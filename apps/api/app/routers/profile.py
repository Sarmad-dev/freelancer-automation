"""Freelancer profile, its public-summary preview, and the AI context transparency view."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app import audit
from app.deps import DbDep, SettingsDep, WorkspaceDep, require_owner
from app.errors import ErrorResponse
from app.schemas.ai_context import AiContext
from app.schemas.profile import ProfileOut, ProfilePatch, ProfileSummary
from app.services import ai_context as ai_context_service
from app.services import profile as svc

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}", tags=["profile"])

_ERR: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


@router.get(
    "/profile", response_model=ProfileOut, responses=_ERR, summary="Get the freelancer profile"
)
def get_profile(ctx: WorkspaceDep, db: DbDep) -> ProfileOut:
    profile = svc.get_profile(db, ctx)
    db.commit()
    return svc.to_out(profile, ctx)


@router.patch(
    "/profile",
    response_model=ProfileOut,
    responses=_ERR,
    summary="Update the profile (partial; 409 if expected_version is stale)",
)
def update_profile(
    body: ProfilePatch, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> ProfileOut:
    require_owner(ctx)
    profile, changed = svc.apply_patch(db, ctx, body)
    if changed:
        audit.record(
            db,
            "profile.updated",
            info=audit.request_info(request, settings),
            actor_user_id=ctx.user.id,
            workspace_id=ctx.workspace_id,
            details={"fields": changed, "version": profile.version},
        )
    db.commit()
    db.refresh(profile)
    return svc.to_out(profile, ctx)


@router.get(
    "/profile/summary",
    response_model=ProfileSummary,
    responses=_ERR,
    summary="Preview of the public-facing professional summary (entered fields only; private fields excluded)",
)
def profile_summary(ctx: WorkspaceDep, db: DbDep) -> ProfileSummary:
    return svc.build_summary(svc.get_profile(db, ctx))


@router.get(
    "/ai-context",
    response_model=AiContext,
    responses=_ERR,
    summary="Exactly what an AI model may know: profile + approved, enabled knowledge",
)
def ai_context(ctx: WorkspaceDep, db: DbDep) -> AiContext:
    return ai_context_service.build_context(db, ctx)
