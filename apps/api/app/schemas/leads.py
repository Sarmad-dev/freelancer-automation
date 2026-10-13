"""Lead, company and contact schemas (MVP Prompt 6).

Create schemas are strict (``extra="forbid"``). Patch schemas follow PATCH semantics: omitted fields are left
alone, an explicit ``null`` (or blank text) clears an optional field.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.schemas.fit_explanation import FitExplanation
from app.schemas.text import (
    OptLine100,
    OptLine120,
    OptLine200,
    OptLine300,
    OptNotes,
    bounded,
)
from app.services.normalize import normalize_email, normalize_phone, normalize_website

LeadStatus = Literal["new", "contacted", "replied", "qualified", "nurturing", "won", "lost"]
BudgetSignal = Literal["low", "medium", "high"]
CompanySize = Literal["1", "2-10", "11-50", "51-200", "201-1000", "1000+"]
ActivityKindIn = Literal["note", "call", "meeting"]
Archived = Literal["active", "archived", "all"]


def _blank(value: str | None) -> str | None:
    return None if value is None or not value.strip() else value


def _email(value: str | None) -> str | None:
    value = _blank(value)
    return None if value is None else normalize_email(value)


def _website(value: str | None) -> str | None:
    value = _blank(value)
    return None if value is None else normalize_website(value)[0]


def _phone(value: str | None) -> str | None:
    value = _blank(value)
    return None if value is None else normalize_phone(value)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


OptEmail = Annotated[str | None, AfterValidator(_email)]
OptWebsite = Annotated[str | None, AfterValidator(_website)]
OptPhone = Annotated[str | None, AfterValidator(_phone)]
Title = Annotated[str, bounded(1, 200)]


# ---------- companies ----------
class CompanyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Title
    website: OptWebsite = None
    industry: OptLine100 = None
    size_label: CompanySize | None = None
    location: OptLine200 = None
    notes: OptNotes = None
    source: OptLine100 = None


class CompanyPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Title | None = None
    website: OptWebsite = None
    industry: OptLine100 = None
    size_label: CompanySize | None = None
    location: OptLine200 = None
    notes: OptNotes = None
    source: OptLine100 = None


class CompanyOut(BaseModel):
    id: uuid.UUID
    name: str
    domain: str | None
    website: str | None
    industry: str | None
    size_label: str | None
    location: str | None
    notes: str | None
    source: str | None
    source_retrieved_at: datetime | None
    is_sample: bool
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    lead_count: int = Field(description="Active leads linked to this company.")
    contact_count: int = Field(description="Active contacts linked to this company.")


# ---------- contacts ----------
class ContactCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: Title
    email: OptEmail = None
    role_title: OptLine120 = None
    phone: OptPhone = None
    company_id: uuid.UUID | None = None
    notes: OptNotes = None
    source: OptLine100 = None


class ContactPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: Title | None = None
    email: OptEmail = None
    role_title: OptLine120 = None
    phone: OptPhone = None
    company_id: uuid.UUID | None = None
    notes: OptNotes = None
    source: OptLine100 = None


class ContactOut(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str | None
    role_title: str | None
    phone: str | None
    company_id: uuid.UUID | None
    company_name: str | None
    notes: str | None
    source: str | None
    source_retrieved_at: datetime | None
    is_sample: bool
    archived_at: datetime | None
    do_not_contact: bool = Field(
        description="The email is on the suppression list. Nothing may be sent to it."
    )
    lead_count: int
    created_at: datetime
    updated_at: datetime


# ---------- leads ----------
class TagRef(BaseModel):
    id: uuid.UUID
    name: str
    color: str | None


class LeadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title
    # Link existing records by id, or describe new ones (matched to existing records by website/name/email first).
    company_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    company_name: OptLine200 = None
    company_website: OptWebsite = None
    contact_name: OptLine200 = None
    contact_email: OptEmail = None
    status: LeadStatus = "new"
    source: OptLine100 = None
    industry: OptLine100 = None
    location: OptLine200 = None
    notes: OptNotes = None
    budget_signal: BudgetSignal | None = None
    next_action: OptLine300 = None
    next_action_at: datetime | None = None
    tag_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)

    _aware = field_validator("next_action_at")(_aware)

    @model_validator(mode="after")
    def _either_or(self) -> LeadCreate:
        if self.company_id and (self.company_name or self.company_website):
            raise ValueError("Choose an existing company or describe a new one, not both.")
        if self.contact_id and (self.contact_name or self.contact_email):
            raise ValueError("Choose an existing contact or describe a new one, not both.")
        return self


class LeadPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title | None = None
    status: LeadStatus | None = None
    stage_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    source: OptLine100 = None
    industry: OptLine100 = None
    location: OptLine200 = None
    notes: OptNotes = None
    budget_signal: BudgetSignal | None = None
    next_action: OptLine300 = None
    next_action_at: datetime | None = None

    _aware = field_validator("next_action_at")(_aware)


class StageRef(BaseModel):
    id: uuid.UUID
    key: str
    name: str


class CompanyRef(BaseModel):
    id: uuid.UUID
    name: str


class ContactRef(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str | None


class LeadOut(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    stage: StageRef | None
    company: CompanyRef | None
    contact: ContactRef | None
    source: str | None
    source_retrieved_at: datetime | None
    industry: str | None
    location: str | None
    notes: str | None
    budget_signal: str | None
    fit_score: int | None = Field(
        description="0-100, rounded to the nearest 5. Null = not enough information."
    )
    fit_band: str | None = Field(
        description="strong | possible | weak | insufficient. Null = never scored."
    )
    fit_scored_at: datetime | None
    next_action: str | None
    next_action_at: datetime | None
    last_activity_at: datetime | None
    is_sample: bool
    archived_at: datetime | None
    tags: list[TagRef]
    do_not_contact: bool
    created_at: datetime
    updated_at: datetime


class LeadDetail(LeadOut):
    fit_explanation: FitExplanation | None = Field(
        description="Score breakdown with evidence. Null when never scored."
    )
    fit_stale: bool = Field(
        description="True when the criteria or profile changed since this score was computed."
    )


class ActivityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ActivityKindIn = "note"
    summary: Title
    body: OptNotes = None


class ActivityOut(BaseModel):
    id: uuid.UUID
    kind: str
    summary: str
    body: str | None
    details: dict[str, Any]
    actor_user_id: uuid.UUID | None
    occurred_at: datetime


class LeadTagsPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tag_ids: list[uuid.UUID] = Field(max_length=20)


class BulkTagRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    add_tag_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    remove_tag_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _something(self) -> BulkTagRequest:
        if not self.add_tag_ids and not self.remove_tag_ids:
            raise ValueError("Choose at least one tag to add or remove.")
        if set(self.add_tag_ids) & set(self.remove_tag_ids):
            raise ValueError("A tag cannot be both added and removed.")
        return self


class BulkTagResult(BaseModel):
    leads: int
    tags_added: int
    tags_removed: int
