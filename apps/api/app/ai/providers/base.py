"""The seam between the domain and any model vendor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class ProviderRequest:
    task: str
    tier: Literal["fast", "quality"]
    system: str
    user: str
    # The validated, minimised input as data. Real providers ignore it (they read ``system``/``user``);
    # the demo provider uses it because it has no language model to read a prompt.
    payload: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 20.0
    max_output_tokens: int = 800
    correlation_id: str = ""


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class ModelProvider(Protocol):
    """Implement ``complete`` and the three attributes to add a vendor. Raise the errors in ``app.ai.errors``."""

    name: str
    is_mock: bool

    def model_for(self, tier: Literal["fast", "quality"]) -> str: ...

    def complete(self, request: ProviderRequest) -> ProviderResponse: ...
