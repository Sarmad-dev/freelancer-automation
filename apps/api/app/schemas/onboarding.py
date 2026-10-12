from __future__ import annotations

from typing import Annotated, Literal
from zoneinfo import available_timezones

from pydantic import BaseModel, Field, field_validator

from app.schemas.text import bounded, clean_list, clean_public_url

STEP_IDS = (
    "role",
    "services",
    "skills",
    "target_clients",
    "industries",
    "portfolio",
    "experience",
    "tone",
    "timezone",
    "goal",
)
REQUIRED_STEPS = frozenset(
    {"role", "services", "skills", "target_clients", "tone", "timezone", "goal"}
)
STEP_LABELS = {
    "role": "Role",
    "services": "Services",
    "skills": "Skills",
    "target_clients": "Target clients",
    "industries": "Industries",
    "portfolio": "Portfolio",
    "experience": "Experience",
    "tone": "Tone",
    "timezone": "Time zone",
    "goal": "Goal",
}
TONES = ("professional", "friendly", "direct", "warm", "concise", "formal")
GOALS = (
    "find_new_clients",
    "organize_pipeline",
    "automate_follow_ups",
    "win_larger_projects",
    "other",
)

_ZONES = available_timezones()

ShortText = Annotated[str, bounded(1, 120)]


class _Step(BaseModel):
    model_config = {"extra": "forbid"}


class RoleStep(_Step):
    step: Literal["role"]
    role_title: Annotated[str, bounded(2, 120)]
    summary: Annotated[str, bounded(0, 500, multiline=True)] = ""


class ServicesStep(_Step):
    step: Literal["services"]
    services: list[str] = Field(max_length=40)

    @field_validator("services")
    @classmethod
    def _clean(cls, v: list[str]) -> list[str]:
        return clean_list(v, max_items=15, min_items=1, item_max=80)


class SkillsStep(_Step):
    step: Literal["skills"]
    skills: list[str] = Field(max_length=80)

    @field_validator("skills")
    @classmethod
    def _clean(cls, v: list[str]) -> list[str]:
        return clean_list(v, max_items=30, min_items=1, item_max=50)


class TargetClientsStep(_Step):
    step: Literal["target_clients"]
    description: Annotated[str, bounded(10, 500, multiline=True)]


class IndustriesStep(_Step):
    step: Literal["industries"]
    industries: list[str] = Field(max_length=40)

    @field_validator("industries")
    @classmethod
    def _clean(cls, v: list[str]) -> list[str]:
        return clean_list(v, max_items=15, min_items=0, item_max=60)


class PortfolioStep(_Step):
    step: Literal["portfolio"]
    urls: list[str] = Field(max_length=20)

    @field_validator("urls")
    @classmethod
    def _clean(cls, v: list[str]) -> list[str]:
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


class ExperienceStep(_Step):
    step: Literal["experience"]
    years: int = Field(ge=0, le=60)
    summary: Annotated[str, bounded(0, 1000, multiline=True)] = ""


class ToneStep(_Step):
    step: Literal["tone"]
    tone: Literal["professional", "friendly", "direct", "warm", "concise", "formal"]
    notes: Annotated[str, bounded(0, 300, multiline=True)] = ""


class TimezoneStep(_Step):
    step: Literal["timezone"]
    timezone: str = Field(max_length=64)

    @field_validator("timezone")
    @classmethod
    def _iana(cls, v: str) -> str:
        if v not in _ZONES or v.startswith(("posix/", "right/")):
            raise ValueError("Choose a valid IANA time zone, e.g. Europe/Berlin.")
        return v


class GoalStep(_Step):
    step: Literal["goal"]
    goal: Literal[
        "find_new_clients",
        "organize_pipeline",
        "automate_follow_ups",
        "win_larger_projects",
        "other",
    ]
    notes: Annotated[str, bounded(0, 300, multiline=True)] = ""


OnboardingStepInput = Annotated[
    RoleStep
    | ServicesStep
    | SkillsStep
    | TargetClientsStep
    | IndustriesStep
    | PortfolioStep
    | ExperienceStep
    | ToneStep
    | TimezoneStep
    | GoalStep,
    Field(discriminator="step"),
]


class StepStatus(BaseModel):
    id: str
    label: str
    required: bool
    completed: bool


class ProfileDraft(BaseModel):
    role_title: str | None
    summary: str | None
    services: list[str]
    skills: list[str]
    target_clients: str | None
    industries: list[str]
    portfolio_urls: list[str]
    years_experience: int | None
    experience_summary: str | None
    tone: str | None
    tone_notes: str | None
    timezone: str
    business_goal: str | None
    business_goal_notes: str | None


class OnboardingState(BaseModel):
    status: Literal["not_started", "in_progress", "skipped", "completed"]
    current_step: str
    steps: list[StepStatus]
    completed_count: int
    total_count: int
    profile: ProfileDraft
    demo_mode: bool


class DemoModeRequest(BaseModel):
    enabled: bool
