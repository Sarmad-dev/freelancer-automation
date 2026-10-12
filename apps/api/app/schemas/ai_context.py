from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel

from app.schemas.profile import MissingField


class ContextFact(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    content: str
    version: int
    source_type: str


class AiContext(BaseModel):
    """Everything a model is allowed to know about the freelancer, and nothing else.

    Built from the freelancer's own profile fields plus knowledge items that are BOTH approved and enabled.
    Draft, pending-review, rejected and disabled items are excluded; only their counts are reported.
    """

    profile: dict[str, Any]
    facts: list[ContextFact]
    missing: list[MissingField]
    excluded_counts: dict[str, int]
    truncated: bool
    policy: list[str]
    # Stable fingerprint of profile + facts; store it with a generated draft to know what informed it.
    context_hash: str
