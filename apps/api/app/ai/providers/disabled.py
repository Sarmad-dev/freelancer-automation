from __future__ import annotations

from typing import Literal

from app.ai.errors import Unavailable
from app.ai.providers.base import ProviderRequest, ProviderResponse


class DisabledProvider:
    """Used when no provider is configured. Every call fails cleanly; nothing is sent anywhere."""

    name = "disabled"
    is_mock = False

    def model_for(self, tier: Literal["fast", "quality"]) -> str:
        return ""

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        raise Unavailable()
