"""AI configuration status. Calling a model happens inside other features (inbox, drafts, workflows)."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Request
from sqlalchemy import case, func, select

from app.ai.prompts import TEMPLATES
from app.ai.service import AiLimits
from app.clock import utcnow
from app.db.models_workflow import UsageRecord
from app.deps import DbDep, SettingsDep, WorkspaceDep
from app.routers._common import ERRORS
from app.schemas.ai import AiStatus, AiTaskStatus, AiUsageSummary

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/ai", tags=["ai"])

_WINDOW_HOURS = 24


@router.get(
    "/status", response_model=AiStatus, responses=ERRORS, summary="Which AI provider is in use"
)
def ai_status(ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep) -> AiStatus:
    provider = request.app.state.ai_provider
    limits = AiLimits.from_settings(settings)
    since = utcnow() - timedelta(hours=_WINDOW_HOURS)
    calls, failures, mocks, latency = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(case((UsageRecord.success.is_(False), 1), else_=0)), 0),
            func.coalesce(func.sum(case((UsageRecord.is_mock.is_(True), 1), else_=0)), 0),
            func.avg(UsageRecord.latency_ms),
        ).where(
            UsageRecord.workspace_id == ctx.workspace_id,
            UsageRecord.kind == "ai",
            UsageRecord.occurred_at >= since,
        )
    ).one()
    available = provider.name != "disabled"
    if provider.is_mock:
        label = "Demo AI: a rule-based stand-in, not a real model. Results are labelled."
    elif available:
        label = f"AI provider: {provider.name}"
    else:
        label = "AI is not set up for this installation."
    return AiStatus(
        provider=provider.name,
        available=available,
        is_mock=provider.is_mock,
        label=label,
        model=provider.model_for("quality") or None,
        fast_model=provider.model_for("fast") or None,
        rate_limit_per_minute=limits.rate_limit_per_minute,
        timeout_seconds=limits.timeout_seconds,
        max_attempts=limits.max_attempts,
        tasks=[
            AiTaskStatus(task=t.task, prompt_version=t.version, model_tier=t.tier)
            for t in TEMPLATES.values()
        ],
        usage=AiUsageSummary(
            window_hours=_WINDOW_HOURS,
            calls=int(calls),
            failures=int(failures),
            mock_calls=int(mocks),
            average_latency_ms=int(latency) if latency is not None else None,
        ),
    )
