"""The execution engine: starting runs, claiming them from the database queue, walking the graph one step at a time.

How it works (details and limits in docs/WORKFLOWS.md):

* A **run** is one pass through one pinned **version** of a workflow. It is a row; where it is in the graph is
  ``current_node_key``; what it has learned is ``context`` (ids and short enumerations only).
* The **queue is the database.** A run is due when it is ``queued`` (and its ``wake_at`` has passed), or
  ``waiting_delay`` with ``wake_at`` passed, or ``running`` with an expired lease (its worker died). A worker claims
  runs with a conditional ``UPDATE`` (two workers cannot take the same run), keeps its lease alive between steps, and
  stops if it ever finds the lease is no longer its own. Nothing depends on an in-memory timer or an open request.
* Every **step** is a ``workflow_step_runs`` row, committed as ``running`` *before* the executor does anything, and
  finished in the same transaction as the executor's own writes. A crash leaves a ``running`` step that the next worker
  marks ``interrupted`` and retries.
* **Failures** are categorised (``errors.py``). Only retryable categories are retried automatically, with backoff and a
  per-node attempt limit; a person can retry a failed step by hand (a send whose outcome is unknown is excluded).
* **Waiting**: a delay stores ``wake_at``; an approval gate stores an ``approval_requests`` row. A decision (or expiry)
  makes the run due again. The run continues from the database, not from memory.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app import audit
from app.clock import as_utc
from app.config import Settings
from app.db.models_crm import Lead
from app.db.models_email import Conversation
from app.db.models_workflow import (
    ApprovalRequest,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
    WorkflowRun,
    WorkflowStepRun,
    WorkflowVersion,
)
from app.errors import AppError
from app.workflows import catalog
from app.workflows.errors import CATEGORIES, StepFailure, from_app_error
from app.workflows.executors import (
    EXECUTORS,
    db_get_scoped,
    notify_owners,
    resume_approval,
)
from app.workflows.runtime import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    Advance,
    EngineDeps,
    Finish,
    StepEnv,
    WaitApproval,
    WaitDelay,
    owner_context,
    safe_summary,
)

logger = logging.getLogger("freelancer_os.workflows")

LEASE = timedelta(minutes=5)
MAX_STEPS_PER_CLAIM = 25
MAX_STEPS_PER_RUN = 100
BACKOFF_SECONDS = (30, 120, 600, 1800, 3600)


# ----------------------------------------------------------------------------- loading a version


@dataclass
class LoadedNode:
    key: str
    type: str
    label: str | None
    config: dict[str, Any]


@dataclass
class LoadedVersion:
    version_id: uuid.UUID
    nodes: dict[str, LoadedNode] = field(default_factory=dict)
    edges: dict[tuple[str, str], str] = field(default_factory=dict)


def load_version(db: Session, workspace_id: uuid.UUID, version_id: uuid.UUID) -> LoadedVersion:
    loaded = LoadedVersion(version_id)
    for n in db.scalars(
        select(WorkflowNode).where(
            WorkflowNode.workspace_id == workspace_id, WorkflowNode.version_id == version_id
        )
    ):
        loaded.nodes[n.node_key] = LoadedNode(n.node_key, n.type, n.label, dict(n.config or {}))
    for e in db.scalars(
        select(WorkflowEdge).where(
            WorkflowEdge.workspace_id == workspace_id, WorkflowEdge.version_id == version_id
        )
    ):
        loaded.edges[(e.source_key, e.branch or "next")] = e.target_key
    return loaded


def _parse(node: LoadedNode) -> BaseModel:
    spec = catalog.NODE_SPECS.get(node.type)
    if spec is None:
        raise StepFailure("validation")
    try:
        return spec.model.model_validate(node.config)
    except ValidationError:
        raise StepFailure("validation") from None


# ----------------------------------------------------------------------------- starting runs


@dataclass
class StartResult:
    run: WorkflowRun | None
    created: bool
    skipped: str | None = (
        None  # why an event did not start a run (duplicate_event, subject_busy, ...)
    )


def _subject_exists(
    db: Session, workspace_id: uuid.UUID, subject_type: str, subject_id: uuid.UUID
) -> bool:
    if subject_type == "lead":
        return (
            db.scalar(
                select(Lead.id).where(
                    Lead.id == subject_id,
                    Lead.workspace_id == workspace_id,
                    Lead.archived_at.is_(None),
                )
            )
            is not None
        )
    return (
        db.scalar(
            select(Conversation.id).where(
                Conversation.id == subject_id, Conversation.workspace_id == workspace_id
            )
        )
        is not None
    )


def latest_version(db: Session, workflow: Workflow) -> WorkflowVersion | None:
    return db.scalar(
        select(WorkflowVersion)
        .where(
            WorkflowVersion.workspace_id == workflow.workspace_id,
            WorkflowVersion.workflow_id == workflow.id,
        )
        .order_by(WorkflowVersion.version.desc())
        .limit(1)
    )


def active_version_row(db: Session, workflow: Workflow) -> WorkflowVersion | None:
    if workflow.active_version is None:
        return None
    return db.scalar(
        select(WorkflowVersion).where(
            WorkflowVersion.workspace_id == workflow.workspace_id,
            WorkflowVersion.workflow_id == workflow.id,
            WorkflowVersion.version == workflow.active_version,
        )
    )


def _check_limits(db: Session, settings: Settings, workspace_id: uuid.UUID, now: datetime) -> None:
    active = db.scalar(
        select(func.count())
        .select_from(WorkflowRun)
        .where(WorkflowRun.workspace_id == workspace_id, WorkflowRun.status.in_(ACTIVE_STATUSES))
    )
    if (active or 0) >= settings.workflow_max_active_runs:
        raise AppError(
            429,
            "workflow_limit_reached",
            "This workspace has too many workflow runs in progress. Wait for some to finish.",
        )
    today = db.scalar(
        select(func.count())
        .select_from(WorkflowRun)
        .where(
            WorkflowRun.workspace_id == workspace_id,
            WorkflowRun.created_at >= now - timedelta(hours=24),
        )
    )
    if (today or 0) >= settings.workflow_max_runs_per_day:
        raise AppError(
            429,
            "workflow_limit_reached",
            "This workspace reached its limit of workflow runs for today.",
        )


def start_run(
    db: Session,
    settings: Settings,
    workflow: Workflow,
    *,
    trigger_type: str,
    subject_type: str,
    subject_id: uuid.UUID,
    idempotency_key: str,
    now: datetime,
    started_by_user_id: uuid.UUID | None,
    event: bool,
) -> StartResult:
    """Create a queued run. ``event=True`` (automatic triggers) skips quietly where a manual start would be refused."""
    wid = workflow.workspace_id
    if workflow.status == "archived":
        raise AppError(409, "workflow_archived", "This workflow is archived.")
    if workflow.status == "active":
        version = active_version_row(db, workflow)
        mode = workflow.mode
    else:
        if event:
            return StartResult(None, False, "not_active")
        version = latest_version(db, workflow)
        mode = "test"  # a workflow that has not been switched on can only be tried out in test mode
    if version is None or not version.valid:
        if event:
            return StartResult(None, False, "invalid_version")
        raise AppError(
            409,
            "workflow_invalid",
            "This workflow has problems that must be fixed before it can run.",
        )
    if version.trigger_event is None:
        raise AppError(409, "workflow_invalid", "This workflow has no trigger.")
    if event and version.trigger_event != trigger_type:
        return StartResult(None, False, "other_trigger")

    expected = catalog.EVENT_SUBJECT.get(version.trigger_event)
    if expected is not None and subject_type != expected:
        raise AppError(422, "wrong_subject", f"This workflow starts from a {expected}.")
    if not _subject_exists(db, wid, subject_type, subject_id):
        if event:
            return StartResult(None, False, "subject_missing")
        raise AppError(404, f"{subject_type}_not_found", f"The {subject_type} was not found.")

    existing = db.scalar(
        select(WorkflowRun).where(
            WorkflowRun.workspace_id == wid,
            WorkflowRun.workflow_id == workflow.id,
            WorkflowRun.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return StartResult(existing, False, "duplicate_event")

    busy = db.scalar(
        select(WorkflowRun.id)
        .where(
            WorkflowRun.workspace_id == wid,
            WorkflowRun.workflow_id == workflow.id,
            WorkflowRun.subject_id == subject_id,
            WorkflowRun.status.in_(ACTIVE_STATUSES),
        )
        .limit(1)
    )
    if busy is not None:
        if event:
            return StartResult(None, False, "subject_busy")
        raise AppError(
            409,
            "run_in_progress",
            "This workflow is already running for that item. Wait for it to finish.",
        )
    try:
        _check_limits(db, settings, wid, now)
    except AppError:
        if event:
            return StartResult(None, False, "limit_reached")
        raise

    loaded = load_version(db, wid, version.id)
    trigger = next((n for n in loaded.nodes.values() if n.type == "trigger"), None)
    if trigger is None:
        raise AppError(409, "workflow_invalid", "This workflow has no trigger.")
    run = WorkflowRun(
        workspace_id=wid,
        workflow_id=workflow.id,
        version_id=version.id,
        status="queued",
        mode=mode,
        trigger_type=trigger_type,
        trigger_payload={"event": trigger_type, "subject_type": subject_type},
        idempotency_key=idempotency_key,
        correlation_id=uuid.uuid4().hex,
        subject_type=subject_type,
        subject_id=subject_id,
        current_node_key=trigger.key,
        context={f"{subject_type}_id": str(subject_id)},
        started_by_user_id=started_by_user_id,
    )
    try:
        with db.begin_nested():
            db.add(run)
            db.flush()
    except IntegrityError:
        # Two copies of the same event raced; the unique key decided which one won.
        winner = db.scalar(
            select(WorkflowRun).where(
                WorkflowRun.workspace_id == wid,
                WorkflowRun.workflow_id == workflow.id,
                WorkflowRun.idempotency_key == idempotency_key,
            )
        )
        if winner is None:
            raise
        return StartResult(winner, False, "duplicate_event")
    audit.record(
        db,
        "workflow.run_started",
        actor_user_id=started_by_user_id,
        workspace_id=wid,
        target_type="workflow_run",
        target_id=str(run.id),
        details={"workflow_id": str(workflow.id), "trigger": trigger_type, "mode": mode},
    )
    return StartResult(run, True)


# ----------------------------------------------------------------------------- claiming


def claim_runs(
    db: Session, now: datetime, limit: int, workspace_id: uuid.UUID | None = None
) -> list[tuple[uuid.UUID, str]]:
    """Atomically take up to ``limit`` due runs. Commits. Returns ``(run_id, lock_token)`` pairs."""
    due = or_(
        and_(
            WorkflowRun.status == "queued",
            or_(WorkflowRun.wake_at.is_(None), WorkflowRun.wake_at <= now),
        ),
        and_(WorkflowRun.status == "waiting_delay", WorkflowRun.wake_at <= now),
        and_(WorkflowRun.status == "running", WorkflowRun.locked_until < now),
    )
    stmt = (
        select(WorkflowRun.id, WorkflowRun.status)
        .where(due)
        .order_by(func.coalesce(WorkflowRun.wake_at, WorkflowRun.created_at), WorkflowRun.id)
        .limit(limit)
    )
    if workspace_id is not None:
        stmt = stmt.where(WorkflowRun.workspace_id == workspace_id)
    claimed: list[tuple[uuid.UUID, str]] = []
    for run_id, status in db.execute(stmt).all():
        token = uuid.uuid4().hex
        result = db.execute(
            update(WorkflowRun)
            .where(WorkflowRun.id == run_id, WorkflowRun.status == status, due)
            .values(
                status="running",
                locked_until=now + LEASE,
                lock_token=token,
                started_at=func.coalesce(WorkflowRun.started_at, now),
                wake_at=None,
            )
        )
        if result.rowcount == 1:  # type: ignore[attr-defined]
            claimed.append((run_id, token))
    db.commit()
    return claimed


def _heartbeat(db: Session, run_id: uuid.UUID, token: str, now: datetime) -> bool:
    """Keep the lease. False means another worker owns the run now (ours expired): stop touching it."""
    result = db.execute(
        update(WorkflowRun)
        .where(
            WorkflowRun.id == run_id,
            WorkflowRun.lock_token == token,
            WorkflowRun.status == "running",
        )
        .values(locked_until=now + LEASE)
    )
    db.commit()
    return bool(result.rowcount == 1)  # type: ignore[attr-defined]


# ----------------------------------------------------------------------------- finishing a run


def _release(run: WorkflowRun) -> None:
    run.locked_until = None
    run.lock_token = None


def _cancel_open_approvals(db: Session, run: WorkflowRun, reason: str) -> None:
    for approval in db.scalars(
        select(ApprovalRequest).where(
            ApprovalRequest.workspace_id == run.workspace_id,
            ApprovalRequest.run_id == run.id,
            ApprovalRequest.status == "pending",
        )
    ):
        approval.status = "cancelled"
        approval.invalidated_reason = reason
        _revert_draft(db, approval)


def _revert_draft(db: Session, approval: ApprovalRequest) -> None:
    from app.db.models_email import Draft

    if approval.draft_id is None:
        return
    draft = db_get_scoped(db, Draft, approval.workspace_id, approval.draft_id)
    if draft is not None and draft.status == "pending_approval":
        draft.status = "draft"


def finish_cancelled(db: Session, run: WorkflowRun, now: datetime) -> None:
    run.status = "cancelled"
    run.finished_at = now
    run.wake_at = None
    _release(run)
    for step in db.scalars(
        select(WorkflowStepRun).where(
            WorkflowStepRun.workspace_id == run.workspace_id,
            WorkflowStepRun.run_id == run.id,
            WorkflowStepRun.status.in_(("waiting", "running", "pending")),
        )
    ):
        step.status = "cancelled"
        step.finished_at = now
    _cancel_open_approvals(db, run, "run_cancelled")
    audit.record(
        db,
        "workflow.run_cancelled",
        workspace_id=run.workspace_id,
        target_type="workflow_run",
        target_id=str(run.id),
        details={"workflow_id": str(run.workflow_id)},
    )


def _finish_succeeded(db: Session, run: WorkflowRun, now: datetime) -> None:
    run.status = "succeeded"
    run.finished_at = now
    run.wake_at = None
    run.error_category = None
    run.error_summary = None
    _release(run)
    audit.record(
        db,
        "workflow.run_finished",
        workspace_id=run.workspace_id,
        target_type="workflow_run",
        target_id=str(run.id),
        details={"workflow_id": str(run.workflow_id), "status": "succeeded"},
    )


def _fail_run(db: Session, run: WorkflowRun, category: str, summary: str, now: datetime) -> None:
    run.status = "failed"
    run.finished_at = now
    run.wake_at = None
    run.error_category = category
    run.error_summary = summary[:500]
    _release(run)
    _cancel_open_approvals(db, run, "run_failed")
    audit.record(
        db,
        "workflow.run_finished",
        workspace_id=run.workspace_id,
        target_type="workflow_run",
        target_id=str(run.id),
        details={
            "workflow_id": str(run.workflow_id),
            "status": "failed",
            "category": category,
            "node": run.current_node_key,
        },
    )
    if category != "ended_as_failure":
        name = (
            db.scalar(select(Workflow.name).where(Workflow.id == run.workflow_id)) or "A workflow"
        )
        notify_owners(
            db,
            run.workspace_id,
            kind="workflow_failed",
            title=f"{name[:120]} did not finish",
            body=summary[:300],
            link=f"/automations?run={run.id}",
            dedupe_key=f"run:{run.id}:failed",
        )


# ----------------------------------------------------------------------------- one step


def _handle_failure(
    db: Session,
    run: WorkflowRun,
    node: LoadedNode,
    step: WorkflowStepRun,
    failure: StepFailure,
    attempts_allowed: int,
    now: datetime,
) -> str:
    step.status = "failed"
    step.finished_at = now
    step.error_category = failure.category
    step.error_summary = failure.summary
    used = step.attempt - run.attempt_floor
    if failure.retryable and used < attempts_allowed:
        wait = failure.retry_after or BACKOFF_SECONDS[min(used - 1, len(BACKOFF_SECONDS) - 1)]
        wait = max(1, min(int(wait), 3600))
        step.next_attempt_at = now + timedelta(seconds=wait)
        run.status = "queued"
        run.wake_at = step.next_attempt_at
        _release(run)
        return "stop"
    _fail_run(db, run, failure.category, failure.summary, now)
    return "stop"


def _apply_advance(
    db: Session,
    run: WorkflowRun,
    node: LoadedNode,
    step: WorkflowStepRun,
    loaded: LoadedVersion,
    result: Advance,
    now: datetime,
) -> str:
    step.status = "succeeded"
    step.finished_at = now
    step.port = result.port
    step.output_summary = safe_summary(result.output)
    context = dict(run.context or {})
    context.update(result.context)
    if node.type == "ai_draft":  # a new draft needs its own approval
        context.pop("approved_draft_id", None)
        context.pop("approval_id", None)
    run.context = context
    target = loaded.edges.get((node.key, result.port))
    if target is None or target not in loaded.nodes:
        _fail_run(db, run, "validation", CATEGORIES["validation"][0], now)
        return "stop"
    run.current_node_key = target
    run.steps_taken += 1
    run.attempt_floor = 0
    if run.steps_taken >= MAX_STEPS_PER_RUN:
        _fail_run(db, run, "limit_exceeded", "The run took too many steps.", now)
        return "stop"
    return "continue"


def _apply_result(
    db: Session,
    run: WorkflowRun,
    node: LoadedNode,
    step: WorkflowStepRun,
    loaded: LoadedVersion,
    result: object,
    now: datetime,
) -> str:
    if isinstance(result, Advance):
        return _apply_advance(db, run, node, step, loaded, result, now)
    if isinstance(result, WaitDelay):
        step.status = "waiting"
        step.output_summary = safe_summary(result.output)
        run.status = "waiting_delay"
        run.wake_at = result.wake_at
        _release(run)
        return "stop"
    if isinstance(result, WaitApproval):
        step.status = "waiting"
        step.output_summary = safe_summary(result.output)
        run.status = "waiting_approval"
        run.wake_at = None
        _release(run)
        return "stop"
    assert isinstance(result, Finish)
    step.status = "succeeded"
    step.finished_at = now
    step.output_summary = safe_summary(result.output)
    run.steps_taken += 1
    if result.outcome == "success":
        _finish_succeeded(db, run, now)
    else:
        _fail_run(
            db,
            run,
            "ended_as_failure",
            (result.reason or CATEGORIES["ended_as_failure"][0])[:500],
            now,
        )
    return "stop"


def _attempts_allowed(node: LoadedNode, cfg: BaseModel | None) -> int:
    if cfg is None or node.type not in catalog.NODE_SPECS:
        return 1
    return catalog.default_attempts(node.type, cfg)


def _step_env(
    db: Session,
    run: WorkflowRun,
    step: WorkflowStepRun,
    node: LoadedNode,
    cfg: BaseModel,
    deps: EngineDeps,
    now: datetime,
) -> StepEnv:
    return StepEnv(
        db=db,
        run=run,
        step=step,
        node_key=node.key,
        node_type=node.type,
        cfg=cfg,
        attempt=step.attempt,
        ctx=owner_context(db, run.workspace_id),
        deps=deps,
        now=now,
        mode=run.mode,
        timeout_seconds=catalog.default_timeout(node.type, cfg),
    )


def _execute_step(db: Session, run_id: uuid.UUID, loaded: LoadedVersion, deps: EngineDeps) -> str:
    """Run (or resume) the run's current node. Returns "continue" or "stop". Commits."""
    now = deps.now()
    run = db.get(WorkflowRun, run_id)
    assert run is not None
    node = loaded.nodes.get(run.current_node_key or "")
    if node is None:
        _fail_run(db, run, "validation", CATEGORIES["validation"][0], now)
        db.commit()
        return "stop"
    latest = db.scalar(
        select(WorkflowStepRun)
        .where(
            WorkflowStepRun.workspace_id == run.workspace_id,
            WorkflowStepRun.run_id == run.id,
            WorkflowStepRun.node_key == node.key,
        )
        .order_by(WorkflowStepRun.attempt.desc())
        .limit(1)
    )

    if latest is not None and latest.status == "waiting":
        return _resume(db, run, node, latest, loaded, deps, now)

    if latest is not None and latest.status == "running":
        # A worker died while this step was running. Whether it finished its effect is unknown, so it is treated as a
        # failed attempt: the executors are idempotent (or refuse to repeat an unconfirmed send).
        cfg: BaseModel | None
        try:
            cfg = _parse(node)
        except StepFailure:
            cfg = None
        outcome = _handle_failure(
            db, run, node, latest, StepFailure("interrupted"), _attempts_allowed(node, cfg), now
        )
        db.commit()
        return outcome

    attempt = (latest.attempt + 1) if latest is not None else 1
    step = WorkflowStepRun(
        workspace_id=run.workspace_id,
        run_id=run.id,
        node_key=node.key,
        attempt=attempt,
        status="running",
        started_at=now,
        idempotency_key=f"{run.id.hex}:{node.key}:{attempt}"[:200],
        input_summary={"node_type": node.type, "mode": run.mode},
    )
    db.add(step)
    db.commit()  # the step exists durably before anything happens
    step_id = step.id

    def reload() -> tuple[WorkflowRun, WorkflowStepRun]:
        fresh_run = db.get(WorkflowRun, run_id)
        fresh_step = db.get(WorkflowStepRun, step_id)
        assert fresh_run is not None and fresh_step is not None
        return fresh_run, fresh_step

    failure: StepFailure | None = None
    result: object = None
    cfg_model: BaseModel | None = None
    started = time.monotonic()
    try:
        cfg_model = _parse(node)
        run, step = reload()
        env = _step_env(db, run, step, node, cfg_model, deps, now)
        result = EXECUTORS[node.type](env)
    except StepFailure as exc:
        failure = exc
    except AppError as exc:
        failure = from_app_error(exc)
    except Exception as exc:
        logger.warning(
            "workflow_step_error type=%s run=%s node=%s", type(exc).__name__, run_id, node.type
        )
        failure = StepFailure("internal")
    elapsed = time.monotonic() - started

    if failure is not None:
        db.rollback()  # whatever the executor had written is discarded; the step row was committed before
        run, step = reload()
        outcome = _handle_failure(
            db, run, node, step, failure, _attempts_allowed(node, cfg_model), deps.now()
        )
        db.commit()
        return outcome

    run, step = reload()
    if cfg_model is not None and elapsed > catalog.default_timeout(node.type, cfg_model):
        logger.warning("workflow_step_slow run=%s node=%s seconds=%.1f", run_id, node.type, elapsed)
        if isinstance(result, Advance):
            result.output["slow"] = True
    outcome = _apply_result(db, run, node, step, loaded, result, deps.now())
    db.commit()
    return outcome


