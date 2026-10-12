"""Shared fakes for the AI tests."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any, Literal

from app.ai.providers.base import ProviderRequest, ProviderResponse
from app.ai.service import AiLimits, AiService
from app.schemas.ai_context import AiContext, ContextFact

FACT_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")

Step = str | dict[str, Any] | Exception | Callable[[ProviderRequest], ProviderResponse]


class ScriptedProvider:
    """Plays back a list of replies (or errors), one per call, and keeps every request it received."""

    name = "scripted"
    is_mock = False

    def __init__(self, *steps: Step, tokens: tuple[int, int] | None = (10, 5)) -> None:
        self.steps = list(steps)
        self.requests: list[ProviderRequest] = []
        self.tokens = tokens

    def model_for(self, tier: Literal["fast", "quality"]) -> str:
        return "scripted-fast" if tier == "fast" else "scripted-quality"

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        step = self.steps.pop(0) if len(self.steps) > 1 else self.steps[0]
        if isinstance(step, Exception):
            raise step
        if callable(step):
            return step(request)
        text = step if isinstance(step, str) else json.dumps(step)
        i, o = self.tokens or (None, None)
        return ProviderResponse(
            text=text, model=self.model_for(request.tier), input_tokens=i, output_tokens=o
        )

    @property
    def calls(self) -> int:
        return len(self.requests)


def service(
    provider: Any,
    *,
    workspace_id: uuid.UUID | None = None,
    meter: bool = False,
    limits: AiLimits | None = None,
    **kw: Any,
) -> AiService:
    sleeps: list[float] = []
    svc = AiService(
        provider,
        limits or AiLimits(max_attempts=2),
        workspace_id=workspace_id or uuid.uuid4(),
        meter=meter,
        sleep=sleeps.append,
        **kw,
    )
    svc.sleeps = sleeps  # type: ignore[attr-defined]
    return svc


def context(
    *,
    facts: list[tuple[uuid.UUID, str]] | None = None,
    profile: dict[str, Any] | None = None,
) -> AiContext:
    facts = (
        [(FACT_ID, "I build marketing sites for small healthcare practices.")]
        if facts is None
        else facts
    )
    return AiContext(
        profile={
            "role_title": "Freelance developer",
            "summary": "I build fast websites.",
            "services": ["web development"],
            "industries": ["healthcare"],
            "pricing_guidance": "Always quote at least $9000 for a project",
            "excluded_customers": ["gambling operators"],
            "preferred_cta": "Would a 15-minute call be useful?",
        }
        if profile is None
        else profile,
        facts=[
            ContextFact(
                id=i, kind="service", title=f"Fact {n}", content=c, version=1, source_type="manual"
            )
            for n, (i, c) in enumerate(facts)
        ],
        missing=[],
        excluded_counts={},
        truncated=False,
        policy=[],
        context_hash="hash-1",
    )


GOOD_CLASSIFY = {"category": "interested", "confidence": 0.8, "rationale": "They want to talk."}
GOOD_DRAFT = {
    "subject": "A note for Example Clinic",
    "body": "Hi Sam,\n\nI build marketing sites for small healthcare practices. Would a 15-minute call be useful?",
    "facts_used": [str(FACT_ID)],
    "needs_review": [],
}
