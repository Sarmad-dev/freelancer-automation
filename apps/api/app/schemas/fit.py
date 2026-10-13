"""Fit-scoring configuration and the explanation that is stored with every score (MVP Prompt 6)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain import FIT_CRITERIA
from app.schemas.fit_explanation import CriterionResult, Evidence, FitExplanation  # noqa: F401
from app.schemas.leads import CompanySize
from app.schemas.text import clean_list


def _terms(value: list[str]) -> list[str]:
    return clean_list(value, max_items=20, min_items=0, item_max=80)


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    weight: int = Field(default=1, ge=1, le=10, description="Relative importance, 1-10.")


class ServiceMatchCriterion(_Base):
    key: Literal["service_match"] = "service_match"
    keywords: list[str] = Field(
        default_factory=list,
        max_length=40,
        description="Extra words that signal a project you want, besides your profile's services.",
    )
    _k = field_validator("keywords")(_terms)


class IndustryCriterion(_Base):
    key: Literal["industry"] = "industry"
    preferred: list[str] = Field(
        default_factory=list,
        max_length=40,
        description="Empty = use the industries in your profile.",
    )
    avoid: list[str] = Field(default_factory=list, max_length=40)
    _p = field_validator("preferred", "avoid")(_terms)


class GeographyCriterion(_Base):
    key: Literal["geography"] = "geography"
    preferred: list[str] = Field(
        default_factory=list,
        max_length=40,
        description="Places, regions or words such as 'Remote'.",
    )
    _p = field_validator("preferred")(_terms)


class CompanySizeCriterion(_Base):
    key: Literal["company_size"] = "company_size"
    preferred: list[CompanySize] = Field(default_factory=list, max_length=6)


class BudgetCriterion(_Base):
    key: Literal["budget"] = "budget"


Criterion = Annotated[
    ServiceMatchCriterion
    | IndustryCriterion
    | GeographyCriterion
    | CompanySizeCriterion
    | BudgetCriterion,
    Field(discriminator="key"),
]


class FitConfigIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criteria: list[Criterion] = Field(min_length=len(FIT_CRITERIA), max_length=len(FIT_CRITERIA))
    expected_version: int | None = Field(default=None, ge=0)
    rescore: bool = Field(
        default=True, description="Recompute every active lead's score right away."
    )

    @model_validator(mode="after")
    def _complete(self) -> FitConfigIn:
        keys = [c.key for c in self.criteria]
        if sorted(keys) != sorted(FIT_CRITERIA):
            raise ValueError("Provide each criterion exactly once.")
        if not any(c.enabled for c in self.criteria):
            raise ValueError("Keep at least one criterion switched on.")
        return self


class FitConfigOut(BaseModel):
    version: int = Field(description="0 = built-in defaults, never saved.")
    criteria: list[Criterion]
    updated_at: datetime | None
    rescored: int | None = Field(default=None, description="Leads recomputed by this save.")


class RescoreResult(BaseModel):
    rescored: int
