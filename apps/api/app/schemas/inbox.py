"""The inbox: conversation list, thread detail, classification and reply suggestions (MVP Prompt 10)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.ai.schemas import ReplyCategory
from app.schemas.drafts import DeliveryState, DraftOut

ClassificationStatus = Literal["none", "pending", "classified", "failed"]
ReviewReason = Literal[
    "low_confidence",
    "fallback",
    "injection_suspected",
    "classification_failed",
    "unsubscribe_unconfirmed",
]
ClassificationSource = Literal["model", "demo_ai", "rules_fallback", "manual"]
StopReason = Literal["unsubscribe", "bounce", "complaint", "manual", "replied_stop"]


class CounterpartOut(BaseModel):
    address: str
    name: str | None = Field(description="The contact's name when the address matches one.")


class LeadRef(BaseModel):
    id: uuid.UUID
    title: str


class CompanyRef(BaseModel):
    id: uuid.UUID
    name: str


class ClassificationOut(BaseModel):
    status: ClassificationStatus
    category: ReplyCategory | None
    confidence: float | None
    explanation: str | None
    evidence: list[str] = Field(
        description="Exact quotes from the reply that support the category."
    )
    source: ClassificationSource | None
    classified_at: datetime | None
    needs_review: bool
    review_reason: ReviewReason | None
    review_text: str | None = Field(description="Why a person needs to look at it, in plain words.")


class StopOut(BaseModel):
    """Contact has been stopped: nothing will be sent to this address."""

    id: uuid.UUID = Field(
        description="The do-not-contact entry (remove it with DELETE /suppressions/{id})."
    )
    reason: StopReason
    address: str
    since: datetime
    text: str


class ConversationSummary(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    account_email: str
    is_demo: bool
    subject: str | None
    counterpart: CounterpartOut
    last_message_at: datetime | None
    last_direction: Literal["inbound", "outbound"] | None
    last_preview: str | None
    message_count: int
    unread: bool
    lead: LeadRef | None
    company: CompanyRef | None
    classification: ClassificationOut
    stop: StopOut | None
    has_draft: bool


class AttachmentOut(BaseModel):
    filename: str
    mime_type: str
    size: int | None


class BodyOut(BaseModel):
    available: bool = Field(
        description="False when only the short preview was stored for this message."
    )
    text: str
    html: str | None = Field(
        description="Sanitised HTML (allow-listed tags, no images, no styles). Show it only in a sandbox."
    )
    text_truncated: bool
    images_blocked: bool = Field(
        description="The original message had images or other remote content that was removed."
    )


class ThreadMessage(BaseModel):
    id: uuid.UUID
    direction: Literal["inbound", "outbound"]
    from_address: str
    to_addresses: list[str]
    subject: str | None
    sent_at: datetime
    attachments: list[AttachmentOut]
    delivery_state: DeliveryState
    delivery_label: str
    delivery_error_code: str | None
    is_bounce: bool
    body: BodyOut


class ConversationDetail(ConversationSummary):
    messages: list[ThreadMessage]
    draft: DraftOut | None = Field(
        description="The open reply draft for this thread, if there is one."
    )


class InboxCounts(BaseModel):
    unread: int
    needs_review: int
    open: int


class SetClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: ReplyCategory


class ClassifyQueued(BaseModel):
    queued: bool
    message: str


class SuggestReplyOut(BaseModel):
    draft: DraftOut
    regenerated: bool = Field(
        description="True when an earlier AI draft for this thread was replaced."
    )
    warnings: list[str]
    ai_label: str = Field(
        description="How the text was produced, e.g. 'Demo AI: rule-based stand-in, not a real model'."
    )
    is_demo_ai: bool


class DeleteMailOut(BaseModel):
    conversations: int
    messages: int
