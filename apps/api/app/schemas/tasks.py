"""Task and notification schemas (MVP Prompt 7)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.schemas.text import OptNotes, bounded
from app.services.times import zone

Priority = Literal["low", "normal", "high"]
TaskView = Literal["open", "today", "upcoming", "overdue", "undated", "done", "dismissed", "all"]
_KEY = re.compile(r"^[A-Za-z0-9._:-]{8,100}$")


def _zone(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    try:
        zone(value)
    except ValueError as exc:
        raise ValueError("Use an IANA time zone such as Europe/Berlin.") from exc
    return value.strip()


def _key(value: str | None) -> str | None:
    if value is None:
        return None
    if not _KEY.match(value):
        raise ValueError("Use 8-100 letters, digits or . _ : -")
    return value


TimeZoneName = Annotated[str | None, AfterValidator(_zone)]
Title = Annotated[str, bounded(1, 300)]


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title
    description: OptNotes = None
    priority: Priority = "normal"
    due_at: datetime | None = Field(
        default=None,
        description="With an offset/Z it is an exact instant. Without one it is wall-clock time in due_timezone.",
    )
    due_timezone: TimeZoneName = Field(
        default=None,
        description="IANA zone the time was meant in. Defaults to the profile's time zone.",
    )
    remind_at: datetime | None = Field(
        default=None, description="Same rules as due_at. Must not be after due_at."
    )
    lead_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    idempotency_key: Annotated[str | None, AfterValidator(_key)] = Field(
        default=None,
        description="Send the same key to retry safely: the same task comes back instead of a duplicate.",
    )


class TaskPatch(BaseModel):
    """PATCH semantics. Status changes use the complete / reopen / dismiss actions."""

    model_config = ConfigDict(extra="forbid")

    title: Title | None = None
    description: OptNotes = None
    priority: Priority | None = None
    due_at: datetime | None = None
    due_timezone: TimeZoneName = None
    remind_at: datetime | None = None


class TaskReschedule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    due_at: datetime
    due_timezone: TimeZoneName = None


class TaskSnooze(BaseModel):
    model_config = ConfigDict(extra="forbid")

    remind_at: datetime
    due_timezone: TimeZoneName = None


class TaskLeadRef(BaseModel):
    id: uuid.UUID
    title: str


class TaskOpportunityRef(BaseModel):
    id: uuid.UUID
    title: str


class TaskOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    status: str
    priority: str
    due_at: datetime | None
    due_timezone: str | None
    remind_at: datetime | None
    completed_at: datetime | None
    assignee_user_id: uuid.UUID | None
    lead: TaskLeadRef | None
    opportunity: TaskOpportunityRef | None
    conversation_id: uuid.UUID | None
    created_by: str
    is_sample: bool
    is_overdue: bool
    created_at: datetime
    updated_at: datetime


class TaskSummary(BaseModel):
    timezone: str
    overdue: int
    today: int
    upcoming: int
    undated: int
    done: int


class NotificationOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    body: str | None
    link: str | None
    read_at: datetime | None
    created_at: datetime


class NotificationCount(BaseModel):
    unread: int


class MarkAllResult(BaseModel):
    marked: int
