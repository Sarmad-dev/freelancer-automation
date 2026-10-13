"""The node catalogue: what each node type is, its settings, its output ports and what it needs from earlier steps.

*Facts* are the typed values a run carries from step to step: ``lead``, ``conversation``, ``draft``,
``approved_draft`` (a draft a person approved *in this run*), ``fit``, ``classification``, ``task``, ``opportunity``.
A node declares the facts it requires; the validator proves every path to it provides them. That is what the
"typed ports" of the playbook mean here: an edge can only carry what the node before it actually produced.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app import domain

# ----------------------------------------------------------------------------- vocabulary

FACT_LEAD = "lead"
FACT_CONVERSATION = "conversation"
FACT_DRAFT = "draft"
FACT_APPROVED_DRAFT = "approved_draft"
FACT_FIT = "fit"
FACT_CLASSIFICATION = "classification"
FACT_TASK = "task"
FACT_OPPORTUNITY = "opportunity"

FACT_LABELS = {
    FACT_LEAD: "a lead",
    FACT_CONVERSATION: "a conversation",
    FACT_DRAFT: "a draft",
    FACT_APPROVED_DRAFT: "a draft that a person approved in this workflow",
    FACT_FIT: "a fit assessment",
    FACT_CLASSIFICATION: "a reply classification",
}

TRIGGER_EVENTS = ("manual", "lead_created", "reply_received", "follow_up_due")
SUBJECT_TYPES = ("lead", "conversation")
EVENT_SUBJECT: dict[str, str] = {
    "lead_created": "lead",
    "reply_received": "conversation",
    "follow_up_due": "lead",
}

MAX_DELAY_SECONDS = 30 * 24 * 3600
DELAY_UNITS = {"minutes": 60, "hours": 3600, "days": 86400}

FIT_RATINGS = ("strong", "possible", "weak", "unknown")

# Placeholders allowed in task titles and notifications, and the fact each needs. A fixed list on purpose: message
# text, addresses and other untrusted values can never be pulled into a template.
PLACEHOLDERS: dict[str, str] = {
    "lead_title": FACT_LEAD,
    "company_name": FACT_LEAD,
    "category": FACT_CLASSIFICATION,
    "fit_rating": FACT_FIT,
}
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def placeholders_in(text: str | None) -> list[str]:
    return _PLACEHOLDER.findall(text or "")


def render(template: str, values: dict[str, str]) -> str:
    """Fill ``{name}`` placeholders. Anything not in ``values`` becomes an empty string (never an error at run time)."""
    return _PLACEHOLDER.sub(lambda m: values.get(m.group(1), ""), template)


# ----------------------------------------------------------------------------- conditions


@dataclass(frozen=True)
class ConditionField:
    kind: Literal["enum", "string", "number", "bool"]
    requires: str
    label: str
    values: tuple[str, ...] = ()


CONDITION_FIELDS: dict[str, ConditionField] = {
    "fit.rating": ConditionField("enum", FACT_FIT, "AI fit rating", FIT_RATINGS),
    "classification.category": ConditionField(
        "enum", FACT_CLASSIFICATION, "Reply category", tuple(domain.REPLY_CATEGORIES)
    ),
    "classification.needs_review": ConditionField(
        "bool", FACT_CLASSIFICATION, "Classification needs review"
    ),
    "lead.status": ConditionField("string", FACT_LEAD, "Lead stage"),
    "lead.score": ConditionField("number", FACT_LEAD, "Lead fit score (0-100)"),
    "lead.has_contact_email": ConditionField("bool", FACT_LEAD, "Lead has a contact email"),
    "contact.suppressed": ConditionField(
        "bool", FACT_LEAD, "Contact is on the do-not-contact list"
    ),
}
CONDITION_OPS: dict[str, tuple[str, ...]] = {
    "enum": ("eq", "ne", "in", "not_in"),
    "string": ("eq", "ne", "in", "not_in"),
    "number": ("eq", "ne", "gte", "lte"),
    "bool": ("is_true", "is_false"),
}


# ----------------------------------------------------------------------------- settings per node type


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Retryable(_Config):
    max_attempts: int | None = Field(
        default=None, ge=1, le=5, description="Attempts before the run fails (default per node type)."
    )
    timeout_seconds: int | None = Field(
        default=None, ge=5, le=300, description="Longest this step may take (default per node type)."
    )


class TriggerConfig(_Config):
    event: Literal["manual", "lead_created", "reply_received", "follow_up_due"]
    subject: Literal["lead", "conversation"] | None = Field(
        default=None, description="What a manual run is about. Event triggers fix it."
    )

    @model_validator(mode="after")
    def _subject(self) -> TriggerConfig:
        if self.event != "manual" and self.subject is not None:
            raise ValueError("subject is only set for a manual trigger")
        return self


class ConditionConfig(_Config):
    field: str = Field(min_length=1, max_length=60)
    op: str = Field(min_length=1, max_length=20)
    value: str | int | float | list[str] | None = None

    @model_validator(mode="after")
    def _check(self) -> ConditionConfig:
        spec = CONDITION_FIELDS.get(self.field)
        if spec is None:
            raise ValueError("field is not one of: " + ", ".join(CONDITION_FIELDS))
        if self.op not in CONDITION_OPS[spec.kind]:
            raise ValueError(
                f"op must be one of {', '.join(CONDITION_OPS[spec.kind])} for {self.field}"
            )
        if spec.kind == "bool":
            if self.value is not None:
                raise ValueError("this check takes no value")
            return self
        if self.value is None:
            raise ValueError("value is required")
        many = self.op in ("in", "not_in")
        if many:
            if not isinstance(self.value, list) or not 1 <= len(self.value) <= 10:
                raise ValueError("value must be a list of 1 to 10 items")
            items: list[Any] = list(self.value)
        else:
            if isinstance(self.value, list):
                raise ValueError("value must be a single value")
            items = [self.value]
        if spec.kind == "number":
            if any(isinstance(i, bool) or not isinstance(i, (int, float)) for i in items):
                raise ValueError("value must be a number")
        else:
            if any(not isinstance(i, str) or not 1 <= len(i) <= 60 for i in items):
                raise ValueError("value must be text")
            if spec.kind == "enum" and any(i not in spec.values for i in items):
                raise ValueError("value must be one of: " + ", ".join(spec.values))
        return self


class AssessFitConfig(_Retryable):
    pass


class ClassifyReplyConfig(_Retryable):
    pass


class AiDraftConfig(_Retryable):
    mode: Literal["outreach", "reply"] = "outreach"
    goal: str | None = Field(
        default=None, max_length=300, description="What the message should achieve (you write this, not the AI)."
    )


class UpsertRecordConfig(_Retryable):
    action: Literal["update_lead", "create_opportunity"]
    stage_key: str | None = Field(
        default=None, min_length=1, max_length=40, description="A pipeline stage key, e.g. contacted."
    )
    title: str | None = Field(default=None, max_length=200, description="Opportunity title (defaults to the lead's).")

    @model_validator(mode="after")
    def _check(self) -> UpsertRecordConfig:
        if self.action == "update_lead" and self.stage_key is None:
            raise ValueError("stage_key is required to update a lead")
        if self.action == "update_lead" and self.title is not None:
            raise ValueError("title is only used when creating an opportunity")
        return self


class CreateTaskConfig(_Retryable):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1_000)
    priority: Literal["low", "normal", "high"] = "normal"
    due_in_days: int | None = Field(default=None, ge=0, le=365)


class ApprovalGateConfig(_Config):
    message: str = Field(default="Approve this step to continue.", min_length=1, max_length=300)
    expires_hours: int = Field(default=72, ge=1, le=720)


class SendEmailConfig(_Retryable):
    pass


class DelayConfig(_Config):
    amount: int = Field(ge=1, le=10_000)
    unit: Literal["minutes", "hours", "days"] = "hours"

    @model_validator(mode="after")
    def _limit(self) -> DelayConfig:
        if self.amount * DELAY_UNITS[self.unit] > MAX_DELAY_SECONDS:
            raise ValueError("a delay can be at most 30 days")
        return self

    @property
    def seconds(self) -> int:
        return self.amount * DELAY_UNITS[self.unit]


class NotifyConfig(_Retryable):
    title: str = Field(min_length=1, max_length=120)
    message: str | None = Field(default=None, max_length=300)


class EndConfig(_Config):
    outcome: Literal["success", "failure"] = "success"
    reason: str | None = Field(default=None, max_length=120)


# ----------------------------------------------------------------------------- specs


def _none(_: Any) -> frozenset[str]:
    return frozenset()


@dataclass(frozen=True)
class NodeSpec:
    type: str
    label: str
    description: str
    model: type[BaseModel]
    ports: tuple[str, ...] = ("next",)
    # True when the step changes records or leaves the system. In test mode these are simulated.
    side_effect: bool = False
    attempts: int = 1
    timeout_seconds: int = 30
    needs: Callable[[Any], frozenset[str]] = _none
    gives: Callable[[Any], frozenset[str]] = _none


def _trigger_gives(cfg: TriggerConfig) -> frozenset[str]:
    if cfg.event == "manual":
        return frozenset({cfg.subject or "lead"})
    return frozenset({EVENT_SUBJECT[cfg.event]})


def _template_needs(*texts: str | None) -> frozenset[str]:
    out: set[str] = set()
    for text in texts:
        for name in placeholders_in(text):
            fact = PLACEHOLDERS.get(name)
            if fact:
                out.add(fact)
    return frozenset(out)


def _draft_needs(cfg: AiDraftConfig) -> frozenset[str]:
    return frozenset({FACT_CONVERSATION if cfg.mode == "reply" else FACT_LEAD})


def _upsert_gives(cfg: UpsertRecordConfig) -> frozenset[str]:
    return frozenset({FACT_OPPORTUNITY}) if cfg.action == "create_opportunity" else frozenset()


NODE_SPECS: dict[str, NodeSpec] = {
    s.type: s
    for s in (
        NodeSpec(
            "trigger",
            "Trigger",
            "Starts the workflow: by hand, or when a lead is created, a reply arrives or a follow-up is due.",
            TriggerConfig,
            gives=_trigger_gives,
        ),
        NodeSpec(
            "condition",
            "Condition",
            "Chooses a path by checking one value. Both the true and the false path must lead somewhere.",
            ConditionConfig,
            ports=("true", "false"),
            needs=lambda c: frozenset({CONDITION_FIELDS[c.field].requires}),
        ),
        NodeSpec(
            "ai_assess_fit",
            "AI lead-fit assessment",
            "Asks the AI whether the lead fits your profile. A suggestion only: nothing is changed.",
            AssessFitConfig,
            attempts=3,
            timeout_seconds=60,
            needs=lambda c: frozenset({FACT_LEAD}),
            gives=lambda c: frozenset({FACT_FIT}),
        ),
        NodeSpec(
            "ai_classify_reply",
            "AI reply classification",
            "Classifies the latest reply in a conversation (interested, question, unsubscribe...).",
            ClassifyReplyConfig,
            attempts=3,
            timeout_seconds=60,
            needs=lambda c: frozenset({FACT_CONVERSATION}),
            gives=lambda c: frozenset({FACT_CLASSIFICATION}),
        ),
        NodeSpec(
            "ai_draft",
            "AI draft",
            "Writes a draft email from your approved facts. A draft is never sent by this step.",
            AiDraftConfig,
            attempts=3,
            timeout_seconds=60,
            needs=_draft_needs,
            gives=lambda c: frozenset({FACT_DRAFT}),
        ),
        NodeSpec(
            "upsert_record",
            "Update lead or create opportunity",
            "Moves a lead to a stage, or opens an opportunity for it. Simulated in test mode.",
            UpsertRecordConfig,
            side_effect=True,
            attempts=2,
            needs=lambda c: frozenset({FACT_LEAD}),
            gives=_upsert_gives,
        ),
        NodeSpec(
            "create_task",
            "Create task",
            "Adds a task (and reminder) for you. Placeholders: " + ", ".join("{" + p + "}" for p in PLACEHOLDERS) + ".",
            CreateTaskConfig,
            attempts=2,
            needs=lambda c: _template_needs(c.title, c.description),
            gives=lambda c: frozenset({FACT_TASK}),
        ),
        NodeSpec(
            "approval_gate",
            "Approval gate",
            "Pauses the run until you approve or reject. Both outcomes must lead somewhere.",
            ApprovalGateConfig,
            ports=("approved", "rejected"),
        ),
        NodeSpec(
            "send_email",
            "Send approved email",
            "Sends the draft you approved at an earlier approval gate, through the normal guarded send. Simulated in test mode.",
            SendEmailConfig,
            side_effect=True,
            attempts=3,
            timeout_seconds=60,
            needs=lambda c: frozenset({FACT_DRAFT, FACT_APPROVED_DRAFT}),
        ),
        NodeSpec(
            "delay",
            "Delay",
            "Waits (up to 30 days) without holding anything open; the run resumes by itself.",
            DelayConfig,
        ),
        NodeSpec(
            "notify",
            "Notify me",
            "Sends you an in-app notification. Placeholders: " + ", ".join("{" + p + "}" for p in PLACEHOLDERS) + ".",
            NotifyConfig,
            attempts=2,
            needs=lambda c: _template_needs(c.title, c.message),
        ),
        NodeSpec(
            "end",
            "End",
            "Finishes the run as a success or a failure.",
            EndConfig,
            ports=(),
        ),
    )
}

NODE_TYPES = tuple(NODE_SPECS)


def default_attempts(node_type: str, cfg: Any) -> int:
    spec = NODE_SPECS[node_type]
    chosen = getattr(cfg, "max_attempts", None)
    return int(chosen or spec.attempts)


def default_timeout(node_type: str, cfg: Any) -> int:
    spec = NODE_SPECS[node_type]
    chosen = getattr(cfg, "timeout_seconds", None)
    return int(chosen or spec.timeout_seconds)
