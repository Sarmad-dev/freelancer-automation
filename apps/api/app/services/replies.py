"""Suggesting a reply to an incoming message.

The suggestion is an ordinary draft (``author="ai"``) that a person edits, approves and sends. Nothing here sends. It is built
from approved facts only (``build_context``), says which facts it used, and is refused when there is not enough approved
information, when the contact has been stopped, or when the thread has nothing to answer.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import inputs as ai_inputs
from app.ai.schemas import DraftOutreachInput, ReplyContext
from app.ai.service import AiService
from app.db.models_email import Conversation, Draft, EmailAccount, Message, MessageBody
from app.deps import WorkspaceContext
from app.errors import AppError
from app.services import drafts as draft_service
from app.services import email_jobs, suppression
from app.services.ai_context import build_context
from app.services.inbox import OPEN_DRAFT_STATUSES

_FAILURES = {
    "ai_disabled": (
        409,
        "AI is not set up for this installation, so no reply can be suggested. You can still write one yourself.",
    ),
    "rate_limited": (429, "Too many AI requests right now. Try again in a minute."),
    "timeout": (503, "The AI provider took too long. Try again."),
    "unavailable": (503, "The AI provider is not responding. Try again shortly."),
}


def _text_of(db: Session, message: Message) -> str:
    stored = db.scalar(select(MessageBody.body_text).where(MessageBody.message_id == message.id))
    return (
        stored if stored and stored.strip() else message.snippet or message.subject or ""
    ).strip()


def _subject(subject: str | None) -> str:
    base = (subject or "").strip()
    if base.lower().startswith("re:"):
        return base[:200]
    return f"Re: {base}"[:200] if base else "Re:"


def suggest_reply(
    db: Session, ctx: WorkspaceContext, conversation: Conversation, ai: AiService, now: datetime
) -> tuple[Draft, bool, list[str], str, bool]:
    """Create (or replace) the AI draft for ``conversation``. Returns ``(draft, regenerated, warnings, label, is_demo)``."""
    latest = email_jobs.latest_inbound(db, conversation.id)
    if latest is None:
        raise AppError(
            409, "nothing_to_reply_to", "This thread has no incoming message to reply to."
        )
    account = db.get(EmailAccount, conversation.email_account_id)
    if account is None or account.workspace_id != ctx.workspace_id:
        raise AppError(404, "email_account_not_found", "Mailbox not found.")
    recipient = latest.from_address
    if suppression.find(db, ctx.workspace_id, recipient) is not None:
        raise AppError(
            409,
            "contact_stopped",
            "This person asked not to be contacted (or the address bounced), so no reply is suggested.",
        )
    lead_part = None
    first_name = None
    if conversation.lead_id is not None:
        lead_part, first_name = ai_inputs.draft_target(db, ctx, conversation.lead_id)
    if lead_part is None:
        from app.ai.schemas import DraftLead

        lead_part = DraftLead(title=conversation.subject)
    previous = db.scalar(
        select(Message)
        .where(
            Message.conversation_id == conversation.id,
            Message.direction == "outbound",
            Message.sent_at <= latest.sent_at,
        )
        .order_by(Message.sent_at.desc(), Message.id)
        .limit(1)
    )
    outcome = ai.draft_outreach(
        DraftOutreachInput(
            lead=lead_part,
            recipient_first_name=first_name,
            goal="Answer their message helpfully and keep the conversation moving with one clear, low-pressure next step.",
            reply_to=ReplyContext(
                subject=latest.subject,
                message=_text_of(db, latest)[:8_000] or "(empty message)",
                classification=conversation.classification,
                previous_message=_text_of(db, previous)[:4_000] if previous else None,
            ),
        ),
        build_context(db, ctx),
    )
    if not outcome.ok or outcome.data is None:
        failure = outcome.failure
        code = failure.code if failure else "unknown"
        if code == "insufficient_context":
            missing = (
                ", ".join(failure.missing) if failure and failure.missing else "approved facts"
            )
            raise AppError(
                422,
                "insufficient_context",
                f"There isn't enough approved information to draft this without guessing. Add: {missing} in the AI Workspace.",
            )
        status, message = _FAILURES.get(
            code,
            (
                502,
                "The reply could not be written safely, so nothing was drafted. Try again, or write it yourself.",
            ),
        )
        raise AppError(status, "ai_unavailable" if status == 409 else code, message)
    data = outcome.data
    draft = db.scalar(
        select(Draft)
        .where(
            Draft.workspace_id == ctx.workspace_id,
            Draft.conversation_id == conversation.id,
            Draft.author == "ai",
            Draft.status.in_(OPEN_DRAFT_STATUSES),
        )
        .order_by(Draft.updated_at.desc())
        .limit(1)
    )
    regenerated = draft is not None
    if draft is not None and draft_service.send_locked(draft):
        draft, regenerated = None, False
    subject = _subject(conversation.subject)
    if draft is None:
        draft = Draft(
            workspace_id=ctx.workspace_id,
            lead_id=conversation.lead_id,
            conversation_id=conversation.id,
            email_account_id=account.id,
            to_address=recipient,
            subject=subject,
            body_text=data.body,
            status="draft",
            author="ai",
        )
        db.add(draft)
    else:
        draft.to_address = recipient
        draft.subject = subject
        draft.body_text = data.body
        draft.version += 1
        draft.status = "draft"  # a new text needs a fresh approval
        draft.approved_content_hash = None
        draft.approved_at = None
        draft.approved_by_user_id = None
    draft.facts_used = [str(i) for i in data.facts_used]
    draft.content_hash = draft_service.content_hash(
        draft.to_address, draft.subject, draft.body_text
    )
    db.flush()
    warnings = list(outcome.warnings) + [f"review: {n}" for n in data.needs_review]
    return draft, regenerated, warnings, outcome.meta.label, outcome.meta.is_mock
