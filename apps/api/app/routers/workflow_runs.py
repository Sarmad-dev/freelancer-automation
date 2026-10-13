"""Workflow runs: list, inspect (every step), cancel and retry. Reading is open to members; changes need the owner role."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request

from app.api.pagination import Page, PageParams, page_params, paginate
from app.api.scoping import get_scoped_or_404, scoped_select
from app.clock import utcnow
from app.db.models_workflow import WorkflowRun
from app.deps import DbDep, WorkspaceDep, require_owner
from app.routers._common import ERRORS
from app.schemas.workflows import CancelOut, RunDetail, RunSummary
from app.services import workflow_defs as defs
from app.workflows import engine

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/workflow-runs", tags=["workflow runs"])


def _get(db: DbDep, ctx: WorkspaceDep, run_id: uuid.UUID) -> WorkflowRun:
    return get_scoped_or_404(
        db, WorkflowRun, ctx, run_id, code="run_not_found", message="Run not found."
    )


@router.get("", response_model=Page[RunSummary], responses=ERRORS, summary="List workflow runs")
def list_runs(
    ctx: WorkspaceDep,
    db: DbDep,
    params: Annotated[PageParams, Depends(page_params)],
    workflow_id: Annotated[uuid.UUID | None, Query()] = None,
    subject_id: Annotated[uuid.UUID | None, Query()] = None,
    run_status: Annotated[
        Literal[
            "queued",
            "running",
            "waiting_approval",
            "waiting_delay",
            "succeeded",
            "failed",
            "cancelled",
        ]
        | None,
        Query(alias="status"),
    ] = None,
) -> Page[RunSummary]:
    stmt = scoped_select(WorkflowRun, ctx)
    if workflow_id is not None:
        stmt = stmt.where(WorkflowRun.workflow_id == workflow_id)
    if subject_id is not None:
        stmt = stmt.where(WorkflowRun.subject_id == subject_id)
    if run_status is not None:
        stmt = stmt.where(WorkflowRun.status == run_status)
    rows, total = paginate(
        db,
        stmt,
        params,
        allowed_sort={"created_at": WorkflowRun.created_at, "finished_at": WorkflowRun.finished_at},
        default_sort="-created_at",
        tie_breaker=WorkflowRun.id,
    )
    return Page[RunSummary](
        items=defs.run_summaries(db, rows), total=total, limit=params.limit, offset=params.offset
    )


@router.get(
    "/{run_id}", response_model=RunDetail, responses=ERRORS, summary="Get a run with its steps"
)
def get_run(run_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep) -> RunDetail:
    return defs.run_detail(db, _get(db, ctx, run_id))


@router.post(
    "/{run_id}/cancel",
    response_model=CancelOut,
    responses=ERRORS,
    summary="Cancel a run. One that is executing stops before its next step.",
)
def cancel_run(run_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep) -> CancelOut:
    require_owner(ctx)
    run = _get(db, ctx, run_id)
    outcome = engine.request_cancel(db, run, utcnow())
    db.commit()
    db.refresh(run)
    return CancelOut(
        status="cancelled" if outcome == "cancelled" else "cancelling",
        run=defs.run_summaries(db, [run])[0],
    )


@router.post(
    "/{run_id}/retry",
    response_model=RunDetail,
    responses=ERRORS,
    summary="Retry the step that failed. A send the provider never confirmed must be resolved on the draft first.",
)
def retry_run(
    run_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep, request: Request, background: BackgroundTasks
) -> RunDetail:
    require_owner(ctx)
    run = _get(db, ctx, run_id)
    engine.retry_failed(db, run, utcnow())
    db.commit()
    db.refresh(run)
    background.add_task(engine.run_worker, request.app, workspace_id=ctx.workspace_id)
    return defs.run_detail(db, run)
