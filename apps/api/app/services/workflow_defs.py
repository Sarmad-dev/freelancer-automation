"""Workflow definitions: create, save immutable versions, validate, activate, switch mode; and the output shapes.

A saved version is an immutable snapshot (rows in ``workflow_nodes`` / ``workflow_edges``). Saving never edits an earlier
version, so a run pinned to version 3 keeps running version 3 whatever happens later. A version that does not validate
can be saved (an editor needs to keep work in progress) but can never be activated or started.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.config import Settings
from app.db.models_workflow import (
    ApprovalRequest,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
    WorkflowRun,
    WorkflowStepRun,
    WorkflowVersion,
)
from app.deps import WorkspaceContext
from app.errors import AppError
from app.schemas.workflows import (
    ApprovalOut,
    CatalogOut,
    ConditionFieldOut,
    IssueOut,
    NodeTypeOut,
    RunDetail,
    RunSummary,
    StepRunOut,
    ValidationOut,
    VersionOut,
    VersionSummary,
    WorkflowDetail,
    WorkflowSummary,
)
from app.services.workflows import definition_checksum
from app.workflows import catalog
from app.workflows.definition import (
    MAX_EDGES,
    MAX_NODES,
    SCHEMA_VERSION,
    EdgeDef,
    NodeDef,
    Position,
    WorkflowDefinition,
)
from app.workflows.engine import latest_version
from app.workflows.runtime import ACTIVE_STATUSES
from app.workflows.validate import Report, validate_definition

MAX_DEFINITION_BYTES = 200_000


# ----------------------------------------------------------------------------- catalogue and validation


def catalog_out() -> CatalogOut:
    nodes = [
        NodeTypeOut(
            type=spec.type,
            label=spec.label,
            description=spec.description,
            ports=list(spec.ports),
            side_effect=spec.side_effect,
            default_max_attempts=spec.attempts,
            default_timeout_seconds=spec.timeout_seconds,
            config_schema=spec.model.model_json_schema(),
        )
        for spec in catalog.NODE_SPECS.values()
    ]
    fields = [
        ConditionFieldOut(
            field=name,
            label=f.label,
            kind=f.kind,
            values=list(f.values),
            ops=list(catalog.CONDITION_OPS[f.kind]),
        )
        for name, f in catalog.CONDITION_FIELDS.items()
    ]
    return CatalogOut(
        nodes=nodes,
        trigger_events=list(catalog.TRIGGER_EVENTS),
        condition_fields=fields,
        placeholders=list(catalog.PLACEHOLDERS),
        max_nodes=MAX_NODES,
        max_edges=MAX_EDGES,
    )


def validation_out(report: Report) -> ValidationOut:
    return ValidationOut(
        valid=report.valid,
        issues=[IssueOut(**i.as_dict()) for i in report.issues],
        trigger_event=report.trigger_event,
    )


def check_size(definition: WorkflowDefinition) -> None:
    size = len(json.dumps(definition.model_dump(mode="json"), separators=(",", ":")))
    if size > MAX_DEFINITION_BYTES:
        raise AppError(422, "definition_too_large", "This workflow definition is too large.")


# ----------------------------------------------------------------------------- storing versions


def _next_version_number(db: Session, workflow: Workflow) -> int:
    top = db.scalar(
        select(func.max(WorkflowVersion.version)).where(
            WorkflowVersion.workspace_id == workflow.workspace_id,
            WorkflowVersion.workflow_id == workflow.id,
        )
    )
    return (top or 0) + 1


def save_version(
    db: Session,
    ctx: WorkspaceContext,
    workflow: Workflow,
    definition: WorkflowDefinition,
    note: str | None,
) -> tuple[WorkflowVersion, Report]:
    if workflow.status == "archived":
        raise AppError(409, "workflow_archived", "This workflow is archived.")
    check_size(definition)
    report = validate_definition(definition)
    nodes = [{"key": n.id, "type": n.type, "config": n.config} for n in definition.nodes]
    edges = [
        {"key": e.id, "source": e.source, "target": e.target, "branch": e.branch}
        for e in definition.edges
    ]
    version = WorkflowVersion(
        workspace_id=workflow.workspace_id,
        workflow_id=workflow.id,
        version=_next_version_number(db, workflow),
        schema_version=SCHEMA_VERSION,
        checksum=definition_checksum(nodes, edges),
        note=note,
        valid=report.valid,
        issues=[i.as_dict() for i in report.issues],
        trigger_event=report.trigger_event,
        created_by_user_id=ctx.user.id,
    )
    db.add(version)
    db.flush()
    seen: set[str] = set()
    for n in definition.nodes:
        if n.id in seen:  # duplicates are reported by the validator; only the first is stored
            continue
        seen.add(n.id)
        db.add(
            WorkflowNode(
                workspace_id=workflow.workspace_id,
                version_id=version.id,
                node_key=n.id,
                type=n.type,
                label=n.label,
                config=n.config,
                position_x=n.position.x,
                position_y=n.position.y,
            )
        )
    db.flush()
    edge_seen: set[str] = set()
    for e in definition.edges:
        if e.id in edge_seen or e.source not in seen or e.target not in seen:
            continue  # a dangling connection cannot be stored (the database checks endpoints); it is an issue
        edge_seen.add(e.id)
        db.add(
            WorkflowEdge(
                workspace_id=workflow.workspace_id,
                version_id=version.id,
                edge_key=e.id,
                source_key=e.source,
                target_key=e.target,
                branch=e.branch,
            )
        )
    db.flush()
    return version, report


def definition_of(db: Session, version: WorkflowVersion) -> WorkflowDefinition:
    nodes = db.scalars(
        select(WorkflowNode).where(
            WorkflowNode.workspace_id == version.workspace_id, WorkflowNode.version_id == version.id
        )
    ).all()
    edges = db.scalars(
        select(WorkflowEdge)
        .where(
            WorkflowEdge.workspace_id == version.workspace_id, WorkflowEdge.version_id == version.id
        )
        .order_by(WorkflowEdge.edge_key)
    ).all()
    return WorkflowDefinition(
        schema_version=version.schema_version,
        nodes=[
            NodeDef(
                id=n.node_key,
                type=n.type,
                label=n.label,
                config=dict(n.config or {}),
                position=Position(x=n.position_x, y=n.position_y),
            )
            for n in sorted(nodes, key=lambda x: x.node_key)
        ],
        edges=[
            EdgeDef(id=e.edge_key, source=e.source_key, target=e.target_key, branch=e.branch)
            for e in edges
        ],
    )


def create_workflow(
    db: Session,
    ctx: WorkspaceContext,
    settings: Settings,
    name: str,
    description: str | None,
    definition: WorkflowDefinition | None,
) -> tuple[Workflow, WorkflowVersion | None, Report | None]:
    count = db.scalar(
        select(func.count())
        .select_from(Workflow)
        .where(Workflow.workspace_id == ctx.workspace_id, Workflow.status != "archived")
    )
    if (count or 0) >= settings.workflow_max_workflows:
        raise AppError(
            409, "workflow_limit_reached", "This workspace has reached its limit of workflows."
        )
    workflow = Workflow(
        workspace_id=ctx.workspace_id,
        name=name.strip(),
        description=description,
        status="draft",
        mode="test",
        created_by_user_id=ctx.user.id,
    )
    db.add(workflow)
    db.flush()
    version: WorkflowVersion | None = None
    report: Report | None = None
    if definition is not None:
        version, report = save_version(db, ctx, workflow, definition, "First version")
    return workflow, version, report


# ----------------------------------------------------------------------------- lifecycle


def activate(
    db: Session, ctx: WorkspaceContext, workflow: Workflow, version_number: int | None
) -> WorkflowVersion:
    if workflow.status == "archived":
        raise AppError(409, "workflow_archived", "This workflow is archived.")
    version = (
        latest_version(db, workflow)
        if version_number is None
        else db.scalar(
            select(WorkflowVersion).where(
                WorkflowVersion.workspace_id == workflow.workspace_id,
                WorkflowVersion.workflow_id == workflow.id,
                WorkflowVersion.version == version_number,
            )
        )
    )
    if version is None:
        raise AppError(404, "version_not_found", "That version does not exist.")
    if not version.valid:
        raise AppError(
            409,
            "workflow_invalid",
            "This version has problems that must be fixed before it can be switched on.",
        )
    workflow.status = "active"
    workflow.active_version = version.version
    workflow.trigger_event = version.trigger_event
    audit.record(
        db,
        "workflow.activated",
        actor_user_id=ctx.user.id,
        workspace_id=workflow.workspace_id,
        target_type="workflow",
        target_id=str(workflow.id),
        details={"version": version.version, "mode": workflow.mode},
    )
    return version


def pause(db: Session, ctx: WorkspaceContext, workflow: Workflow) -> None:
    if workflow.status != "active":
        raise AppError(
            409, "workflow_not_active", "Only a workflow that is switched on can be paused."
        )
    workflow.status = "paused"
    audit.record(
        db,
        "workflow.paused",
        actor_user_id=ctx.user.id,
        workspace_id=workflow.workspace_id,
        target_type="workflow",
        target_id=str(workflow.id),
    )


def archive(db: Session, ctx: WorkspaceContext, workflow: Workflow) -> None:
    workflow.status = "archived"
    workflow.trigger_event = None
    audit.record(
        db,
        "workflow.archived",
        actor_user_id=ctx.user.id,
        workspace_id=workflow.workspace_id,
        target_type="workflow",
        target_id=str(workflow.id),
    )


def set_mode(
    db: Session, ctx: WorkspaceContext, workflow: Workflow, mode: str, confirm: bool
) -> None:
    if mode == workflow.mode:
        return
    if mode == "live":
        if workflow.status != "active":
            raise AppError(
                409,
                "workflow_not_active",
                "Switch the workflow on (in test mode) before going live.",
            )
        if not confirm:
            raise AppError(
                422,
                "confirmation_required",
                "Going live means runs change your records and can send email you approve. Confirm to continue.",
                fields={"confirm": "Set confirm to true to go live."},
            )
    workflow.mode = mode
    audit.record(
        db,
        "workflow.mode_changed",
        actor_user_id=ctx.user.id,
        workspace_id=workflow.workspace_id,
        target_type="workflow",
        target_id=str(workflow.id),
        details={"mode": mode},
    )


# ----------------------------------------------------------------------------- output shapes


def _issues(raw: list[dict[str, Any]] | None) -> list[IssueOut]:
    return [IssueOut(**i) for i in (raw or [])]


def version_summaries(db: Session, workflow: Workflow) -> list[VersionSummary]:
    rows = db.scalars(
        select(WorkflowVersion)
        .where(
            WorkflowVersion.workspace_id == workflow.workspace_id,
            WorkflowVersion.workflow_id == workflow.id,
        )
        .order_by(WorkflowVersion.version.desc())
    )
    return [
        VersionSummary(
            version=v.version,
            valid=v.valid,
            issue_count=len(v.issues or []),
            trigger_event=v.trigger_event,
            note=v.note,
            created_at=v.created_at,
            active=v.version == workflow.active_version,
        )
        for v in rows
    ]


def version_out(db: Session, workflow: Workflow, version: WorkflowVersion) -> VersionOut:
    return VersionOut(
        version=version.version,
        valid=version.valid,
        issues=_issues(version.issues),
        trigger_event=version.trigger_event,
        note=version.note,
        created_at=version.created_at,
        active=version.version == workflow.active_version,
        definition=definition_of(db, version),
    )


def workflow_summary(db: Session, workflow: Workflow) -> WorkflowSummary:
    latest = latest_version(db, workflow)
    in_progress = db.scalar(
        select(func.count())
        .select_from(WorkflowRun)
        .where(
            WorkflowRun.workspace_id == workflow.workspace_id,
            WorkflowRun.workflow_id == workflow.id,
            WorkflowRun.status.in_(ACTIVE_STATUSES),
        )
    )
    return WorkflowSummary(
        id=workflow.id,
        name=workflow.name,
        description=workflow.description,
        status=workflow.status,
        mode=workflow.mode,
        active_version=workflow.active_version,
        latest_version=latest.version if latest else None,
        latest_valid=bool(latest and latest.valid),
        trigger_event=workflow.trigger_event,
        runs_in_progress=in_progress or 0,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


def workflow_detail(db: Session, workflow: Workflow) -> WorkflowDetail:
    summary = workflow_summary(db, workflow)
    latest = latest_version(db, workflow)
    return WorkflowDetail(
        **summary.model_dump(),
        latest=version_out(db, workflow, latest) if latest else None,
        versions=version_summaries(db, workflow),
    )


def approval_out(
    approval: ApprovalRequest, *, workflow_name: str | None, workflow_id: uuid.UUID | None
) -> ApprovalOut:
    payload = approval.proposed_payload or {}
    return ApprovalOut(
        id=approval.id,
        run_id=approval.run_id,
        workflow_id=workflow_id,
        workflow_name=workflow_name,
        kind=approval.kind,
        status=approval.status,
        mode=payload.get("mode"),
        summary=payload.get("summary"),
        draft_id=approval.draft_id,
        target_type=approval.target_type,
        target_id=approval.target_id,
        expires_at=approval.expires_at,
        decided_at=approval.decided_at,
        decision_note=approval.decision_note,
        invalidated_reason=approval.invalidated_reason,
        created_at=approval.created_at,
    )


def run_summary(
    run: WorkflowRun, *, workflow_name: str | None, version_number: int | None
) -> RunSummary:
    return RunSummary(
        id=run.id,
        workflow_id=run.workflow_id,
        workflow_name=workflow_name,
        version=version_number,
        status=run.status,
        mode=run.mode,
        trigger_type=run.trigger_type,
        subject_type=run.subject_type,
        subject_id=run.subject_id,
        current_node_key=run.current_node_key,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        wake_at=run.wake_at,
        error_category=run.error_category,
        error_summary=run.error_summary,
        cancel_requested=run.cancel_requested_at is not None,
        correlation_id=run.correlation_id,
    )


def run_summaries(db: Session, runs: list[WorkflowRun]) -> list[RunSummary]:
    if not runs:
        return []
    workflows = {
        w.id: w
        for w in db.scalars(select(Workflow).where(Workflow.id.in_({r.workflow_id for r in runs})))
    }
    versions = {
        v.id: v.version
        for v in db.scalars(
            select(WorkflowVersion).where(WorkflowVersion.id.in_({r.version_id for r in runs}))
        )
    }
    return [
        run_summary(
            r,
            workflow_name=workflows[r.workflow_id].name if r.workflow_id in workflows else None,
            version_number=versions.get(r.version_id),
        )
        for r in runs
    ]


def run_detail(db: Session, run: WorkflowRun) -> RunDetail:
    base = run_summaries(db, [run])[0]
    types = {
        n.node_key: (n.type, n.label)
        for n in db.scalars(
            select(WorkflowNode).where(
                WorkflowNode.workspace_id == run.workspace_id,
                WorkflowNode.version_id == run.version_id,
            )
        )
    }
    steps = db.scalars(
        select(WorkflowStepRun)
        .where(WorkflowStepRun.workspace_id == run.workspace_id, WorkflowStepRun.run_id == run.id)
        .order_by(WorkflowStepRun.created_at, WorkflowStepRun.attempt)
    ).all()
    approvals = db.scalars(
        select(ApprovalRequest)
        .where(ApprovalRequest.workspace_id == run.workspace_id, ApprovalRequest.run_id == run.id)
        .order_by(ApprovalRequest.created_at)
    ).all()
    return RunDetail(
        **base.model_dump(),
        steps=[
            StepRunOut(
                id=s.id,
                node_key=s.node_key,
                node_type=types.get(s.node_key, (None, None))[0],
                node_label=types.get(s.node_key, (None, None))[1],
                attempt=s.attempt,
                status=s.status,
                port=s.port,
                started_at=s.started_at,
                finished_at=s.finished_at,
                next_attempt_at=s.next_attempt_at,
                output_summary=dict(s.output_summary or {}),
                error_category=s.error_category,
                error_summary=s.error_summary,
            )
            for s in steps
        ],
        approvals=[
            approval_out(a, workflow_name=base.workflow_name, workflow_id=run.workflow_id)
            for a in approvals
        ],
        context=dict(run.context or {}),
    )
