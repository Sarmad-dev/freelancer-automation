"""Knowledge item schemas (MVP Prompt 5)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.schemas.text import bounded, clean_source_ref

Kind = Literal["fact", "service", "case_study", "portfolio", "pricing", "other"]
Status = Literal["draft", "pending_review", "approved", "rejected"]
SourceType = Literal["manual", "upload", "extracted"]

Title = Annotated[str, bounded(1, 200)]
Content = Annotated[str, bounded(1, 4000, multiline=True)]
SourceRef = Annotated[str, AfterValidator(clean_source_ref)]


class KnowledgeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Kind = "fact"
    title: Title
    content: Content
    source_ref: SourceRef | None = None
    # Convenience for facts the freelancer wrote themselves; extracted facts always need review.
    approve_now: bool = False


class KnowledgePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Kind | None = None
    title: Title | None = None
    content: Content | None = None
    source_ref: SourceRef | None = None
    # Switching an item on or off is not a content change: no new version, approval is kept.
    is_enabled: bool | None = None
    expected_version: int | None = Field(default=None, ge=1)


class KnowledgeApprove(BaseModel):
    """Approval is bound to the exact version that was reviewed."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)


class KnowledgeImport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_label: Annotated[str, AfterValidator(clean_source_ref)]
    text: Annotated[str, bounded(1, 20000, multiline=True)]
    kind: Kind = "fact"


class KnowledgeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    title: str
    content: str
    source_type: str
    source_ref: str | None
    status: str
    version: int
    is_enabled: bool
    approved_at: datetime | None
    approved_by_user_id: uuid.UUID | None
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class KnowledgeVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    kind: str
    title: str
    content: str
    source_ref: str | None
    changed_by_user_id: uuid.UUID | None
    created_at: datetime


class KnowledgeImportResult(BaseModel):
    method: Literal["text_split"] = "text_split"
    created: int
    skipped_duplicates: int
    truncated: bool
    items: list[KnowledgeOut]
