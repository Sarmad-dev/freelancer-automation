"""Reading the inbox: the conversation list, a thread with its messages, counts, and the few things a person can change
(read state, the category of a reply, deleting synced mail).

Every query is scoped to the workspace. HTML bodies are only ever returned in their sanitised, stored form.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.orm import Session

from app.api.pagination import PageParams, paginate
from app.api.scoping import scoped_select
from app.db.models_crm import Company, Contact, Lead
from app.db.models_email import (
    Conversation,
    Draft,
    EmailAccount,
    EmailJob,
    Message,
    MessageBody,
    SuppressionEntry,
)
from app.deps import WorkspaceContext
from app.errors import AppError
from app.routers._common import like_pattern
from app.schemas.inbox import (
    AttachmentOut,
    BodyOut,
    ClassificationOut,
    CompanyRef,
    ConversationDetail,
    ConversationSummary,
    CounterpartOut,
    InboxCounts,
    LeadRef,
    StopOut,
    ThreadMessage,
)
from app.services import drafts as draft_service
from app.services import email_jobs, suppression
from app.services.email_out import draft_out

OPEN_DRAFT_STATUSES = ("draft", "pending_approval", "approved")

REVIEW_TEXT = {
    "low_confidence": "The system wasn't sure about this one. Check the category before acting on it.",
    "fallback": "The AI provider was unavailable, so a simple keyword rule made this guess. Check it.",
    "injection_suspected": "This message contains text that tries to give instructions to the AI. Read it yourself and check the category.",
    "classification_failed": "This message could not be classified automatically. Choose a category yourself.",
    "unsubscribe_unconfirmed": "This looks like an opt-out, but the wording isn't explicit. Confirm before they are added to your do-not-contact list.",
}
STOP_TEXT = {
    "unsubscribe": "Asked not to be contacted. Nothing will be sent to this address.",
    "bounce": "The address bounced. Nothing will be sent to it.",
    "complaint": "Reported a complaint. Nothing will be sent to this address.",
    "manual": "On your do-not-contact list. Nothing will be sent to this address.",
    "replied_stop": "Replied asking to stop. Nothing will be sent to this address.",
}


def _counterpart(message: Message | None, account: EmailAccount | None) -> str:
    if message is None:
        return ""
    if message.direction == "inbound":
        return message.from_address
    own = account.email_address if account else ""
    return next((a for a in message.to_addresses or [] if a != own), "")


def _latest_messages(
    db: Session, ws: uuid.UUID, ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, Message]:
    if not ids:
        return {}
    ranked = (
        select(
            Message.id.label("id"),
            func.row_number()
            .over(
                partition_by=Message.conversation_id,
                order_by=(Message.sent_at.desc(), Message.id),
            )
            .label("rn"),
        )
        .where(
            Message.workspace_id == ws,
            Message.conversation_id.in_(ids),
            Message.is_bounce.is_(False),
        )
        .subquery()
    )
    rows = db.scalars(
        select(Message).join(ranked, Message.id == ranked.c.id).where(ranked.c.rn == 1)
    )
    return {m.conversation_id: m for m in rows}


def summarize(
    db: Session, ws: uuid.UUID, conversations: Sequence[Conversation]
) -> list[ConversationSummary]:
    """Summaries for a page of conversations using a handful of bulk queries (never one per row)."""
    ids = [c.id for c in conversations]
    if not ids:
        return []
    latest = _latest_messages(db, ws, ids)
    counts: dict[uuid.UUID, int] = {
        conv_id: int(n)
        for conv_id, n in db.execute(
            select(Message.conversation_id, func.count())
            .where(Message.workspace_id == ws, Message.conversation_id.in_(ids))
            .group_by(Message.conversation_id)
        )
    }
    accounts = {
        a.id: a
        for a in db.scalars(
            select(EmailAccount).where(
                EmailAccount.workspace_id == ws,
                EmailAccount.id.in_({c.email_account_id for c in conversations}),
            )
        )
    }
    contacts = {
        c.id: c
        for c in db.scalars(
            select(Contact).where(
                Contact.workspace_id == ws,
                Contact.id.in_({c.contact_id for c in conversations if c.contact_id}),
            )
        )
    }
    leads = {
        ld.id: ld
        for ld in db.scalars(
            select(Lead).where(
                Lead.workspace_id == ws,
                Lead.id.in_({c.lead_id for c in conversations if c.lead_id}),
            )
        )
    }
    company_ids = {ld.company_id for ld in leads.values() if ld.company_id} | {
        ct.company_id for ct in contacts.values() if ct.company_id
    }
    companies = {
        co.id: co
        for co in db.scalars(
            select(Company).where(Company.workspace_id == ws, Company.id.in_(company_ids))
        )
    }
    job_states: dict[uuid.UUID, set[str]] = {}
    for conv_id, status in db.execute(
        select(EmailJob.conversation_id, EmailJob.status).where(
            EmailJob.workspace_id == ws, EmailJob.conversation_id.in_(ids)
        )
    ):
        job_states.setdefault(conv_id, set()).add(status)
    with_draft = set(
        db.scalars(
            select(Draft.conversation_id).where(
                Draft.workspace_id == ws,
                Draft.conversation_id.in_(ids),
                Draft.status.in_(OPEN_DRAFT_STATUSES),
            )
        )
    )
    addresses = {
        a: _counterpart(latest.get(c.id), accounts.get(c.email_account_id))
        for c, a in ((c, c.id) for c in conversations)
    }
    stops = {
        e.email_normalized: e
        for e in db.scalars(
            select(SuppressionEntry).where(
                SuppressionEntry.workspace_id == ws,
                SuppressionEntry.email_normalized.in_({a.lower() for a in addresses.values() if a}),
            )
        )
    }
    out: list[ConversationSummary] = []
    for c in conversations:
        last = latest.get(c.id)
        account = accounts.get(c.email_account_id)
        address = addresses[c.id]
        contact = contacts.get(c.contact_id) if c.contact_id else None
        lead = leads.get(c.lead_id) if c.lead_id else None
        company_id = (lead.company_id if lead and lead.company_id else None) or (
            contact.company_id if contact else None
        )
        company = companies.get(company_id) if company_id else None
        stop_entry = stops.get(address.lower()) if address else None
        states = job_states.get(c.id, set())
        if states & {"queued", "running"}:
            status = "pending"
        elif c.classification is not None:
            status = "classified"
        elif "failed" in states:
            status = "failed"
        else:
            status = "none"
        out.append(
            ConversationSummary(
                id=c.id,
                account_id=c.email_account_id,
                account_email=account.email_address if account else "",
                is_demo=bool(account and account.is_demo),
                subject=c.subject,
                counterpart=CounterpartOut(
                    address=address, name=contact.full_name if contact else None
                ),
                last_message_at=c.last_message_at,
                last_direction=last.direction if last else None,
                last_preview=last.snippet if last else None,
                message_count=int(counts.get(c.id, 0)),
                unread=c.unread,
                lead=LeadRef(id=lead.id, title=lead.title) if lead else None,
                company=CompanyRef(id=company.id, name=company.name) if company else None,
                classification=ClassificationOut(
                    status=status,
                    category=c.classification,
                    confidence=c.classification_confidence,
                    explanation=c.classification_explanation,
                    evidence=list(c.classification_evidence or []),
                    source=c.classification_source,
                    classified_at=c.classified_at,
                    needs_review=c.needs_review,
                    review_reason=c.review_reason,
                    review_text=REVIEW_TEXT.get(c.review_reason or "") if c.needs_review else None,
                ),
                stop=StopOut(
                    id=stop_entry.id,
                    reason=stop_entry.reason,
                    address=stop_entry.email_normalized,
                    since=stop_entry.created_at,
                    text=STOP_TEXT.get(stop_entry.reason, STOP_TEXT["manual"]),
                )
                if stop_entry
                else None,
                has_draft=c.id in with_draft,
            )
        )
    return out


def list_conversations(
    db: Session,
    ctx: WorkspaceContext,
    params: PageParams,
    *,
    q: str | None,
    unread: bool | None,
    classification: str | None,
    needs_review: bool | None,
    account_id: uuid.UUID | None,
    lead_id: uuid.UUID | None,
    status: str,
) -> tuple[list[ConversationSummary], int]:
    ws = ctx.workspace_id
    stmt = scoped_select(Conversation, ctx).where(Conversation.status == status)
    if unread is not None:
        stmt = stmt.where(Conversation.unread.is_(unread))
    if needs_review is not None:
        stmt = stmt.where(Conversation.needs_review.is_(needs_review))
    if classification == "unclassified":
        stmt = stmt.where(Conversation.classification.is_(None))
    elif classification:
        stmt = stmt.where(Conversation.classification == classification)
    if account_id:
        stmt = stmt.where(Conversation.email_account_id == account_id)
    if lead_id:
        stmt = stmt.where(Conversation.lead_id == lead_id)
    if q:
        like = like_pattern(q)
        in_message = exists().where(
            Message.conversation_id == Conversation.id,
            Message.workspace_id == ws,
            or_(
                func.lower(func.coalesce(Message.subject, "")).like(like, escape="\\"),
                func.lower(Message.from_address).like(like, escape="\\"),
                func.lower(func.coalesce(Message.snippet, "")).like(like, escape="\\"),
            ),
        )
        in_body = exists().where(
            Message.conversation_id == Conversation.id,
            Message.workspace_id == ws,
            MessageBody.message_id == Message.id,
            func.lower(MessageBody.body_text).like(like, escape="\\"),
        )
        by_contact = exists().where(
            Contact.id == Conversation.contact_id,
            Contact.workspace_id == ws,
            func.lower(Contact.full_name).like(like, escape="\\"),
        )
        by_lead = exists().where(
            Lead.id == Conversation.lead_id,
            Lead.workspace_id == ws,
            func.lower(Lead.title).like(like, escape="\\"),
        )
        stmt = stmt.where(
            or_(
                func.lower(func.coalesce(Conversation.subject, "")).like(like, escape="\\"),
                in_message,
                in_body,
                by_contact,
                by_lead,
            )
        )
    sorts: dict[str, Any] = {
        "last_message_at": Conversation.last_message_at,
        "created_at": Conversation.created_at,
    }
    rows, total = paginate(
        db,
        stmt,
        params,
        allowed_sort=sorts,
        default_sort="-last_message_at",
        tie_breaker=Conversation.id,
    )
    return summarize(db, ws, rows), total


def counts(db: Session, ctx: WorkspaceContext) -> InboxCounts:
    base = scoped_select(Conversation, ctx).where(Conversation.status == "open").subquery()

    def n(*where: Any) -> int:
        return int(db.scalar(select(func.count()).select_from(base).where(*where)) or 0)

    return InboxCounts(
        unread=n(base.c.unread.is_(True)),
        needs_review=n(base.c.needs_review.is_(True)),
        open=n(),
    )


def get_detail(
    db: Session, ctx: WorkspaceContext, conversation: Conversation
) -> ConversationDetail:
    ws = ctx.workspace_id
    [summary] = summarize(db, ws, [conversation])
    messages = list(
        db.scalars(
            select(Message)
            .where(Message.workspace_id == ws, Message.conversation_id == conversation.id)
            .order_by(Message.sent_at, Message.created_at, Message.id)
        )
    )
    bodies = {
        b.message_id: b
        for b in db.scalars(
            select(MessageBody).where(
                MessageBody.workspace_id == ws, MessageBody.message_id.in_([m.id for m in messages])
            )
        )
    }
    thread: list[ThreadMessage] = []
    for m in messages:
        b = bodies.get(m.id)
        thread.append(
            ThreadMessage(
                id=m.id,
                direction=m.direction,
                from_address=m.from_address,
                to_addresses=list(m.to_addresses or []),
                subject=m.subject,
                sent_at=m.sent_at,
                attachments=[
                    AttachmentOut(
                        filename=str(a.get("filename", "attachment"))[:200],
                        mime_type=str(a.get("mime_type", "application/octet-stream"))[:100],
                        size=a.get("size") if isinstance(a.get("size"), int) else None,
                    )
                    for a in (m.attachments or [])
                ],
                delivery_state=m.delivery_state,
                delivery_label=draft_service.delivery_label(m.delivery_state),
                delivery_error_code=m.delivery_error_code,
                is_bounce=m.is_bounce,
                body=BodyOut(
                    available=b is not None,
                    text=b.body_text if b else (m.snippet or ""),
                    html=b.body_html if b else None,
                    text_truncated=b.text_truncated if b else False,
                    images_blocked=b.images_blocked if b else False,
                ),
            )
        )
    draft = db.scalar(
        select(Draft)
        .where(
            Draft.workspace_id == ws,
            Draft.conversation_id == conversation.id,
            Draft.status.in_(OPEN_DRAFT_STATUSES),
        )
        .order_by(Draft.updated_at.desc(), Draft.id)
        .limit(1)
    )
    return ConversationDetail(
        **summary.model_dump(), messages=thread, draft=draft_out(db, draft) if draft else None
    )


def set_read(conversation: Conversation, read: bool) -> None:
    conversation.unread = not read


def set_classification(
    db: Session, ctx: WorkspaceContext, conversation: Conversation, category: str, now: Any
) -> bool:
    """A person decides the category (or confirms the suggested one). Returns whether the sender was added to the
    do-not-contact list because the category is ``unsubscribe``."""
    latest = email_jobs.latest_inbound(db, conversation.id)
    if latest is None:
        raise AppError(
            409, "no_reply_to_classify", "This thread has no incoming message to classify."
        )
    conversation.classification = category
    conversation.classification_confidence = 1.0
    conversation.classification_explanation = "Set by you."
    conversation.classification_evidence = []
    conversation.classification_source = "manual"
    conversation.classified_message_id = latest.id
    conversation.classified_at = now
    conversation.needs_review = False
    conversation.review_reason = None
    if category != "unsubscribe":
        return False
    _, created = suppression.add(
        db,
        ctx.workspace_id,
        latest.from_address,
        "unsubscribe",
        source="manual_classification",
        user_id=ctx.user.id,
    )
    return created


def delete_synced_mail(
    db: Session, ctx: WorkspaceContext, account: EmailAccount
) -> tuple[int, int]:
    """Remove every conversation, message, stored body and job synced from this mailbox (retention control).

    Refused while a send is unconfirmed: deleting the record would hide a message that may have gone out.
    """
    ws = ctx.workspace_id
    unresolved = db.scalar(
        select(func.count())
        .select_from(Message)
        .where(
            Message.workspace_id == ws,
            Message.email_account_id == account.id,
            Message.delivery_state.in_(("queued", "unknown")),
            Message.direction == "outbound",
        )
    )
    if unresolved:
        raise AppError(
            409,
            "unresolved_sends",
            "Some sent messages are still unconfirmed. Resolve them before deleting this mailbox's mail.",
        )
    message_count = int(
        db.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.workspace_id == ws, Message.email_account_id == account.id)
        )
        or 0
    )
    conversation_ids = list(
        db.scalars(
            select(Conversation.id).where(
                Conversation.workspace_id == ws, Conversation.email_account_id == account.id
            )
        )
    )
    if conversation_ids:
        # Drafts attached to these threads go with them (their foreign key cascades); messages, bodies and jobs too.
        db.execute(
            delete(Message).where(
                Message.workspace_id == ws, Message.email_account_id == account.id
            )
        )
        db.execute(
            delete(Conversation).where(
                Conversation.workspace_id == ws, Conversation.id.in_(conversation_ids)
            )
        )
    account.sync_cursor = None
    account.last_synced_at = None
    db.flush()
    return len(conversation_ids), message_count
