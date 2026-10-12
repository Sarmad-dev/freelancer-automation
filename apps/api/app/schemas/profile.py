"""Freelancer profile schemas (MVP Prompt 5)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.text import bounded, clean_list, clean_public_url

Tone = Literal["professional", "friendly", "direct", "warm", "concise", "formal"]
Goal = Literal[
    "find_new_clients", "organize_pipeline", "automate_follow_ups", "win_larger_projects", "other"
]


def _clean(value: list[str] | None, max_items: int, item_max: int) -> list[str] | None:
    if value is None:
        return None
    return clean_list(value, max_items=max_items, min_items=0, item_max=item_max)


class ProfilePatch(BaseModel):
    """PATCH semantics: omitted fields are untouched; ``null`` or an empty value clears the field."""

    model_config = ConfigDict(extra="forbid")

    role_title: Annotated[str, bounded(0, 120)] | None = None
    summary: Annotated[str, bounded(0, 500, multiline=True)] | None = None
    services: list[str] | None = Field(default=None, max_length=60)
    skills: list[str] | None = Field(default=None, max_length=100)
    industries: list[str] | None = Field(default=None, max_length=60)
    differentiators: list[str] | None = Field(default=None, max_length=40)
    excluded_customers: list[str] | None = Field(default=None, max_length=60)
    target_clients: Annotated[str, bounded(0, 500, multiline=True)] | None = None
    portfolio_urls: list[str] | None = Field(default=None, max_length=30)
    years_experience: int | None = Field(default=None, ge=0, le=60)
    experience_summary: Annotated[str, bounded(0, 1000, multiline=True)] | None = None
    pricing_guidance: Annotated[str, bounded(0, 1000, multiline=True)] | None = None
    preferred_cta: Annotated[str, bounded(0, 200)] | None = None
    tone: Tone | None = None
    tone_notes: Annotated[str, bounded(0, 300, multiline=True)] | None = None
    business_goal: Goal | None = None
    business_goal_notes: Annotated[str, bounded(0, 300, multiline=True)] | None = None
    # Optimistic concurrency: the profile version the client edited. A mismatch is a 409.
    expected_version: int | None = Field(default=None, ge=1)

    @field_validator("services")
    @classmethod
    def _services(cls, v: list[str] | None) -> list[str] | None:
        return _clean(v, 15, 80)

    @field_validator("skills")
    @classmethod
    def _skills(cls, v: list[str] | None) -> list[str] | None:
        return _clean(v, 30, 50)

    @field_validator("industries")
    @classmethod
    def _industries(cls, v: list[str] | None) -> list[str] | None:
        return _clean(v, 15, 60)

    @field_validator("differentiators")
    @classmethod
    def _differentiators(cls, v: list[str] | None) -> list[str] | None:
        return _clean(v, 10, 200)

    @field_validator("excluded_customers")
    @classmethod
    def _excluded(cls, v: list[str] | None) -> list[str] | None:
        return _clean(v, 15, 100)

    @field_validator("portfolio_urls")
    @classmethod
    def _urls(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        out: list[str] = []
        for raw in v:
            if not raw.strip():
                continue
            url = clean_public_url(raw)
            if url not in out:
                out.append(url)
        if len(out) > 10:
            raise ValueError("Add at most 10 links.")
        return out


class MissingField(BaseModel):
    field: str
    label: str
    importance: Literal["needed", "recommended"]


class Completeness(BaseModel):
    filled: int
    total: int
    missing: list[MissingField]


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    role_title: str | None
    summary: str | None
    services: list[str]
    skills: list[str]
    industries: list[str]
    differentiators: list[str]
    excluded_customers: list[str]
    target_clients: str | None
    portfolio_urls: list[str]
    years_experience: int | None
    experience_summary: str | None
    pricing_guidance: str | None
    preferred_cta: str | None
    tone: str | None
    tone_notes: str | None
    business_goal: str | None
    business_goal_notes: str | None
    version: int
    updated_at: datetime
    timezone: str
    completeness: Completeness


class SummarySection(BaseModel):
    title: str
    items: list[str]


class ProfileSummary(BaseModel):
    """Plain-text, public-facing professional summary composed ONLY from fields the freelancer entered."""

    headline: str | None
    intro: str | None
    sections: list[SummarySection]
    links: list[str]
    omitted: list[MissingField]
    profile_version: int
    private_fields_excluded: list[str]
