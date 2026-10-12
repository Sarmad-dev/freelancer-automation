"""Request/response schemas for CRM resources. Separate from ORM models on purpose: the API shape is a
contract, the table layout is an implementation detail."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.text import bounded

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")

TagName = Annotated[str, bounded(1, 50)]


def _check_color(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if not _HEX_COLOR.fullmatch(value):
        raise ValueError("Use a hex colour like #A8E66B.")
    return value.upper()


class TagCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: TagName
    color: str | None = None

    _color = field_validator("color")(_check_color)


class TagUpdate(BaseModel):
    """PATCH semantics: omitted fields are left unchanged."""

    model_config = ConfigDict(extra="forbid")

    name: TagName | None = None
    color: str | None = None

    _color = field_validator("color")(_check_color)


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    color: str | None
    created_at: datetime
    updated_at: datetime


class PipelineStageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    name: str
    position: int = Field(description="0-based display order.")
    is_won: bool
    is_lost: bool
