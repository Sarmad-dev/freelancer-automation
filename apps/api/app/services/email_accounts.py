"""Connected mailboxes: OAuth connect/callback, token handling, sync, health checks and disconnect.

Rules enforced here (and tested):
- Tokens live only in the encrypted credential store; no token ever reaches a response, a log line or the browser.
- The OAuth ``state`` is a single-use, expiring, server-side record bound to the user and workspace that started it;
  PKCE protects the code exchange.
- An account is ``connected`` only after a real provider call succeeded. A revoked or expired grant becomes
  ``needs_reauth`` with a stable reason code; transient failures never downgrade a working account.
- Sync is idempotent: provider ids are unique per account, the cursor moves only after a page is stored, and a stale
  cursor falls back to a full sync.
- The demo mailbox and real mailboxes are separate (``is_demo`` / provider ``demo``) and never mixed.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import logging
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Membership
from app.db.models_crm import Contact, Lead
from app.db.models_email import Conversation, CredentialSecret, EmailAccount, Message
from app.deps import WorkspaceContext
from app.errors import AppError
from app.mailbox.connector import EmailConnector
from app.mailbox.errors import (
    AccessRevoked,
    AuthExpired,
    EmailError,
    HistoryExpired,
    InsufficientScopes,
    NotConfigured,
    PermanentError,
    RateLimited,
    TransientError,
)
from app.mailbox.gmail import REQUIRED_SCOPES
from app.mailbox.registry import ConnectorRegistry
from app.mailbox.types import AccountProfile, RemoteMessage, SyncPage, TokenSet
from app.security.credentials import CredentialError, CredentialStore
from app.services import leads as lead_service

logger = logging.getLogger("freelancer_os.email")

PENDING_PURPOSE = "email_oauth_pending"
TOKEN_PURPOSE = "email_oauth"
PENDING_TTL = timedelta(minutes=10)
REFRESH_MARGIN = timedelta(seconds=90)

# What each stable code means to a person. Nothing here comes from the provider's own text.
ERROR_MESSAGES = {
    "access_revoked": "Access to this mailbox was removed or expired. Reconnect it to continue.",
    "insufficient_scopes": "The mailbox was connected without all the permissions Freelancer OS needs. Reconnect and allow them.",
    "credentials_unreadable": "The saved connection could not be read. Reconnect the mailbox.",
    "rate_limited": "The email provider asked us to slow down. Syncing will work again shortly.",
    "provider_unavailable": "The email provider is not responding. The last sync did not finish; try again shortly.",
    "provider_rejected": "The email provider rejected a request. Check the connection and try again.",
}


@dataclass
class SyncSummary:
    conversations_created: int = 0
    messages_created: int = 0
    messages_updated: int = 0
    skipped: int = 0
    pages: int = 0
    complete: bool = False
    rate_limited_until: datetime | None = None
    error_code: str | None = None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def friendly_error(code: str | None) -> str | None:
    return ERROR_MESSAGES.get(code) if code else None


# ---------------------------------------------------------------------- accounts


def get_demo_account(db: Session, ctx: WorkspaceContext) -> tuple[EmailAccount, bool]:
    from app.mailbox.demo import DEMO_ACCOUNT_ID, DEMO_ADDRESS, DEMO_DISPLAY_NAME

    existing = db.scalar(
        select(EmailAccount).where(
            EmailAccount.workspace_id == ctx.workspace_id,
            EmailAccount.provider == "demo",
            EmailAccount.provider_account_id == DEMO_ACCOUNT_ID,
        )
    )
    if existing is not None:
        return existing, False
    account = EmailAccount(
        workspace_id=ctx.workspace_id,
        provider="demo",
        provider_account_id=DEMO_ACCOUNT_ID,
        email_address=DEMO_ADDRESS,
        display_name=DEMO_DISPLAY_NAME,
        status="demo",
        is_demo=True,
    )
    db.add(account)
    db.flush()
    return account, True


def set_problem(account: EmailAccount, code: str, *, reconnect: bool, now: datetime) -> None:
    if reconnect:
        account.status = "needs_reauth"
    account.last_error_code = code[:60]
    account.last_health_check_at = now


def mark_healthy(account: EmailAccount, now: datetime) -> None:
    account.last_error_code = None
    account.rate_limited_until = None
    account.last_health_check_at = now
    if not account.is_demo:
        account.status = "connected"


# ---------------------------------------------------------------------- OAuth


def _pkce_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


def begin_authorization(
    db: Session,
    ctx: WorkspaceContext,
    store: CredentialStore,
    connector: EmailConnector,
    *,
    redirect_uri: str,
    login_hint: str | None = None,
) -> str:
    """Create the single-use pending record and return the provider's consent URL."""
    if connector.manifest.is_demo:
        raise AppError(422, "not_oauth", "The demo mailbox does not use a sign-in.")
    if not connector.configured():
        raise AppError(
            409,
            NotConfigured.code,
            f"{connector.manifest.label} is not set up on this server. An administrator must add the client credentials first.",
        )
    token = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)  # 86 chars: within RFC 7636's 43-128
    cred_id = store.put(
        db,
        ctx.workspace_id,
        PENDING_PURPOSE,
        {
            "token": token,
            "verifier": verifier,
            "user_id": str(ctx.user.id),
            "provider": connector.manifest.key,
            "redirect_uri": redirect_uri,
        },
    )
    state = f"{ctx.workspace_id.hex}.{cred_id.hex}.{token}"
    return connector.authorization_url(
        state=state,
        redirect_uri=redirect_uri,
        code_challenge=_pkce_challenge(verifier),
        login_hint=login_hint,
    )