def _resume(
    db: Session,
    run: WorkflowRun,
    node: LoadedNode,
    step: WorkflowStepRun,
    loaded: LoadedVersion,
    deps: EngineDeps,
    now: datetime,
) -> str:
    cfg: BaseModel | None = None
    try:
        cfg = _parse(node)
        result: Advance
        if node.type == "delay":
            result = Advance(output={"waited": True})
        elif node.type == "approval_gate":
            approval = db.scalar(
                select(ApprovalRequest).where(
                    ApprovalRequest.workspace_id == run.workspace_id,
                    ApprovalRequest.step_run_id == step.id,
                )
            )
            if approval is None:
                raise StepFailure("validation")
            if approval.status == "pending":
                # Not decided: put it back to sleep (a worker should not have been given this run).
                run.status = "waiting_approval"
                _release(run)
                db.commit()
                return "stop"
            resumed = resume_approval(_step_env(db, run, step, node, cfg, deps, now), approval)
            assert isinstance(resumed, Advance)
            result = resumed
        else:
            raise StepFailure("validation")
    except StepFailure as failure:
        outcome = _handle_failure(db, run, node, step, failure, _attempts_allowed(node, cfg), now)
        db.commit()
        return outcome
    outcome = _apply_advance(db, run, node, step, loaded, result, now)
    db.commit()
    return outcome


