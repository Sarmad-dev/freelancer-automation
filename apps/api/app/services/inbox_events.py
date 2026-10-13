"""What happens when a message is first stored: its body is kept (cleaned), bounces stop contact, replies are noticed and
inbound mail is queued for classification.

Everything here is idempotent (it runs only for newly inserted messages, and each effect has its own uniqueness guard) and
nothing here sends mail or changes anything a person decided.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.config import get_settings
from app.db.models import Membership
from app.db.models_crm import Contact
from app.db.models_email import Conversation, EmailAccount, Message, MessageBody
from app.db.models_workflow import Notification
from app.mailbox import signals
from app.mailbox.sanitize import SANITIZER_VERSION, prepare_body
from app.mailbox.types import RemoteMessage
from app.services import email_jobs, suppression
from app.workflows import events as workflow_events


def store_body(db: Session, workspace_id: uuid.UUID, message: Message, rm: RemoteMessage) -> bool:
    """Keep the cleaned body of ``message``. True when something was created or changed."""
    if rm.body_text is None and rm.body_html is None:
        return False
    prepared = prepare_body(rm.body_text, rm.body_html)
    existing = db.scalar(select(MessageBody).where(MessageBody.message_id == message.id))
    if existing is None:
        db.add(
            MessageBody(
                workspace_id=workspace_id,
                message_id=message.id,
                body_text=prepared.text,
                body_html=prepared.html,
                text_truncated=prepared.text_truncated,
                images_blocked=prepared.images_blocked,
                sanitizer_version=SANITIZER_VERSION if prepared.html else None,
            )
        )
        return True
    changed = False
    for attr, value in (
        ("body_text", prepared.text),
        ("body_html", prepared.html),
        ("text_truncated", prepared.text_truncated),
        ("images_blocked", prepared.images_blocked),
        ("sanitizer_version", SANITIZER_VERSION if prepared.html else None),
    ):
        if getattr(existing, attr) != value:
            setattr(existing, attr, value)
            changed = True
    return changed


def _owner_ids(db: Session, workspace_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        db.scalars(
            select(Membership.user_id).where(
                Membership.workspace_id == workspace_id, Membership.role == "owner"
            )
        )
    )


def is_reply(db: Session, conversation: Conversation, message: Message) -> bool:
    """An inbound message in a thread where we had already written."""
    return (
        db.scalar(
            select(Message.id)
            .where(
                Message.conversation_id == conversation.id,
                Message.direction == "outbound",
                Message.sent_at <= message.sent_at,
            )
            .limit(1)
        )
        is not None
    )


def _notify_reply(
    db: Session, workspace_id: uuid.UUID, conversation: Conversation, message: Message
) -> None:
    sender = message.from_address
    if conversation.contact_id is not None:
        contact = db.get(Contact, conversation.contact_id)
        if contact is not None and contact.workspace_id == workspace_id:
            sender = contact.full_name
    for user_id in _owner_ids(db, workspace_id):
        note = Notification(
            workspace_id=workspace_id,
            user_id=user_id,
            kind="reply_received",
            title=f"New reply from {sender}"[:200],
            body=(message.subject or "")[:500] or None,
            link=f"/inbox?c={conversation.id}",
            dedupe_key=f"reply:{message.id}"[:120],
        )
        try:
            with db.begin_nested():
                db.add(note)
                db.flush()
        except IntegrityError:
            continue  # already notified about this message


def handle_bounce(
    db: Session, workspace_id: uuid.UUID, conversation: Conversation, message: Message
) -> int:
    """A delivery failure: stop contacting whoever we last wrote to in this thread. Returns how many addresses were added."""
    last_out = db.scalar(
        select(Message)
        .where(
            Message.conversation_id == conversation.id,
            Message.direction == "outbound",
            Message.sent_at <= message.sent_at,
        )
        .order_by(Message.sent_at.desc(), Message.id)
        .limit(1)
    )
    if last_out is None:
        return 0
    added = 0
    for address in last_out.to_addresses or []:
        _, created = suppression.add(
            db, workspace_id, address, "bounce", source="bounce_detected", note=None
        )
        added += int(created)
    if added:
        audit.record(
            db,
            "email.bounce_detected",
            workspace_id=workspace_id,
            target_type="conversation",
            target_id=str(conversation.id),
            details={"count": added},
        )
    return added


def on_new_message(
    db: Session,
    workspace_id: uuid.UUID,
    account: EmailAccount,
    conversation: Conversation,
    message: Message,
    rm: RemoteMessage,
    now: datetime,
) -> None:
    """Called once for every message that was newly stored."""
    if rm.direction != "inbound":
        return
    if signals.is_bounce(rm.from_address, rm.subject):
        message.is_bounce = True
        handle_bounce(db, workspace_id, conversation, message)
        return
    email_jobs.enqueue(db, workspace_id, conversation.id, message.id, now=now)
    if is_reply(db, conversation, message):
        _notify_reply(db, workspace_id, conversation, message)
        # Workflows listening for replies are queued here and run by the worker (never inside this request).
        workflow_events.emit(
            db,
            get_settings(),
            workspace_id,
            "reply_received",
            "conversation",
            conversation.id,
            str(message.id),
            now,
        )
