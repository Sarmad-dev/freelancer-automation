"""Approvals: what is waiting for a person's yes or no. Anyone in the workspace can look; only the owner decides."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request

from app.api.pagination import Page, PageParams, page_params, paginate
from app.api.scoping import get_scoped_or_404, scoped_select
from app.clock import utcnow
from app.db.models_workflow import ApprovalRequest, Workflow, WorkflowRun
from app.deps import DbDep, WorkspaceDep, require_owner
from app.routers._common import ERRORS
from app.schemas.workflows import ApprovalOut, DecideIn
from app.services import workflow_defs as defs
from app.workflows import approvals, engine

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/approvals", tags=["approvals"])


def _out(db: DbDep, approval: ApprovalRequest) -> ApprovalOut:
    run = db.get(WorkflowRun, approval.run_id) if approval.run_id else None
    workflow = db.get(Workflow, run.workflow_id) if run is not None else None
    return defs.approval_out(
        approval,
        workflow_name=workflow.name if workflow else None,
        workflow_id=workflow.id if workflow else None,
    )


@router.get("", response_model=Page[ApprovalOut], responses=ERRORS, summary="List approvals")
def list_approvals(
    ctx: WorkspaceDep,
    db: DbDep,
    params: Annotated[PageParams, Depends(page_params)],
    approval_status: Annotated[
        Literal["pending", "approved", "rejected", "expired", "cancelled", "invalidated"] | None,
        Query(alias="status"),
    ] = "pending",
    run_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[ApprovalOut]:
    stmt = scoped_select(ApprovalRequest, ctx)
    if approval_status is not None:
        stmt = stmt.where(ApprovalRequest.status == approval_status)
    if run_id is not None:
        stmt = stmt.where(ApprovalRequest.run_id == run_id)
    rows, total = paginate(
        db,
        stmt,
        params,
        allowed_sort={
            "created_at": ApprovalRequest.created_at,
            "expires_at": ApprovalRequest.expires_at,
        },
        default_sort="-created_at",
        tie_breaker=ApprovalRequest.id,
    )
    return Page[ApprovalOut](
        items=[_out(db, a) for a in rows], total=total, limit=params.limit, offset=params.offset
    )


@router.get(
    "/{approval_id}", response_model=ApprovalOut, responses=ERRORS, summary="Get an approval"
)
def get_approval(approval_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep) -> ApprovalOut:
    approval = get_scoped_or_404(
        db,
        ApprovalRequest,
        ctx,
        approval_id,
        code="approval_not_found",
        message="Approval not found.",
    )
    return _out(db, approval)


@router.post(
    "/{approval_id}/decide",
    response_model=ApprovalOut,
    responses=ERRORS,
    summary="Approve or reject. Approving a draft approves exactly the text that was requested; the run then continues.",
)
def decide(
    approval_id: uuid.UUID,
    body: DecideIn,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    background: BackgroundTasks,
) -> ApprovalOut:
    require_owner(ctx)
    approval = get_scoped_or_404(
        db,
        ApprovalRequest,
        ctx,
        approval_id,
        code="approval_not_found",
        message="Approval not found.",
    )
    approvals.decide(db, ctx, approval, body.decision, body.note, utcnow())
    db.commit()
    db.refresh(approval)
    background.add_task(engine.run_worker, request.app, workspace_id=ctx.workspace_id)
    return _out(db, approval)