# ----------------------------------------------------------------------------- the worker


@dataclass
class BatchStats:
    claimed: int = 0
    finished: int = 0
    waiting: int = 0
    requeued: int = 0
    lost_lease: int = 0
    errors: int = 0
    approvals_expired: int = 0


def process_run(
    session_factory: sessionmaker[Session],
    deps: EngineDeps,
    run_id: uuid.UUID,
    token: str,
    stats: BatchStats,
) -> None:
    loaded: LoadedVersion | None = None
    for _ in range(MAX_STEPS_PER_CLAIM):
        with session_factory() as db:
            if not _heartbeat(db, run_id, token, deps.now()):
                stats.lost_lease += 1
                return
            run = db.get(WorkflowRun, run_id)
            if run is None:
                return
            if run.cancel_requested_at is not None:
                finish_cancelled(db, run, deps.now())
                db.commit()
                stats.finished += 1
                return
            if loaded is None:
                loaded = load_version(db, run.workspace_id, run.version_id)
            try:
                outcome = _execute_step(db, run_id, loaded, deps)
            except Exception:
                db.rollback()
                raise
            run = db.get(WorkflowRun, run_id)
            status = run.status if run is not None else "failed"
            if (
                run is not None
                and run.cancel_requested_at is not None
                and run.status not in TERMINAL_STATUSES
            ):
                # A cancel arrived while the step ran and the run moved on to wait: honour it now.
                finish_cancelled(db, run, deps.now())
                db.commit()
                status = "cancelled"
                outcome = "stop"
        if outcome == "stop":
            if status in TERMINAL_STATUSES:
                stats.finished += 1
            elif status == "queued":
                stats.requeued += 1
            else:
                stats.waiting += 1
            return
    # Used this claim's step budget: give the run back so others get a turn.
    with session_factory() as db:
        db.execute(
            update(WorkflowRun)
            .where(WorkflowRun.id == run_id, WorkflowRun.lock_token == token)
            .values(status="queued", wake_at=None, locked_until=None, lock_token=None)
        )
        db.commit()
    stats.requeued += 1


