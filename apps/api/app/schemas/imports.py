"""CSV import schemas (MVP Prompt 6)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.text import bounded
from app.services.csvio import MAX_CHARS

DuplicateStrategy = Literal["skip", "update"]
RowAction = Literal["create", "update", "skip_duplicate", "error"]


class ImportMapping(BaseModel):
    """Which CSV column feeds each field (the column's header text), or null to ignore the field."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=200, description="Contact's full name.")
    email: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=200, description="Contact's job title.")
    phone: str | None = Field(default=None, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    website: str | None = Field(default=None, max_length=200, description="Company website.")
    company_size: str | None = Field(default=None, max_length=200)
    industry: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=200, description="Lead title.")
    source: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=200)
    budget: str | None = Field(default=None, max_length=200, description="low, medium or high.")
    tags: str | None = Field(default=None, max_length=200, description="Separated by ; or | or ,")
    status: str | None = Field(default=None, max_length=200)
    next_action: str | None = Field(default=None, max_length=200)


class ImportPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=MAX_CHARS, description="The CSV text.")
    mapping: ImportMapping | None = Field(
        default=None, description="Omit to use the suggested mapping."
    )
    duplicate_strategy: DuplicateStrategy = "skip"


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=MAX_CHARS)
    mapping: ImportMapping
    duplicate_strategy: DuplicateStrategy = "skip"
    filename: Annotated[str, bounded(1, 200)] = "import.csv"


class ImportErrorOut(BaseModel):
    row: int = Field(description="Line number in the file (the header is line 1).")
    column: str
    message: str
    value: str
    kind: Literal["error", "skipped"]


class ImportRowPreview(BaseModel):
    row: int
    action: RowAction
    values: dict[str, str]
    issues: list[str]
    warnings: list[str]
    note: str | None


class ImportCounts(BaseModel):
    create: int
    update: int
    skip_duplicate: int
    error: int


class ImportPreview(BaseModel):
    delimiter: str
    headers: list[str]
    suggested_mapping: ImportMapping
    mapping: ImportMapping
    mapping_problem: str | None = Field(
        description="Why nothing was analysed (for example, no name, email or company column is mapped)."
    )
    total_rows: int
    counts: ImportCounts
    suppressed: int = Field(description="Rows whose email is on your do-not-contact list.")
    rows: list[ImportRowPreview] = Field(
        description="The first rows, with what will happen to each."
    )
    errors: list[ImportErrorOut]
    errors_truncated: bool


class ImportJobOut(BaseModel):
    id: uuid.UUID
    filename: str
    status: str
    duplicate_strategy: str
    total_rows: int
    created_count: int
    updated_count: int
    skipped_count: int
    error_count: int
    errors_truncated: bool
    suppressed: int | None = None
    created_at: datetime
