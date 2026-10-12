"""Choose the provider from configuration, and hand request handlers a ready ``AiService``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

from app.ai.providers.base import ModelProvider
from app.ai.providers.disabled import DisabledProvider
from app.ai.providers.gateway import GatewayProvider
from app.ai.providers.mock import MockProvider
from app.ai.service import AiLimits, AiService
from app.deps import WorkspaceContext

if TYPE_CHECKING:
    from app.config import Settings


def build_provider(settings: Settings) -> ModelProvider:
    kind = settings.effective_ai_provider
    if kind == "gateway":
        return GatewayProvider(
            base_url=settings.ai_base_url,
            api_key=settings.ai_api_key.get_secret_value(),
            model=settings.ai_model,
            fast_model=settings.ai_model_fast,
        )
    if kind == "mock":
        return MockProvider()
    return DisabledProvider()


def ai_service_for(request: Request, ctx: WorkspaceContext, settings: Settings) -> AiService:
    """One service per request, sharing the app's provider and rate limiter."""
    return AiService(
        request.app.state.ai_provider,
        AiLimits.from_settings(settings),
        workspace_id=ctx.workspace_id,
        limiter=request.app.state.rate_limiter,
    )
