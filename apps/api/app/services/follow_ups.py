"""The gate every AUTOMATED follow-up must pass (used by workflows and sequences from MVP Prompt 11 on).

A follow-up must stop when the person has replied, has asked not to be contacted, or the address bounced. Manual,
approved sends have their own server-side suppression check (``drafts.send_draft``); this gate is for anything that would
act without a person pressing "send".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models_email import Conversation, Message
from app.services import suppression


@dataclass(frozen=True)
class Gate:
    allowed: bool
    reason: str | None = None  # "suppressed" | "replied"


def _has_reply(db: Session, workspace_id: uuid.UUID, conversation_ids: list[uuid.UUID]) -> bool:
    if not conversation_ids:
        return False
    first_out = (
        select(Message.conversation_id, func.min(Message.sent_at).label("first_out"))
        .where(
            Message.workspace_id == workspace_id,
            Message.conversation_id.in_(conversation_ids),
            Message.direction == "outbound",
        )
        .group_by(Message.conversation_id)
        .subquery()
    )
    reply = db.scalar(
        select(Message.id)
        .join(first_out, first_out.c.conversation_id == Message.conversation_id)
        .where(
            Message.workspace_id == workspace_id,
            Message.direction == "inbound",
            Message.is_bounce.is_(False),
            Message.sent_at > first_out.c.first_out,
        )
        .limit(1)
    )
    return reply is not None


def check(
    db: Session,
    workspace_id: uuid.UUID,
    *,
    address: str | None = None,
    lead_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
) -> Gate:
    """May an automated follow-up go to this person/lead/thread? Any one reason to stop is enough."""
    if address is not None and suppression.find(db, workspace_id, address) is not None:
        return Gate(False, "suppressed")
    conversation_ids: list[uuid.UUID] = []
    if conversation_id is not None:
        conversation_ids.append(conversation_id)
    if lead_id is not None:
        conversation_ids += list(
            db.scalars(
                select(Conversation.id).where(
                    Conversation.workspace_id == workspace_id, Conversation.lead_id == lead_id
                )
            )
        )
    if _has_reply(db, workspace_id, conversation_ids):
        return Gate(False, "replied")
    return Gate(True)
