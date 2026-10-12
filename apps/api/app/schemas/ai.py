from __future__ import annotations

from pydantic import BaseModel, Field


class AiTaskStatus(BaseModel):
    task: str
    prompt_version: str
    model_tier: str


class AiUsageSummary(BaseModel):
    window_hours: int
    calls: int
    failures: int
    mock_calls: int
    average_latency_ms: int | None


class AiStatus(BaseModel):
    """What is behind the AI features, without any secret. Safe for every member to read."""

    provider: str = Field(description="mock | gateway | disabled")
    available: bool = Field(description="False when AI is switched off.")
    is_mock: bool = Field(
        description="True when results come from the rule-based stand-in, not a model."
    )
    label: str
    model: str | None
    fast_model: str | None
    rate_limit_per_minute: int
    timeout_seconds: float
    max_attempts: int
    tasks: list[AiTaskStatus]
    usage: AiUsageSummary
