"""Drafts, approval and sending (MVP Prompt 9)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.text import bounded

Subject = Annotated[str, bounded(0, 200)]
Body = Annotated[str, bounded(0, 20_000, multiline=True)]
DeliveryState = Literal["demo", "queued", "sent", "failed", "unknown"]


class DraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    email_account_id: uuid.UUID | None = None
    to_address: str | None = Field(default=None, max_length=254)
    subject: Subject = ""
    body_text: Body = ""


class DraftPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email_account_id: uuid.UUID | None = None
    to_address: str | None = Field(default=None, max_length=254)
    subject: Subject | None = None
    body_text: Body | None = None


class MessageStateOut(BaseModel):
    id: uuid.UUID
    delivery_state: DeliveryState
    delivery_label: str
    delivery_error_code: str | None
    is_demo: bool
    conversation_id: uuid.UUID
    sent_at: datetime


class DraftFactOut(BaseModel):
    """An approved profile fact an AI draft was written from."""

    id: uuid.UUID
    title: str
    kind: str
    still_approved: bool = Field(
        description="False when the fact was edited, disabled or deleted after the draft was written."
    )


class DraftOut(BaseModel):
    id: uuid.UUID
    lead_id: uuid.UUID | None
    conversation_id: uuid.UUID | None
    email_account_id: uuid.UUID | None
    to_address: str | None
    subject: str
    body_text: str
    status: Literal["draft", "pending_approval", "approved", "rejected", "sent", "discarded"]
    author: Literal["user", "ai"]
    version: int
    facts_used: list[str]
    facts: list[DraftFactOut]
    approved_at: datetime | None
    approval_is_current: bool = Field(
        description="True only while the approved text is exactly the text that would be sent."
    )
    sent_at: datetime | None
    send_locked: bool = Field(
        description="A send has started or finished; the draft can no longer be edited."
    )
    message: MessageStateOut | None
    created_at: datetime
    updated_at: datetime


class SendIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(
        min_length=8,
        max_length=100,
        pattern=r"^[A-Za-z0-9._:\-]+$",
        description="Create one per send intent (when the dialog opens) and reuse it for retries.",
    )


class SendOut(BaseModel):
    draft: DraftOut
    replayed: bool = Field(
        description="True when this key had already been used: nothing new was sent."
    )


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["sent", "not_sent"]