def process_batch(
    session_factory: sessionmaker[Session],
    deps: EngineDeps,
    *,
    limit: int = 10,
    workspace_id: uuid.UUID | None = None,
) -> BatchStats:
    from app.workflows import approvals

    stats = BatchStats()
    with session_factory() as db:
        stats.approvals_expired = approvals.expire_due(db, deps.now())
        db.commit()
        claimed = claim_runs(db, deps.now(), limit, workspace_id)
    stats.claimed = len(claimed)
    for run_id, token in claimed:
        try:
            process_run(session_factory, deps, run_id, token, stats)
        except Exception as exc:  # the lease expires and the run is picked up again
            stats.errors += 1
            logger.warning("workflow_run_error type=%s run=%s", type(exc).__name__, run_id)
    return stats


def run_worker(app: Any, *, limit: int = 10, workspace_id: uuid.UUID | None = None) -> BatchStats:
    """Process due runs with the running application's providers (used by background tasks and the CLI)."""
    from app.db.session import get_sessionmaker
    from app.workflows.runtime import deps_from_app

    return process_batch(
        get_sessionmaker(), deps_from_app(app), limit=limit, workspace_id=workspace_id
    )


# ----------------------------------------------------------------------------- cancel and retry (called by services)


def request_cancel(db: Session, run: WorkflowRun, now: datetime) -> str:
    """Cancel now if nothing is executing; otherwise ask the worker to stop before its next step."""
    if run.status in TERMINAL_STATUSES:
        if run.status == "cancelled":
            return "cancelled"
        raise AppError(409, "run_finished", "This run has already finished.")
    if run.status == "running":
        run.cancel_requested_at = now
        return "cancelling"
    finish_cancelled(db, run, now)
    return "cancelled"


