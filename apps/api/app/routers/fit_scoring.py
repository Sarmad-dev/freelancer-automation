"""Fit-scoring criteria (MVP Prompt 6): read, edit and recompute."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.deps import DbDep, SettingsDep, WorkspaceDep, require_owner
from app.errors import AppError
from app.routers._common import ERRORS, audit_event
from app.schemas.fit import FitConfigIn, FitConfigOut, RescoreResult
from app.services import fit_scoring as svc

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/fit-scoring", tags=["fit-scoring"])


def _out(
    version: int, criteria: list[dict[str, Any]], updated_at: Any, rescored: int | None = None
) -> FitConfigOut:
    return FitConfigOut.model_validate(
        {"version": version, "criteria": criteria, "updated_at": updated_at, "rescored": rescored}
    )


@router.get(
    "", response_model=FitConfigOut, responses=ERRORS, summary="Current fit-scoring criteria"
)
def get_config(ctx: WorkspaceDep, db: DbDep) -> FitConfigOut:
    version, criteria, updated_at = svc.current_config(db, ctx)
    return _out(version, criteria, updated_at)


@router.put(
    "",
    response_model=FitConfigOut,
    responses=ERRORS,
    summary="Save the criteria (and by default recompute every active lead)",
)
def put_config(
    body: FitConfigIn, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> FitConfigOut:
    require_owner(ctx)
    current, _, _ = svc.current_config(db, ctx)
    if body.expected_version is not None and body.expected_version != current:
        raise AppError(
            409,
            "stale_version",
            "The criteria changed after you opened them. Reload and try again.",
        )
    row, changed = svc.save_config(db, ctx, body)
    rescored = svc.rescore_all(db, ctx) if body.rescore and changed else None
    if changed:
        audit_event(
            db,
            ctx,
            request,
            settings,
            "fit_scoring.updated",
            "fit_scoring",
            row.id,
            version=row.version,
        )
    db.commit()
    return _out(row.version, row.criteria, row.updated_at, rescored)


@router.post(
    "/rescore",
    response_model=RescoreResult,
    responses=ERRORS,
    summary="Recompute the score of every active lead",
)
def rescore(ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep) -> RescoreResult:
    require_owner(ctx)
    count = svc.rescore_all(db, ctx)
    audit_event(
        db, ctx, request, settings, "fit_scoring.rescored", "fit_scoring", None, count=count
    )
    db.commit()
    return RescoreResult(rescored=count)