class OAuthFailure(Exception):
    """Carries a short reason for the redirect back to the web app. Never contains provider text or secrets."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _purge_expired_pending(db: Session, now: datetime) -> None:
    cutoff = now - PENDING_TTL * 3
    for row in db.scalars(
        select(CredentialSecret).where(
            CredentialSecret.purpose == PENDING_PURPOSE, CredentialSecret.created_at < cutoff
        )
    ):
        db.delete(row)


def complete_authorization(
    db: Session,
    user_id: uuid.UUID,
    store: CredentialStore,
    registry: ConnectorRegistry,
    *,
    state: str,
    code: str | None,
    provider_error: str | None,
    now: datetime,
    can_write: Callable[[uuid.UUID, uuid.UUID], bool] | None = None,
) -> tuple[uuid.UUID, EmailAccount]:
    """Finish a consent flow. Raises ``OAuthFailure(reason)`` for anything wrong; the pending record is always consumed."""
    try:
        ws_hex, cred_hex, token = state.split(".", 2)
        workspace_id, cred_id = uuid.UUID(ws_hex), uuid.UUID(cred_hex)
    except ValueError as exc:
        raise OAuthFailure("invalid_state") from exc
    try:
        pending = store.get(db, workspace_id, cred_id)
        row = db.get(CredentialSecret, cred_id)
    except CredentialError as exc:
        raise OAuthFailure("invalid_state") from exc
    if row is None or row.purpose != PENDING_PURPOSE:
        raise OAuthFailure("invalid_state")
    created = _aware(row.created_at)
    # Single use, whatever happens next.
    store.delete(db, workspace_id, cred_id)
    db.flush()
    _purge_expired_pending(db, now)
    if not secrets.compare_digest(pending.get("token", ""), token):
        raise OAuthFailure("invalid_state")
    if now - created > PENDING_TTL:
        raise OAuthFailure("expired")
    if pending.get("user_id") != str(user_id):
        raise OAuthFailure("wrong_user")  # a different signed-in user finished someone else's flow
    membership = db.scalar(
        select(Membership).where(
            Membership.workspace_id == workspace_id, Membership.user_id == user_id
        )
    )
    if membership is None or membership.role != "owner":
        raise OAuthFailure("not_allowed")
    if provider_error:
        raise OAuthFailure("denied" if provider_error == "access_denied" else "provider_error")
    if not code:
        raise OAuthFailure("invalid_state")
    try:
        connector = registry.get(pending["provider"])
        tokens = connector.exchange_code(
            code=code, redirect_uri=pending["redirect_uri"], code_verifier=pending["verifier"]
        )
    except EmailError as exc:
        raise OAuthFailure(
            "exchange_failed" if not isinstance(exc, TransientError) else "provider_unavailable"
        ) from exc
    missing = [s for s in REQUIRED_SCOPES if s not in tokens.scopes]
    if missing:
        # Google lets people untick individual permissions on the consent screen.
        raise OAuthFailure("insufficient_scopes")
    if not tokens.refresh_token:
        raise OAuthFailure("no_refresh_token")
    try:
        profile = connector.profile(tokens.access_token)  # the real connection test
    except EmailError as exc:
        raise OAuthFailure("profile_failed") from exc
    account = _upsert_connected_account(
        db, workspace_id, store, connector.manifest.key, profile, tokens, now
    )
    return workspace_id, account


def _upsert_connected_account(
    db: Session,
    workspace_id: uuid.UUID,
    store: CredentialStore,
    provider: str,
    profile: AccountProfile,
    tokens: TokenSet,
    now: datetime,
) -> EmailAccount:
    secret = {
        "refresh_token": tokens.refresh_token or "",
        "access_token": tokens.access_token,
        "expires_at": tokens.expires_at.isoformat(),
    }
    account = db.scalar(
        select(EmailAccount).where(
            EmailAccount.workspace_id == workspace_id,
            EmailAccount.provider == provider,
            EmailAccount.provider_account_id == profile.account_id,
        )
    )
    if account is None:
        cred_id = store.put(db, workspace_id, TOKEN_PURPOSE, secret)
        account = EmailAccount(
            workspace_id=workspace_id,
            provider=provider,
            provider_account_id=profile.account_id,
            email_address=profile.email_address,
            display_name=profile.display_name,
            status="connected",
            is_demo=False,
            credential_id=cred_id,
            granted_scopes=list(tokens.scopes),
        )
        db.add(account)
    else:
        if account.credential_id is not None:
            with contextlib.suppress(CredentialError):
                store.delete(db, workspace_id, account.credential_id)
        account.credential_id = store.put(db, workspace_id, TOKEN_PURPOSE, secret)
        account.granted_scopes = list(tokens.scopes)
        account.sync_cursor = None  # a fresh grant starts from a full sync
    mark_healthy(account, now)
    db.flush()
    return account


def ensure_access_token(
    db: Session,
    workspace_id: uuid.UUID,
    store: CredentialStore,
    connector: EmailConnector,
    account: EmailAccount,
    now: datetime,
    *,
    force: bool = False,
) -> str:
    """A usable access token, refreshing it when it is about to expire. Raises ``AccessRevoked`` when the grant is gone."""
    if account.is_demo:
        return ""
    if account.credential_id is None:
        raise AccessRevoked()
    try:
        secret = store.get(db, workspace_id, account.credential_id)
    except CredentialError as exc:
        set_problem(account, "credentials_unreadable", reconnect=True, now=now)
        raise AccessRevoked() from exc
    try:
        expires = _aware(datetime.fromisoformat(secret["expires_at"]))
    except (KeyError, ValueError):
        expires = now
    if not force and secret.get("access_token") and expires - REFRESH_MARGIN > now:
        return secret["access_token"]
    refresh_token = secret.get("refresh_token")
    if not refresh_token:
        raise AccessRevoked()
    tokens = connector.refresh(
        refresh_token
    )  # AccessRevoked / TransientError propagate to the caller
    store.update(
        db,
        workspace_id,
        account.credential_id,
        {
            "refresh_token": tokens.refresh_token or refresh_token,
            "access_token": tokens.access_token,
            "expires_at": tokens.expires_at.isoformat(),
        },
    )
    if tokens.scopes:
        account.granted_scopes = list(tokens.scopes)
    db.flush()
    return tokens.access_token


# ---------------------------------------------------------------------- sync


def _problem_response(status: int, code: str, *, retry_after: int | None = None) -> AppError:
    headers = {"Retry-After": str(retry_after)} if retry_after else None
    return AppError(
        status,
        code,
        friendly_error(code) or "The email provider could not complete that request.",
        headers=headers,
    )


def check_usable(account: EmailAccount, now: datetime) -> None:
    if account.status in ("needs_reauth", "disconnected"):
        raise AppError(
            409,
            "reconnect_required",
            friendly_error(account.last_error_code)
            or "This mailbox is not connected. Connect it again to continue.",
        )
    if account.rate_limited_until and _aware(account.rate_limited_until) > now:
        wait = int((_aware(account.rate_limited_until) - now).total_seconds()) + 1
        raise _problem_response(429, "rate_limited", retry_after=wait)


def sync_account(
    db: Session,
    ctx: WorkspaceContext,
    store: CredentialStore,
    registry: ConnectorRegistry,
    account: EmailAccount,
    *,
    now: datetime,
    max_pages: int,
    page_size: int = 25,
) -> SyncSummary:
    connector = registry.get(account.provider)
    if connector.manifest.is_demo != account.is_demo:
        raise AppError(
            409, "provider_mismatch", "This mailbox cannot be synced with that provider."
        )
    check_usable(account, now)
    summary = SyncSummary()
    token = _token_or_problem(db, ctx, store, connector, account, now)
    restarted = False
    refreshed = False
    while summary.pages < max_pages:
        try:
            page = connector.sync(token, cursor=account.sync_cursor, now=now, page_size=page_size)
        except HistoryExpired:
            if restarted:
                _fail(db, account, "provider_rejected", now, reconnect=False)
                raise _problem_response(502, "provider_rejected") from None
            restarted = True
            account.sync_cursor = None
            continue
        except AuthExpired:
            if refreshed:
                _fail(db, account, "access_revoked", now, reconnect=True)
                raise AppError(
                    409, "reconnect_required", ERROR_MESSAGES["access_revoked"]
                ) from None
            refreshed = True
            token = _token_or_problem(db, ctx, store, connector, account, now, force=True)
            continue
        except (AccessRevoked, InsufficientScopes) as exc:
            _fail(db, account, exc.code, now, reconnect=True)
            raise AppError(
                409, "reconnect_required", friendly_error(exc.code) or exc.user_message
            ) from None
        except RateLimited as exc:
            wait = exc.retry_after or 60
            account.rate_limited_until = now + timedelta(seconds=wait)
            account.last_error_code = "rate_limited"
            db.commit()
            summary.rate_limited_until = account.rate_limited_until
            summary.error_code = "rate_limited"
            if summary.pages == 0:
                raise _problem_response(429, "rate_limited", retry_after=wait) from None
            return summary
        except TransientError:
            account.last_error_code = "provider_unavailable"
            db.commit()
            summary.error_code = "provider_unavailable"
            if summary.pages == 0:
                raise _problem_response(503, "provider_unavailable") from None
            return summary
        except PermanentError:
            _fail(db, account, "provider_rejected", now, reconnect=False)
            raise _problem_response(502, "provider_rejected") from None
        _store_page(db, ctx, account, page, summary)
        account.sync_cursor = page.cursor
        mark_healthy(account, now)
        summary.pages += 1
        if page.done:
            account.last_synced_at = now
            summary.complete = True
        db.commit()
        if page.done:
            break
    return summary


def _token_or_problem(
    db: Session,
    ctx: WorkspaceContext,
    store: CredentialStore,
    connector: EmailConnector,
    account: EmailAccount,
    now: datetime,
    *,
    force: bool = False,
) -> str:
    try:
        return ensure_access_token(
            db, ctx.workspace_id, store, connector, account, now, force=force
        )
    except AccessRevoked as exc:
        _fail(db, account, account.last_error_code or exc.code, now, reconnect=True)
        raise AppError(
            409, "reconnect_required", friendly_error(account.last_error_code) or exc.user_message
        ) from None
    except TransientError:
        account.last_error_code = "provider_unavailable"
        db.commit()
        raise _problem_response(503, "provider_unavailable") from None
    except RateLimited as exc:
        account.rate_limited_until = now + timedelta(seconds=exc.retry_after or 60)
        account.last_error_code = "rate_limited"
        db.commit()
        raise _problem_response(429, "rate_limited", retry_after=exc.retry_after or 60) from None
    except EmailError:
        _fail(db, account, "provider_rejected", now, reconnect=False)
        raise _problem_response(502, "provider_rejected") from None


def _fail(db: Session, account: EmailAccount, code: str, now: datetime, *, reconnect: bool) -> None:
    set_problem(account, code, reconnect=reconnect, now=now)
    if not reconnect and not account.is_demo:
        account.status = "error"
    db.commit()


def _counterparts(account: EmailAccount, rm: RemoteMessage) -> tuple[str, ...]:
    if rm.direction == "inbound":
        return (rm.from_address,)
    return tuple(a for a in rm.to_addresses if a != account.email_address)


def _find_contact_and_lead(
    db: Session, workspace_id: uuid.UUID, addresses: tuple[str, ...]
) -> tuple[Contact | None, Lead | None]:
    for address in addresses:
        contact = db.scalar(
            select(Contact).where(
                Contact.workspace_id == workspace_id,
                Contact.email_normalized == address,
                Contact.archived_at.is_(None),
            )
        )
        if contact is not None:
            lead = db.scalar(
                select(Lead)
                .where(
                    Lead.workspace_id == workspace_id,
                    Lead.contact_id == contact.id,
                    Lead.archived_at.is_(None),
                )
                .order_by(Lead.updated_at.desc())
                .limit(1)
            )
            return contact, lead
    return None, None


def _store_page(
    db: Session,
    ctx: WorkspaceContext,
    account: EmailAccount,
    page: SyncPage,
    summary: SyncSummary,
) -> None:
    """Upsert one page atomically. A concurrent run that stored the same ids first is tolerated (retry once)."""
    for attempt in range(2):
        try:
            with db.begin_nested():
                counts = _upsert_messages(db, ctx, account, page)
        except IntegrityError:
            if attempt:
                raise
            continue
        summary.conversations_created += counts[0]
        summary.messages_created += counts[1]
        summary.messages_updated += counts[2]
        summary.skipped += page.skipped
        return


def _upsert_messages(
    db: Session, ctx: WorkspaceContext, account: EmailAccount, page: SyncPage
) -> tuple[int, int, int]:
    wid = ctx.workspace_id
    ids = [m.provider_message_id for m in page.messages]
    threads = {m.provider_thread_id for m in page.messages}
    existing = {
        m.provider_message_id: m
        for m in db.scalars(
            select(Message).where(
                Message.email_account_id == account.id, Message.provider_message_id.in_(ids)
            )
        )
    }
    conversations = {
        c.provider_thread_id: c
        for c in db.scalars(
            select(Conversation).where(
                Conversation.email_account_id == account.id,
                Conversation.provider_thread_id.in_(threads),
            )
        )
    }
    created_conv = created_msg = updated_msg = 0
    for rm in sorted(page.messages, key=lambda m: m.sent_at):
        conv = conversations.get(rm.provider_thread_id)
        if conv is None:
            conv = Conversation(
                workspace_id=wid,
                email_account_id=account.id,
                provider_thread_id=rm.provider_thread_id,
                subject=rm.subject,
                unread=False,
                is_sample=account.is_demo,
            )
            db.add(conv)
            db.flush()
            conversations[rm.provider_thread_id] = conv
            created_conv += 1
        message = existing.get(rm.provider_message_id)
        attachments = [
            {"filename": a.filename, "mime_type": a.mime_type, "size": a.size}
            for a in rm.attachments
        ]
        if message is not None:
            changed = False
            for attr, value in (
                ("snippet", rm.snippet),
                ("subject", rm.subject),
                ("attachments", attachments),
            ):
                if getattr(message, attr) != value:
                    setattr(message, attr, value)
                    changed = True
            updated_msg += int(changed)
            continue
        message = Message(
            workspace_id=wid,
            email_account_id=account.id,
            conversation_id=conv.id,
            provider_message_id=rm.provider_message_id,
            direction=rm.direction,
            delivery_state="demo"
            if account.is_demo
            else "sent"
            if rm.direction == "outbound"
            else "unknown",
            from_address=rm.from_address,
            to_addresses=list(rm.to_addresses),
            subject=rm.subject,
            snippet=rm.snippet,
            attachments=attachments,
            sent_at=rm.sent_at,
            is_sample=account.is_demo,
        )
        db.add(message)
        created_msg += 1
        last = _aware(conv.last_message_at) if conv.last_message_at else None
        if last is None or _aware(rm.sent_at) > last:
            conv.last_message_at = rm.sent_at
        if rm.direction == "inbound" and rm.unread:
            conv.unread = True
        if conv.contact_id is None:
            contact, lead = _find_contact_and_lead(db, wid, _counterparts(account, rm))
            if contact is not None:
                conv.contact_id = contact.id
                conv.lead_id = lead.id if lead else None
        if conv.lead_id is not None:
            lead = db.get(Lead, conv.lead_id)
            if lead is not None:
                when = _aware(rm.sent_at)
                newer = lead.last_activity_at is None or when > _aware(lead.last_activity_at)
                lead_service.add_activity(
                    db,
                    ctx,
                    lead,
                    "email",
                    ("Email received: " if rm.direction == "inbound" else "Email sent: ")
                    + (rm.subject or "(no subject)"),
                    details={"direction": rm.direction, "demo": account.is_demo},
                    actor=False,
                    bump=newer,
                    when=when,
                )
    db.flush()
    return created_conv, created_msg, updated_msg


# ---------------------------------------------------------------------- health, disconnect


def test_connection(
    db: Session,
    ctx: WorkspaceContext,
    store: CredentialStore,
    registry: ConnectorRegistry,
    account: EmailAccount,
    *,
    now: datetime,
) -> bool:
    """A REAL provider call. Only a success moves the account to ``connected`` and stamps the check time."""
    connector = registry.get(account.provider)
    if account.is_demo:
        account.last_health_check_at = now
        db.commit()
        return True
    if account.status == "disconnected":
        raise AppError(
            409,
            "reconnect_required",
            "This mailbox is not connected. Connect it again to continue.",
        )
    token = _token_or_problem(db, ctx, store, connector, account, now)
    try:
        connector.profile(token)
    except AuthExpired:
        token = _token_or_problem(db, ctx, store, connector, account, now, force=True)
        try:
            connector.profile(token)
        except AuthExpired:
            _fail(db, account, "access_revoked", now, reconnect=True)
            raise AppError(409, "reconnect_required", ERROR_MESSAGES["access_revoked"]) from None
        except EmailError as exc:
            return _health_failure(db, account, exc, now)
    except (AccessRevoked, InsufficientScopes) as exc:
        _fail(db, account, exc.code, now, reconnect=True)
        raise AppError(
            409, "reconnect_required", friendly_error(exc.code) or exc.user_message
        ) from None
    except EmailError as exc:
        return _health_failure(db, account, exc, now)
    mark_healthy(account, now)
    db.commit()
    return True


def _health_failure(db: Session, account: EmailAccount, exc: EmailError, now: datetime) -> bool:
    if isinstance(exc, RateLimited):
        account.rate_limited_until = now + timedelta(seconds=exc.retry_after or 60)
        account.last_error_code = "rate_limited"
    else:
        account.last_error_code = (
            "provider_unavailable" if isinstance(exc, TransientError) else "provider_rejected"
        )
    account.last_health_check_at = now
    db.commit()
    return False


def disconnect(
    db: Session,
    ctx: WorkspaceContext,
    store: CredentialStore,
    registry: ConnectorRegistry,
    account: EmailAccount,
    *,
    now: datetime,
) -> bool:
    """Revoke at the provider (best effort), delete our copy of the credentials, keep the mail history.

    Returns whether the provider confirmed revocation. The local disconnect succeeds either way: a provider outage must
    never keep a person's credentials in our database.
    """
    revoked = account.is_demo
    if account.credential_id is not None:
        connector = registry.get(account.provider)
        try:
            secret = store.get(db, ctx.workspace_id, account.credential_id)
        except CredentialError:
            secret = {}
        for key in ("refresh_token", "access_token"):
            if secret.get(key):
                try:
                    revoked = connector.revoke(secret[key])
                except EmailError:
                    revoked = False
                break
        with contextlib.suppress(CredentialError):
            store.delete(db, ctx.workspace_id, account.credential_id)
        account.credential_id = None
    if not account.is_demo:
        account.status = "disconnected"
        account.sync_cursor = None
        account.last_error_code = None if revoked else "revocation_unconfirmed"
        account.rate_limited_until = None
        account.granted_scopes = []
    account.last_health_check_at = now
    db.flush()
    return revoked
