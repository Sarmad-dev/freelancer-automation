"""Typed requests and responses for the six AI tasks, plus the envelope every call returns.

Inputs hold only what a task needs (no email addresses, no phone numbers, no other tenants' data). Outputs are
validated strictly: unknown keys, wrong types, out-of-range numbers and over-long text are rejected rather than
repaired, because a repaired answer is a guess.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Task = Literal[
    "classify_reply",
    "assess_lead_fit",
    "extract_profile_facts",
    "draft_outreach",
    "summarize_conversation",
    "recommend_next_action",
]
TASKS: tuple[str, ...] = (
    "classify_reply",
    "assess_lead_fit",
    "extract_profile_facts",
    "draft_outreach",
    "summarize_conversation",
    "recommend_next_action",
)

ReplyCategory = Literal[
    "interested",
    "question",
    "objection",
    "not_now",
    "referral",
    "out_of_office",
    "unsubscribe",
    "irrelevant",
]
REPLY_CATEGORIES: tuple[str, ...] = (
    "interested",
    "question",
    "objection",
    "not_now",
    "referral",
    "out_of_office",
    "unsubscribe",
    "irrelevant",
)

Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- classify_reply


class ClassifyReplyInput(_Strict):
    subject: str | None = Field(default=None, max_length=500)
    body: str = Field(min_length=1, max_length=20_000, description="Untrusted email text.")
    previous_outbound: str | None = Field(
        default=None, max_length=4_000, description="The message being replied to, if known."
    )


class ClassifyReplyOutput(_Strict):
    category: ReplyCategory
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=300)


# --------------------------------------------------------------------------- assess_lead_fit


class LeadFacts(_Strict):
    """What is known about a lead. Every non-empty field is citable as evidence by its name."""

    title: str | None = Field(default=None, max_length=200)
    company_name: str | None = Field(default=None, max_length=200)
    industry: str | None = Field(default=None, max_length=100)
    company_size: str | None = Field(default=None, max_length=40)
    location: str | None = Field(default=None, max_length=200)
    budget_signal: str | None = Field(default=None, max_length=10)
    source: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=4_000, description="Untrusted free text.")


class AssessLeadFitInput(_Strict):
    lead: LeadFacts
    # The explainable rule-based score, when one exists. The model's view complements it; it never replaces it.
    rule_score: int | None = Field(default=None, ge=0, le=100)


class FitReason(_Strict):
    statement: str = Field(min_length=1, max_length=250)
    # Name of the lead field or profile field the statement rests on, e.g. "industry" or "profile.services".
    evidence_field: str = Field(min_length=1, max_length=60)


class AssessLeadFitOutput(_Strict):
    assessment: Literal["strong", "possible", "weak", "unknown"]
    confidence: float = Field(ge=0, le=1)
    reasons: list[FitReason] = Field(max_length=6)
    gaps: list[Short] = Field(default_factory=list, max_length=6, description="What is not known.")


# --------------------------------------------------------------------------- extract_profile_facts

FactKind = Literal["service", "fact", "case_study", "portfolio", "pricing", "other"]


class ExtractProfileFactsInput(_Strict):
    text: str = Field(min_length=1, max_length=30_000, description="Untrusted document text.")
    source_label: str = Field(default="document", max_length=100)


class ExtractedFact(_Strict):
    kind: FactKind
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=1_000)
    # An exact excerpt of the source that supports the fact. Checked against the source text.
    source_quote: str = Field(min_length=1, max_length=400)


class ExtractProfileFactsOutput(_Strict):
    facts: list[ExtractedFact] = Field(max_length=20)


class ExtractedFactOut(ExtractedFact):
    """A proposed fact. Always ``pending_review``: nothing here is true until the freelancer approves it."""

    status: Literal["pending_review"] = "pending_review"


class ExtractProfileFactsResult(_Strict):
    facts: list[ExtractedFactOut]
    dropped: int = Field(
        description="Proposed facts removed because the source did not support them."
    )


# --------------------------------------------------------------------------- draft_outreach


class DraftLead(_Strict):
    title: str | None = Field(default=None, max_length=200)
    company_name: str | None = Field(default=None, max_length=200)
    industry: str | None = Field(default=None, max_length=100)
    location: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2_000, description="Untrusted free text.")


class DraftOutreachInput(_Strict):
    lead: DraftLead
    recipient_first_name: str | None = Field(default=None, max_length=60)
    goal: str = Field(
        default="Introduce my services and ask whether a short conversation would be useful.",
        min_length=1,
        max_length=300,
    )


class DraftOutreachOutput(_Strict):
    subject: str = Field(min_length=1, max_length=150)
    body: str = Field(min_length=1, max_length=2_500)
    # Ids of approved facts the draft relies on (must all come from the context that was supplied).
    facts_used: list[uuid.UUID] = Field(default_factory=list, max_length=40)
    # Things the model was unsure about or lacked; shown to the person reviewing the draft.
    needs_review: list[Short] = Field(default_factory=list, max_length=8)


# --------------------------------------------------------------------------- summarize_conversation


class ConversationMessage(_Strict):
    direction: Literal["inbound", "outbound"]
    sent_at: datetime | None = None
    subject: str | None = Field(default=None, max_length=500)
    text: str = Field(max_length=4_000, description="Untrusted email text.")


class SummarizeConversationInput(_Strict):
    messages: list[ConversationMessage] = Field(min_length=1, max_length=20)


class SummarizeConversationOutput(_Strict):
    summary: str = Field(min_length=1, max_length=700)
    key_points: list[Short] = Field(default_factory=list, max_length=6)
    open_questions: list[Short] = Field(default_factory=list, max_length=6)


# --------------------------------------------------------------------------- recommend_next_action

NextAction = Literal[
    "reply", "create_follow_up_task", "wait", "pause_outreach", "close_as_lost", "no_action"
]


class RecommendNextActionInput(_Strict):
    lead_status: str | None = Field(default=None, max_length=20)
    stage_name: str | None = Field(default=None, max_length=80)
    last_classification: ReplyCategory | None = None
    conversation_summary: str | None = Field(
        default=None, max_length=1_500, description="Untrusted."
    )
    days_since_last_contact: int | None = Field(default=None, ge=0, le=3650)
    has_open_task: bool = False
    opted_out: bool = Field(default=False, description="The person asked not to be contacted.")


class RecommendNextActionOutput(_Strict):
    action: NextAction
    rationale: str = Field(min_length=1, max_length=300)
    in_days: int | None = Field(default=None, ge=0, le=90)


# --------------------------------------------------------------------------- envelope


class AiMeta(BaseModel):
    """How a result was produced. Shown next to anything a person might rely on."""

    task: str
    provider: str
    model: str | None
    is_mock: bool
    prompt_version: str
    latency_ms: int
    attempts: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    context_hash: str | None = Field(
        default=None, description="Fingerprint of the approved facts that informed the result."
    )
    correlation_id: str
    source: Literal["model", "rules_fallback"] = "model"

    @property
    def label(self) -> str:
        if self.source == "rules_fallback":
            return "Rule-based fallback (the AI provider was unavailable)"
        if self.is_mock:
            return "Demo AI: rule-based stand-in, not a real model"
        return f"AI ({self.provider})"


class AiFailure(BaseModel):
    code: str
    message: str
    retryable: bool = False
    retry_after: int | None = None
    missing: list[str] = Field(default_factory=list)


class AiOutcome[T](BaseModel):
    """Either ``data`` or ``failure``, never both, always with ``meta`` and ``warnings``."""

    ok: bool
    data: T | None = None
    failure: AiFailure | None = None
    meta: AiMeta
    warnings: list[str] = Field(default_factory=list)

    def require(self) -> T:
        if self.data is None:
            raise RuntimeError(
                "AI call failed: " + (self.failure.code if self.failure else "unknown")
            )
        return self.data


JsonSchema = dict[str, Any]
