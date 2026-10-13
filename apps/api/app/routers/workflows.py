"""Workflows: the catalogue of nodes, validation, workflows and their immutable versions, switching on, test/live mode,
and starting a run by hand. Reading is open to members; every change needs the owner role and is audited without content."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response, status

from app import audit
from app.api.pagination import Page, PageParams, page_params, paginate
from app.api.scoping import get_scoped_or_404, scoped_select
from app.clock import utcnow
from app.db.models_workflow import Workflow, WorkflowVersion
from app.deps import DbDep, SettingsDep, WorkspaceDep, require_owner
from app.errors import AppError
from app.routers._common import ERRORS
from app.schemas.workflows import (
    ActivateIn,
    CatalogOut,
    ModeIn,
    RunStart,
    StartRunOut,
    ValidateIn,
    ValidationOut,
    VersionCreate,
    VersionOut,
    WorkflowCreate,
    WorkflowDetail,
    WorkflowPatch,
    WorkflowSummary,
)
from app.services import workflow_defs as defs
from app.workflows import engine
from app.workflows.validate import validate_definition

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/workflows", tags=["workflows"])


def _get(db: DbDep, ctx: WorkspaceDep, workflow_id: uuid.UUID) -> Workflow:
    return get_scoped_or_404(
        db, Workflow, ctx, workflow_id, code="workflow_not_found", message="Workflow not found."
    )


@router.get(
    "/catalog",
    response_model=CatalogOut,
    responses=ERRORS,
    summary="The node types, their settings and ports, and the values conditions and templates may use",
)
def get_catalog(ctx: WorkspaceDep) -> CatalogOut:
    return defs.catalog_out()


@router.post(
    "/validate",
    response_model=ValidationOut,
    responses=ERRORS,
    summary="Check a definition without saving it",
)
def validate(body: ValidateIn, ctx: WorkspaceDep) -> ValidationOut:
    return defs.validation_out(validate_definition(body.definition))


@router.get("", response_model=Page[WorkflowSummary], responses=ERRORS, summary="List workflows")
def list_workflows(
    ctx: WorkspaceDep,
    db: DbDep,
    params: Annotated[PageParams, Depends(page_params)],
    workflow_status: Annotated[
        Literal["draft", "active", "paused", "archived"] | None, Query(alias="status")
    ] = None,
) -> Page[WorkflowSummary]:
    stmt = scoped_select(Workflow, ctx)
    if workflow_status is None:
        stmt = stmt.where(Workflow.status != "archived")
    else:
        stmt = stmt.where(Workflow.status == workflow_status)
    rows, total = paginate(
        db,
        stmt,
        params,
        allowed_sort={
            "name": Workflow.name,
            "created_at": Workflow.created_at,
            "updated_at": Workflow.updated_at,
        },
        default_sort="-updated_at",
        tie_breaker=Workflow.id,
    )
    return Page[WorkflowSummary](
        items=[defs.workflow_summary(db, w) for w in rows],
        total=total,
        limit=params.limit,
        offset=params.offset,
    )


@router.post(
    "",
    response_model=WorkflowDetail,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
    summary="Create a workflow (in draft and test mode), optionally with a first version",
)
def create_workflow(
    body: WorkflowCreate, ctx: WorkspaceDep, db: DbDep, settings: SettingsDep
) -> WorkflowDetail:
    require_owner(ctx)
    workflow, _version, _report = defs.create_workflow(
        db, ctx, settings, body.name, body.description, body.definition
    )
    audit.record(
        db,
        "workflow.created",
        actor_user_id=ctx.user.id,
        workspace_id=ctx.workspace_id,
        target_type="workflow",
        target_id=str(workflow.id),
    )
    db.commit()
    db.refresh(workflow)
    return defs.workflow_detail(db, workflow)


@router.get(
    "/{workflow_id}", response_model=WorkflowDetail, responses=ERRORS, summary="Get a workflow"
)
def get_workflow(workflow_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep) -> WorkflowDetail:
    return defs.workflow_detail(db, _get(db, ctx, workflow_id))


@router.patch(
    "/{workflow_id}", response_model=WorkflowDetail, responses=ERRORS, summary="Rename a workflow"
)
def patch_workflow(
    workflow_id: uuid.UUID, body: WorkflowPatch, ctx: WorkspaceDep, db: DbDep
) -> WorkflowDetail:
    require_owner(ctx)
    workflow = _get(db, ctx, workflow_id)
    if body.name is not None:
        workflow.name = body.name.strip()
    if "description" in body.model_fields_set:
        workflow.description = body.description
    db.commit()
    db.refresh(workflow)
    return defs.workflow_detail(db, workflow)


@router.post(
    "/{workflow_id}/versions",
    response_model=VersionOut,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
    summary="Save a new, immutable version (it may have problems; it cannot be switched on until it has none)",
)
def create_version(
    workflow_id: uuid.UUID, body: VersionCreate, ctx: WorkspaceDep, db: DbDep
) -> VersionOut:
    require_owner(ctx)
    workflow = _get(db, ctx, workflow_id)
    version, _report = defs.save_version(db, ctx, workflow, body.definition, body.note)
    audit.record(
        db,
        "workflow.version_saved",
        actor_user_id=ctx.user.id,
        workspace_id=ctx.workspace_id,
        target_type="workflow",
        target_id=str(workflow.id),
        details={"version": version.version, "status": "valid" if version.valid else "invalid"},
    )
    db.commit()
    db.refresh(workflow)
    db.refresh(version)
    return defs.version_out(db, workflow, version)


@router.get(
    "/{workflow_id}/versions/{version}",
    response_model=VersionOut,
    responses=ERRORS,
    summary="Get one version",
)
def get_version(workflow_id: uuid.UUID, version: int, ctx: WorkspaceDep, db: DbDep) -> VersionOut:
    workflow = _get(db, ctx, workflow_id)
    row = db.scalar(
        scoped_select(WorkflowVersion, ctx).where(
            WorkflowVersion.workflow_id == workflow.id, WorkflowVersion.version == version
        )
    )
    if row is None:
        raise AppError(404, "version_not_found", "That version does not exist.")
    return defs.version_out(db, workflow, row)


@router.post(
    "/{workflow_id}/activate",
    response_model=WorkflowDetail,
    responses=ERRORS,
    summary="Switch a valid version on. New workflows stay in test mode until you go live.",
)
def activate(
    workflow_id: uuid.UUID, body: ActivateIn, ctx: WorkspaceDep, db: DbDep
) -> WorkflowDetail:
    require_owner(ctx)
    workflow = _get(db, ctx, workflow_id)
    defs.activate(db, ctx, workflow, body.version)
    db.commit()
    db.refresh(workflow)
    return defs.workflow_detail(db, workflow)


@router.post(
    "/{workflow_id}/pause",
    response_model=WorkflowDetail,
    responses=ERRORS,
    summary="Stop starting new runs (runs already in progress continue)",
)
def pause(workflow_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep) -> WorkflowDetail:
    require_owner(ctx)
    workflow = _get(db, ctx, workflow_id)
    defs.pause(db, ctx, workflow)
    db.commit()
    db.refresh(workflow)
    return defs.workflow_detail(db, workflow)


@router.post(
    "/{workflow_id}/archive",
    response_model=WorkflowDetail,
    responses=ERRORS,
    summary="Archive a workflow (it can no longer run)",
)
def archive(workflow_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep) -> WorkflowDetail:
    require_owner(ctx)
    workflow = _get(db, ctx, workflow_id)
    defs.archive(db, ctx, workflow)
    db.commit()
    db.refresh(workflow)
    return defs.workflow_detail(db, workflow)


@router.post(
    "/{workflow_id}/mode",
    response_model=WorkflowDetail,
    responses=ERRORS,
    summary="Switch between test mode (record changes and sending are simulated) and live mode",
)
def set_mode(workflow_id: uuid.UUID, body: ModeIn, ctx: WorkspaceDep, db: DbDep) -> WorkflowDetail:
    require_owner(ctx)
    workflow = _get(db, ctx, workflow_id)
    defs.set_mode(db, ctx, workflow, body.mode, body.confirm)
    db.commit()
    db.refresh(workflow)
    return defs.workflow_detail(db, workflow)


@router.post(
    "/{workflow_id}/runs",
    response_model=StartRunOut,
    responses=ERRORS,
    summary="Start a run by hand. A workflow that is not switched on runs in test mode only.",
)
def start_run(
    workflow_id: uuid.UUID,
    body: RunStart,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    settings: SettingsDep,
) -> StartRunOut:
    require_owner(ctx)
    workflow = _get(db, ctx, workflow_id)
    now = utcnow()
    key = body.idempotency_key or f"manual:{uuid.uuid4().hex}"
    result = engine.start_run(
        db,
        settings,
        workflow,
        trigger_type="manual"
        if workflow.trigger_event in (None, "manual")
        else workflow.trigger_event,
        subject_type=body.subject_type,
        subject_id=body.subject_id,
        idempotency_key=key,
        now=now,
        started_by_user_id=ctx.user.id,
        event=False,
    )
    assert result.run is not None
    db.commit()
    db.refresh(result.run)
    if result.created:
        response.status_code = status.HTTP_201_CREATED
        background.add_task(engine.run_worker, request.app, workspace_id=ctx.workspace_id)
    summary = defs.run_summaries(db, [result.run])[0]
    return StartRunOut(run=summary, created=result.created)
