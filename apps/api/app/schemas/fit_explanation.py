"""The explanation stored with every fit score (MVP Prompt 6). Kept free of other schema imports so both the
lead schemas and the criteria schemas can use it."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    field: str
    value: str | None = None
    note: str | None = None


class CriterionResult(BaseModel):
    key: str
    label: str
    weight: int
    outcome: Literal["match", "partial", "miss", "unknown"]
    points: float = Field(
        description="weight x (1 match, 0.5 partial, 0 miss). Unknown counts for nothing."
    )
    reason: str
    evidence: list[Evidence]


class FitExplanation(BaseModel):
    version: int
    method: Literal["rules"]
    computed_at: datetime
    config_version: int
    profile_version: int
    score: int | None
    band: Literal["strong", "possible", "weak", "insufficient"]
    confidence: float = Field(description="Share of the total weighting that had data (0-1).")
    known_weight: int
    total_weight: int
    capped: bool = Field(
        description="Score was limited because the lead matches a client type you don't take."
    )
    summary: str
    warnings: list[str]
    criteria: list[CriterionResult]
