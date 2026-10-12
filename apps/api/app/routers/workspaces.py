from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app import audit
from app.deps import DbDep, SettingsDep, WorkspaceDep, require_owner
from app.errors import ErrorResponse
from app.schemas.auth import WorkspaceOut
from app.schemas.onboarding import DemoModeRequest, OnboardingState, OnboardingStepInput
from app.services import onboarding as svc

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}", tags=["workspaces"])

_ERR: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


@router.get(
    "/onboarding",
    response_model=OnboardingState,
    responses=_ERR,
    summary="Onboarding progress and profile draft",
)
def get_onboarding(ctx: WorkspaceDep, db: DbDep) -> OnboardingState:
    progress, profile = svc.get_or_create_rows(db, ctx)
    db.commit()
    return svc.build_state(ctx, progress, profile)


@router.put(
    "/onboarding/step",
    response_model=OnboardingState,
    responses=_ERR,
    summary="Validate and save one onboarding step",
)
def save_onboarding_step(
    body: OnboardingStepInput, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> OnboardingState:
    require_owner(ctx)
    state = svc.save_step(db, ctx, body)
    audit.record(
        db,
        "onboarding.step_saved",
        info=audit.request_info(request, settings),
        actor_user_id=ctx.user.id,
        workspace_id=ctx.workspace_id,
        details={"step": body.step},
    )
    db.commit()
    return state


@router.post(
    "/onboarding/skip",
    response_model=OnboardingState,
    responses=_ERR,
    summary="Skip for now; progress is kept",
)
def skip_onboarding(
    ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> OnboardingState:
    require_owner(ctx)
    state = svc.skip(db, ctx)
    audit.record(
        db,
        "onboarding.skipped",
        info=audit.request_info(request, settings),
        actor_user_id=ctx.user.id,
        workspace_id=ctx.workspace_id,
        details={"status": state.status},
    )
    db.commit()
    return state


@router.post(
    "/onboarding/complete",
    response_model=OnboardingState,
    responses=_ERR,
    summary="Finish onboarding (all required steps must be saved)",
)
def complete_onboarding(
    ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> OnboardingState:
    require_owner(ctx)
    state = svc.complete(db, ctx)
    audit.record(
        db,
        "onboarding.completed",
        info=audit.request_info(request, settings),
        actor_user_id=ctx.user.id,
        workspace_id=ctx.workspace_id,
    )
    db.commit()
    return state


@router.put(
    "/demo-mode", response_model=WorkspaceOut, responses=_ERR, summary="Turn demo mode on or off"
)
def set_demo_mode(
    body: DemoModeRequest, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> WorkspaceOut:
    require_owner(ctx)
    ctx.workspace.demo_mode = body.enabled
    audit.record(
        db,
        "workspace.demo_mode_changed",
        info=audit.request_info(request, settings),
        actor_user_id=ctx.user.id,
        workspace_id=ctx.workspace_id,
        details={"demo_mode": body.enabled},
    )
    db.commit()
    progress, _ = svc.get_or_create_rows(db, ctx)
    return WorkspaceOut(
        id=ctx.workspace.id,
        name=ctx.workspace.name,
        kind=ctx.workspace.kind,
        role=ctx.membership.role,
        timezone=ctx.workspace.timezone,
        demo_mode=ctx.workspace.demo_mode,
        onboarding_status=progress.status,
    )
