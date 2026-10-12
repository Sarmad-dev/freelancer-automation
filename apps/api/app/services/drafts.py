"""Drafts, approval and sending.

The send path is the product's most consequential side effect, so every rule is enforced HERE, server-side, in this order:

1. the draft must be ``approved`` AND the text must still be exactly what was approved (approval binds to a hash);
2. an idempotency key is recorded before anything leaves, and a repeated key returns the earlier outcome;
3. the recipient must not be on the suppression list;
4. the sending mailbox must be usable (connected, not rate-limited) and the workspace's send limits must allow it;
5. the attempt is committed as ``queued`` BEFORE the provider is called, so a crash can never lead to a silent second send;
6. an ambiguous provider result (timeout, 5xx) is recorded as ``unknown`` and is never retried automatically.

Every outcome is audited with fixed vocabulary only (provider, state, reason code); never addresses or content.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.api.scoping import get_scoped_or_404, scoped_select
from app.config import Settings
from app.db.models_crm import Lead
from app.db.models_email import Conversation, Draft, EmailAccount, Message
from app.deps import WorkspaceContext
from app.errors import AppError
from app.mailbox.connector import EmailConnector
from app.mailbox.errors import (
    AccessRevoked,
    AuthExpired,
    EmailError,
    InsufficientScopes,
    PermanentError,
    RateLimited,
    SendOutcomeUnknown,
    TransientError,
)
from app.mailbox.mime import normalize_address
from app.mailbox.registry import ConnectorRegistry
from app.mailbox.types import OutgoingMessage, SendResult
from app.ratelimit import RateLimiter
from app.schemas.drafts import DraftCreate, DraftPatch
from app.security.credentials import CredentialStore
from app.services import email_accounts as accounts
from app.services import leads as lead_service
from app.services import suppression

logger = logging.getLogger("freelancer_os.email")

DELIVERY_LABELS = {
    "demo": "Demo only: nothing was delivered to anyone.",
    "queued": "Queued: the provider has not confirmed it yet.",
    "sent": "Sent.",
    "failed": "Failed: the message was not sent.",
    "unknown": "Unknown: the provider did not confirm. Check your mailbox before sending again.",
}
EDITABLE = ("draft", "pending_approval", "approved", "rejected")


def delivery_label(state: str) -> str:
    return DELIVERY_LABELS.get(state, DELIVERY_LABELS["unknown"])


def content_hash(to_address: str | None, subject: str, body: str) -> str:
    """What approval binds to: the normalised recipient, the subject and the body, exactly."""
    to = normalize_address(to_address) if to_address else None
    payload = json.dumps(
        [to or "", subject.strip(), body], ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def approval_is_current(draft: Draft) -> bool:
    return (
        draft.status == "approved"
        and draft.approved_content_hash is not None
        and draft.approved_content_hash
        == content_hash(draft.to_address, draft.subject, draft.body_text)
    )


def _invalid(field: str, message: str) -> AppError:
    return AppError(422, "validation_error", message, fields={field: message})


def _recipient(raw: str | None) -> str | None:
    if raw is None or not raw.strip():
        return None
    norm = normalize_address(raw)
    if norm is None:
        raise _invalid("to_address", "Enter one valid email address.")
    return norm


def _check_links(
    db: Session,
    ctx: WorkspaceContext,
    *,
    lead_id: uuid.UUID | None,
    conversation_id: uuid.UUID | None,
    account_id: uuid.UUID | None,
) -> None:
    if lead_id is not None:
        get_scoped_or_404(db, Lead, ctx, lead_id, code="lead_not_found", message="Lead not found.")
    if conversation_id is not None:
        get_scoped_or_404(
            db,
            Conversation,
            ctx,
            conversation_id,
            code="conversation_not_found",
            message="Conversation not found.",
        )
    if account_id is not None:
        get_scoped_or_404(
            db,
            EmailAccount,
            ctx,
            account_id,
            code="email_account_not_found",
            message="Mailbox not found.",
        )


def create_draft(db: Session, ctx: WorkspaceContext, data: DraftCreate) -> Draft:
    _check_links(
        db,
        ctx,
        lead_id=data.lead_id,
        conversation_id=data.conversation_id,
        account_id=data.email_account_id,
    )
    to = _recipient(data.to_address)
    draft = Draft(
        workspace_id=ctx.workspace_id,
        lead_id=data.lead_id,
        conversation_id=data.conversation_id,
        email_account_id=data.email_account_id,
        to_address=to,
        subject=data.subject,
        body_text=data.body_text,
        status="draft",
        author="user",
        content_hash=content_hash(to, data.subject, data.body_text),
    )
    db.add(draft)
    db.flush()
    return draft


def send_locked(draft: Draft) -> bool:
    return draft.send_idempotency_key is not None or draft.status in ("sent", "discarded")


def update_draft(db: Session, ctx: WorkspaceContext, draft: Draft, patch: DraftPatch) -> list[str]:
    """Edit a draft. Any change withdraws an earlier approval: what gets sent is only ever what was approved."""
    if send_locked(draft):
        raise AppError(
            409,
            "draft_locked",
            "This draft has been sent or is being sent, so it can no longer be edited.",
        )
    fields = patch.model_fields_set
    changed: list[str] = []
    if "email_account_id" in fields:
        _check_links(db, ctx, lead_id=None, conversation_id=None, account_id=patch.email_account_id)
        if patch.email_account_id != draft.email_account_id:
            draft.email_account_id = patch.email_account_id
            changed.append("email_account_id")
    if "to_address" in fields:
        to = _recipient(patch.to_address)
        if to != draft.to_address:
            draft.to_address = to
            changed.append("to_address")
    if "subject" in fields and patch.subject is not None and patch.subject != draft.subject:
        draft.subject = patch.subject
        changed.append("subject")
    if "body_text" in fields and patch.body_text is not None and patch.body_text != draft.body_text:
        draft.body_text = patch.body_text
        changed.append("body_text")
    if changed:
        draft.content_hash = content_hash(draft.to_address, draft.subject, draft.body_text)
        draft.version += 1
        if draft.status in ("approved", "pending_approval", "rejected"):
            draft.status = "draft"
        draft.approved_content_hash = None
        draft.approved_at = None
        draft.approved_by_user_id = None
    return changed


def approve(db: Session, ctx: WorkspaceContext, draft: Draft, now: datetime) -> None:
    if send_locked(draft):
        raise AppError(409, "draft_locked", "This draft has been sent or discarded.")
    problems: dict[str, str] = {}
    if _recipient(draft.to_address) is None:
        problems["to_address"] = "Add the recipient's email address before approving."
    if not draft.subject.strip():
        problems["subject"] = "Add a subject before approving."
    if not draft.body_text.strip():
        problems["body_text"] = "Write the message before approving."
    if problems:
        raise AppError(
            422, "validation_error", "The draft is not ready to approve.", fields=problems
        )
    draft.content_hash = content_hash(draft.to_address, draft.subject, draft.body_text)
    draft.approved_content_hash = draft.content_hash
    draft.approved_at = now
    draft.approved_by_user_id = ctx.user.id
    draft.status = "approved"


def discard(draft: Draft) -> None:
    if send_locked(draft):
        raise AppError(409, "draft_locked", "This draft has been sent or is being sent.")
    draft.status = "discarded"
    draft.approved_content_hash = None
    draft.approved_at = None


def get_message(db: Session, workspace_id: uuid.UUID, draft_id: uuid.UUID) -> Message | None:
    return db.scalar(
        select(Message).where(Message.workspace_id == workspace_id, Message.draft_id == draft_id)
    )


# ---------------------------------------------------------------------- sending


def _audit(
    db: Session,
    ctx: WorkspaceContext,
    info: audit.RequestInfo,
    action: str,
    draft: Draft,
    **details: object,
) -> None:
    audit.record(
        db,
        action,
        info=info,
        actor_user_id=ctx.user.id,
        workspace_id=ctx.workspace_id,
        target_type="draft",
        target_id=str(draft.id),
        details=dict(details),
    )


def _pick_account(
    db: Session, ctx: WorkspaceContext, draft: Draft, conversation: Conversation | None
) -> EmailAccount:
    if conversation is not None:
        account = db.get(EmailAccount, conversation.email_account_id)
        if account is None or account.workspace_id != ctx.workspace_id:
            raise AppError(404, "email_account_not_found", "Mailbox not found.")
        if draft.email_account_id and draft.email_account_id != account.id:
            raise AppError(409, "account_mismatch", "This reply belongs to a different mailbox.")
        return account
    if draft.email_account_id is not None:
        return get_scoped_or_404(
            db,
            EmailAccount,
            ctx,
            draft.email_account_id,
            code="email_account_not_found",
            message="Mailbox not found.",
        )
    usable = list(
        db.scalars(
            scoped_select(EmailAccount, ctx).where(EmailAccount.status.in_(("connected", "demo")))
        )
    )
    if len(usable) == 1:
        return usable[0]
    raise AppError(
        422,
        "email_account_required",
        "Choose which mailbox to send from."
        if usable
        else "Connect a mailbox (or add the demo mailbox) before sending.",
        fields={"email_account_id": "Choose a mailbox."},
    )


def _enforce_send_limits(settings: Settings, limiter: RateLimiter, workspace_id: uuid.UUID) -> None:
    for window, limit, name in (
        (3600, settings.email_send_limit_per_hour, "hour"),
        (86_400, settings.email_send_limit_per_day, "day"),
    ):
        decision = limiter.hit(f"email-send:{name}:{workspace_id}", limit, window)
        if not decision.allowed:
            raise AppError(
                429,
                "send_rate_limited",
                f"This workspace has reached its sending limit for the {name}. Try again later.",
                headers={"Retry-After": str(decision.retry_after)},
            )


class SendResultInfo:
    def __init__(
        self, draft: Draft, message: Message, *, replayed: bool, unknown: bool = False
    ) -> None:
        self.draft = draft
        self.message = message
        self.replayed = replayed
        self.unknown = unknown


def send_draft(
    db: Session,
    ctx: WorkspaceContext,
    draft_id: uuid.UUID,
    idempotency_key: str,
    *,
    now: datetime,
    info: audit.RequestInfo,
    settings: Settings,
    store: CredentialStore,
    registry: ConnectorRegistry,
    limiter: RateLimiter,
) -> SendResultInfo:
    draft = db.scalar(
        select(Draft)
        .where(Draft.id == draft_id, Draft.workspace_id == ctx.workspace_id)
        .with_for_update()
    )
    if draft is None:
        raise AppError(404, "draft_not_found", "Draft not found.")
    message = get_message(db, ctx.workspace_id, draft.id)

    # 2. a repeated key returns the earlier outcome; any other key cannot start a second send
    if draft.send_idempotency_key is not None:
        if draft.send_idempotency_key == idempotency_key and message is not None:
            return SendResultInfo(draft, message, replayed=True)
        state = message.delivery_state if message else "queued"
        if state == "unknown":
            raise AppError(
                409,
                "send_outcome_unknown",
                "The last attempt was not confirmed by the provider. Check your mailbox, then mark it as sent or not sent before trying again.",
            )
        if draft.status == "sent":
            raise AppError(409, "already_sent", "This draft has already been sent.")
        raise AppError(409, "send_in_progress", "This draft is already being sent.")
    other = db.scalar(
        select(Draft.id).where(
            Draft.workspace_id == ctx.workspace_id,
            Draft.send_idempotency_key == idempotency_key,
            Draft.id != draft.id,
        )
    )
    if other is not None:
        raise AppError(
            409,
            "idempotency_key_conflict",
            "That idempotency key was already used for a different draft.",
        )

    # 1. approval, bound to the exact text
    if draft.status != "approved":
        raise AppError(409, "draft_not_approved", "Approve this draft before sending it.")
    if not approval_is_current(draft):
        raise AppError(
            409,
            "draft_changed",
            "The draft changed after it was approved. Review and approve it again.",
        )
    recipient = _recipient(draft.to_address)
    if recipient is None:
        raise AppError(409, "invalid_recipient", "The recipient address is missing or invalid.")

    # 3. suppression, checked here and only here at send time
    entry = suppression.find(db, ctx.workspace_id, recipient)
    if entry is not None:
        _audit(db, ctx, info, "email.send_blocked", draft, reason="suppressed")
        db.commit()
        raise AppError(
            409,
            "recipient_suppressed",
            "This person is on your do-not-contact list, so the message was not sent.",
        )

    # 4. mailbox and limits
    conversation = (
        db.get(Conversation, draft.conversation_id)
        if draft.conversation_id and message is None
        else (db.get(Conversation, message.conversation_id) if message else None)
    )
    account = _pick_account(db, ctx, draft, conversation)
    connector = registry.get(account.provider)
    if connector.manifest.is_demo != account.is_demo:
        raise AppError(409, "provider_mismatch", "This mailbox cannot send with that provider.")
    if not connector.configured():
        raise AppError(
            409,
            "provider_not_configured",
            f"{connector.manifest.label} is not set up on this server.",
        )
    accounts.check_usable(account, now)
    _enforce_send_limits(settings, limiter, ctx.workspace_id)

    # 5. record the attempt before anything leaves
    if message is None:
        if conversation is None:
            conversation = _new_conversation(db, ctx, account, draft, recipient)
        message = Message(
            workspace_id=ctx.workspace_id,
            email_account_id=account.id,
            conversation_id=conversation.id,
            provider_message_id=f"pending:{draft.id.hex}",
            direction="outbound",
            delivery_state="queued",
            from_address=account.email_address,
            to_addresses=[recipient],
            subject=draft.subject,
            snippet=draft.body_text[:200],
            draft_id=draft.id,
            sent_at=now,
            is_sample=account.is_demo,
        )
        db.add(message)
    else:  # a previous attempt definitely failed: reuse its row
        message.delivery_state = "queued"
        message.delivery_error_code = None
        message.sent_at = now
    draft.send_idempotency_key = idempotency_key
    draft.email_account_id = account.id
    thread_id = (
        conversation.provider_thread_id
        if conversation and not conversation.provider_thread_id.startswith("local:")
        else None
    )
    _audit(db, ctx, info, "email.send_queued", draft, provider=account.provider, state="queued")
    db.commit()

    outgoing = OutgoingMessage(
        from_address=account.email_address,
        to_address=recipient,
        subject=draft.subject,
        body_text=draft.body_text,
        thread_id=thread_id,
    )
    try:
        result = _call_provider(db, ctx, store, connector, account, outgoing, now)
    except SendOutcomeUnknown:
        return _finish_unknown(db, ctx, info, draft, message, account, "send_outcome_unknown")
    except (AccessRevoked, InsufficientScopes, AuthExpired) as exc:
        code = "access_revoked" if not isinstance(exc, InsufficientScopes) else exc.code
        accounts.set_problem(account, code, reconnect=True, now=now)
        _finish_failed(db, ctx, info, draft, message, account, code)
        raise AppError(
            409, "reconnect_required", accounts.friendly_error(code) or exc.user_message
        ) from None
    except RateLimited as exc:
        wait = exc.retry_after or 60
        account.rate_limited_until = now + timedelta(seconds=wait)
        account.last_error_code = "rate_limited"
        _finish_failed(db, ctx, info, draft, message, account, "rate_limited")
        raise AppError(
            429,
            "rate_limited",
            accounts.ERROR_MESSAGES["rate_limited"],
            headers={"Retry-After": str(wait)},
        ) from None
    except TransientError:
        _finish_failed(db, ctx, info, draft, message, account, "provider_unavailable")
        raise AppError(
            503, "provider_unavailable", accounts.ERROR_MESSAGES["provider_unavailable"]
        ) from None
    except (PermanentError, EmailError):
        _finish_failed(db, ctx, info, draft, message, account, "provider_rejected")
        raise AppError(
            502, "provider_rejected", accounts.ERROR_MESSAGES["provider_rejected"]
        ) from None
    except Exception:
        # Anything unexpected after the request may have left: never assume it failed.
        logger.exception("unexpected error while sending; outcome recorded as unknown")
        return _finish_unknown(db, ctx, info, draft, message, account, "unexpected_error")

    _finish_sent(
        db,
        ctx,
        info,
        draft,
        message,
        account,
        result.provider_message_id,
        result.provider_thread_id,
        result.delivery_state,
        now,
    )
    return SendResultInfo(draft, message, replayed=False)


def _call_provider(
    db: Session,
    ctx: WorkspaceContext,
    store: CredentialStore,
    connector: EmailConnector,
    account: EmailAccount,
    outgoing: OutgoingMessage,
    now: datetime,
) -> SendResult:
    token = accounts.ensure_access_token(db, ctx.workspace_id, store, connector, account, now)
    try:
        return connector.send(token, outgoing)
    except AuthExpired:
        # A 401 means the request was rejected before sending, so one retry with a fresh token is safe.
        token = accounts.ensure_access_token(
            db, ctx.workspace_id, store, connector, account, now, force=True
        )
        return connector.send(token, outgoing)


def _new_conversation(
    db: Session, ctx: WorkspaceContext, account: EmailAccount, draft: Draft, recipient: str
) -> Conversation:
    contact, lead = accounts._find_contact_and_lead(db, ctx.workspace_id, (recipient,))
    conversation = Conversation(
        workspace_id=ctx.workspace_id,
        email_account_id=account.id,
        provider_thread_id=f"local:{uuid.uuid4().hex}",
        subject=draft.subject,
        lead_id=draft.lead_id or (lead.id if lead else None),
        contact_id=contact.id if contact else None,
        unread=False,
        is_sample=account.is_demo,
    )
    db.add(conversation)
    db.flush()
    draft.conversation_id = conversation.id
    return conversation


def _finish_failed(
    db: Session,
    ctx: WorkspaceContext,
    info: audit.RequestInfo,
    draft: Draft,
    message: Message,
    account: EmailAccount,
    code: str,
) -> None:
    message.delivery_state = "failed"
    message.delivery_error_code = code
    draft.send_idempotency_key = None  # nothing was sent, so a retry is allowed
    _audit(
        db,
        ctx,
        info,
        "email.send_failed",
        draft,
        provider=account.provider,
        state="failed",
        reason=code,
    )
    db.commit()


def _finish_unknown(
    db: Session,
    ctx: WorkspaceContext,
    info: audit.RequestInfo,
    draft: Draft,
    message: Message,
    account: EmailAccount,
    code: str,
) -> SendResultInfo:
    message.delivery_state = "unknown"
    message.delivery_error_code = code
    _audit(
        db,
        ctx,
        info,
        "email.send_unknown",
        draft,
        provider=account.provider,
        state="unknown",
        reason=code,
    )
    db.commit()
    return SendResultInfo(draft, message, replayed=False, unknown=True)


def _finish_sent(
    db: Session,
    ctx: WorkspaceContext,
    info: audit.RequestInfo,
    draft: Draft,
    message: Message,
    account: EmailAccount,
    provider_message_id: str,
    provider_thread_id: str,
    state: str,
    now: datetime,
) -> None:
    merged = False
    clash = db.scalar(
        select(Message).where(
            Message.email_account_id == account.id,
            Message.provider_message_id == provider_message_id,
            Message.id != message.id,
        )
    )
    conversation = db.get(Conversation, message.conversation_id)
    if clash is not None:
        # A sync stored the same message first: keep that row, carry our draft link and state onto it.
        merged = True
        db.delete(message)
        db.flush()
        clash.draft_id = draft.id
        clash.delivery_state = state
        clash.delivery_error_code = None
        message = clash
    else:
        message.provider_message_id = provider_message_id
        message.delivery_state = state
        message.delivery_error_code = None
    if conversation is not None and conversation.provider_thread_id.startswith("local:"):
        taken = db.scalar(
            select(Conversation.id).where(
                Conversation.email_account_id == account.id,
                Conversation.provider_thread_id == provider_thread_id,
                Conversation.id != conversation.id,
            )
        )
        if taken is None:
            conversation.provider_thread_id = provider_thread_id
    if conversation is not None:
        conversation.last_message_at = now
    draft.status = "sent"
    draft.sent_at = now
    if not merged and draft.lead_id is not None:
        lead = db.get(Lead, draft.lead_id)
        if lead is not None:
            lead_service.add_activity(
                db,
                ctx,
                lead,
                "email",
                f"Email sent: {draft.subject}"[:500],
                details={"direction": "outbound", "demo": account.is_demo},
            )
    _audit(db, ctx, info, "email.sent", draft, provider=account.provider, state=state)
    db.commit()


def resolve_send(
    db: Session,
    ctx: WorkspaceContext,
    draft_id: uuid.UUID,
    outcome: str,
    *,
    now: datetime,
    info: audit.RequestInfo,
) -> tuple[Draft, Message]:
    """The owner checked the mailbox after an unconfirmed send and says what happened."""
    draft = db.scalar(
        select(Draft)
        .where(Draft.id == draft_id, Draft.workspace_id == ctx.workspace_id)
        .with_for_update()
    )
    if draft is None:
        raise AppError(404, "draft_not_found", "Draft not found.")
    message = get_message(db, ctx.workspace_id, draft.id)
    if message is None or message.delivery_state not in ("unknown", "queued"):
        raise AppError(409, "nothing_to_resolve", "This draft has no unconfirmed send to resolve.")
    if outcome == "sent":
        message.delivery_state = "sent"
        message.delivery_error_code = "confirmed_manually"
        draft.status = "sent"
        draft.sent_at = draft.sent_at or now
    else:
        message.delivery_state = "failed"
        message.delivery_error_code = "confirmed_not_sent"
        draft.send_idempotency_key = None
    _audit(db, ctx, info, "email.send_resolved", draft, state=message.delivery_state)
    db.commit()
    return draft, message