def _send_unresolved(db: Session, run: WorkflowRun) -> bool:
    """True while the draft this run was sending still has an unconfirmed send nobody has resolved."""
    from app.db.models_email import Draft
    from app.services import drafts as draft_service

    draft_id = run.context.get("draft_id") if run.context else None
    try:
        parsed = uuid.UUID(str(draft_id)) if draft_id else None
    except ValueError:
        parsed = None
    draft = db_get_scoped(db, Draft, run.workspace_id, parsed)
    if draft is None:
        return False
    message = draft_service.get_message(db, run.workspace_id, draft.id)
    return message is not None and message.delivery_state in ("unknown", "queued")


def retry_failed(db: Session, run: WorkflowRun, now: datetime) -> WorkflowStepRun:
    """Manual retry of the failed step. A send whose outcome is unknown is never retried blindly."""
    if run.status != "failed":
        raise AppError(409, "not_retryable", "Only a failed run can be retried.")
    step = db.scalar(
        select(WorkflowStepRun)
        .where(
            WorkflowStepRun.workspace_id == run.workspace_id,
            WorkflowStepRun.run_id == run.id,
            WorkflowStepRun.node_key == run.current_node_key,
        )
        .order_by(WorkflowStepRun.attempt.desc())
        .limit(1)
    )
    if step is None or step.status != "failed" or step.error_category is None:
        raise AppError(409, "not_retryable", "This run did not fail on a step that can be retried.")
    if step.error_category == "outcome_unknown" and _send_unresolved(db, run):
        raise AppError(
            409,
            "resolve_send_first",
            "The mail provider never confirmed this message. Check your mailbox and mark the draft as sent or not sent, "
            "then retry.",
        )
    if step.error_category == "ended_as_failure":
        raise AppError(409, "not_retryable", "The workflow ended as a failure by design.")
    run.status = "queued"
    run.finished_at = None
    run.error_category = None
    run.error_summary = None
    run.wake_at = None
    run.cancel_requested_at = None
    run.attempt_floor = step.attempt
    _release(run)
    audit.record(
        db,
        "workflow.run_retried",
        workspace_id=run.workspace_id,
        target_type="workflow_run",
        target_id=str(run.id),
        details={"workflow_id": str(run.workflow_id), "node": run.current_node_key},
    )
    return step


def aware(value: datetime | None) -> datetime | None:
    return as_utc(value) if value is not None else None
