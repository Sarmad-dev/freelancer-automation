"""Tasks: creation (idempotent), editing, state changes, reminders and the Today / Upcoming / Overdue views."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.clock import utcnow
from app.db.models_crm import Lead, Opportunity, Task
from app.db.models_email import Conversation
from app.deps import WorkspaceContext
from app.errors import AppError
from app.schemas.tasks import (
    TaskCreate,
    TaskLeadRef,
    TaskOpportunityRef,
    TaskOut,
    TaskPatch,
    TaskReschedule,
    TaskSnooze,
    TaskSummary,
)
from app.services import crm
from app.services import leads as lead_svc
from app.services import notifications as notification_svc
from app.services.times import DEFAULT_ZONE, as_utc, day_bounds, to_utc, zone


def _invalid(field: str, message: str) -> AppError:
    return AppError(422, "validation_error", "Some fields are invalid.", fields={field: message})


def default_zone(db: DbSession, ctx: WorkspaceContext) -> str:
    """The workspace's time zone (set in onboarding): what "today" means unless the person says otherwise."""
    return ctx.workspace.timezone or DEFAULT_ZONE


def view_zone(db: DbSession, ctx: WorkspaceContext, requested: str | None) -> str:
    if requested:
        try:
            zone(requested)
        except ValueError as exc:
            raise _invalid("tz", "Use an IANA time zone such as Europe/Berlin.") from exc
        return requested
    return default_zone(db, ctx)


def _instant(value: datetime, tz_name: str, field: str) -> datetime:
    try:
        return to_utc(value, tz_name)
    except ValueError as exc:
        raise _invalid(field, str(exc)) from exc


# ---------------------------------------------------------------- links
def _resolve_links(
    db: DbSession,
    ctx: WorkspaceContext,
    lead_id: uuid.UUID | None,
    opportunity_id: uuid.UUID | None,
    conversation_id: uuid.UUID | None,
) -> tuple[uuid.UUID | None, uuid.UUID | None, uuid.UUID | None]:
    """Validate every link against the workspace and fill in the lead a deal or conversation belongs to."""
    wid = ctx.workspace_id
    if opportunity_id is not None:
        opp = db.scalar(
            select(Opportunity).where(
                Opportunity.workspace_id == wid, Opportunity.id == opportunity_id
            )
        )
        if opp is None:
            raise crm.invalid_ref("opportunity_id", "Opportunity")
        if lead_id is not None and lead_id != opp.lead_id:
            raise _invalid("lead_id", "That deal belongs to a different lead.")
        lead_id = opp.lead_id
    if conversation_id is not None:
        convo = db.scalar(
            select(Conversation).where(
                Conversation.workspace_id == wid, Conversation.id == conversation_id
            )
        )
        if convo is None:
            raise crm.invalid_ref("conversation_id", "Conversation")
        if lead_id is None:
            lead_id = convo.lead_id
        elif convo.lead_id is not None and convo.lead_id != lead_id:
            raise _invalid("conversation_id", "That conversation belongs to a different lead.")
    if lead_id is not None:
        lead = db.scalar(select(Lead).where(Lead.workspace_id == wid, Lead.id == lead_id))
        if lead is None:
            raise crm.invalid_ref("lead_id", "Lead")
    return lead_id, opportunity_id, conversation_id


# ---------------------------------------------------------------- create / edit
def _fingerprint(t: Task) -> tuple[Any, ...]:
    return (
        t.title,
        t.lead_id,
        t.opportunity_id,
        t.conversation_id,
        as_utc(t.due_at) if t.due_at else None,
    )


def _existing_by_key(db: DbSession, ctx: WorkspaceContext, key: str) -> Task | None:
    return db.scalar(
        select(Task).where(Task.workspace_id == ctx.workspace_id, Task.idempotency_key == key)
    )


def _same_request(existing: Task, candidate: Task) -> Task:
    if _fingerprint(existing) != _fingerprint(candidate):
        raise AppError(
            409,
            "idempotency_conflict",
            "That submission key was already used for a different task.",
        )
    return existing


def create_task(db: DbSession, ctx: WorkspaceContext, body: TaskCreate) -> tuple[Task, bool]:
    """Create a task. Returns ``(task, created)``: a repeated idempotency key returns the first task."""
    tz = body.due_timezone or default_zone(db, ctx)
    lead_id, opportunity_id, conversation_id = _resolve_links(
        db, ctx, body.lead_id, body.opportunity_id, body.conversation_id
    )
    due = _instant(body.due_at, tz, "due_at") if body.due_at else None
    remind = _instant(body.remind_at, tz, "remind_at") if body.remind_at else None
    if due and remind and remind > due:
        raise _invalid("remind_at", "The reminder must not be after the due time.")
    task = Task(
        workspace_id=ctx.workspace_id,
        title=body.title,
        description=body.description,
        priority=body.priority,
        due_at=due,
        due_timezone=tz if (due or remind) else None,
        remind_at=remind,
        assignee_user_id=ctx.user.id,
        lead_id=lead_id,
        opportunity_id=opportunity_id,
        conversation_id=conversation_id,
        created_by="user",
        idempotency_key=body.idempotency_key,
    )
    if body.idempotency_key:
        existing = _existing_by_key(db, ctx, body.idempotency_key)
        if existing is not None:
            return _same_request(existing, task), False
    try:
        with db.begin_nested():
            db.add(task)
            db.flush()
    except IntegrityError:
        # Two identical submissions raced; the database's unique key decided which one won.
        existing = _existing_by_key(db, ctx, body.idempotency_key or "")
        if existing is None:
            raise
        return _same_request(existing, task), False
    _log(db, ctx, task, "Task created")
    return task, True


def _log(db: DbSession, ctx: WorkspaceContext, task: Task, verb: str) -> None:
    if task.lead_id is None:
        return
    lead = db.get(Lead, task.lead_id)
    if lead is None:
        return
    lead_svc.add_activity(
        db,
        ctx,
        lead,
        "task",
        f"{verb}: {task.title}"[:500],
        opportunity_id=task.opportunity_id,
        details={"task_id": str(task.id), "status": task.status},
    )


def update_task(db: DbSession, ctx: WorkspaceContext, task: Task, body: TaskPatch) -> list[str]:
    changes = body.model_dump(exclude_unset=True)
    for required in ("title", "priority"):
        if required in changes and changes[required] is None:
            changes.pop(required)
    tz = changes.pop("due_timezone", None) or task.due_timezone or default_zone(db, ctx)
    due_before = task.due_at
    if "due_at" in changes:
        value = changes.pop("due_at")
        task.due_at = _instant(value, tz, "due_at") if value else None
    if "remind_at" in changes:
        value = changes.pop("remind_at")
        task.remind_at = _instant(value, tz, "remind_at") if value else None
    for name, value in changes.items():
        setattr(task, name, value)
    if task.due_at and task.remind_at and as_utc(task.remind_at) > as_utc(task.due_at):
        raise _invalid("remind_at", "The reminder must not be after the due time.")
    task.due_timezone = tz if (task.due_at or task.remind_at) else None
    if due_before != task.due_at:
        notification_svc.settle_task(db, ctx, task.id)
    db.flush()
    return sorted(set(body.model_fields_set))


def reschedule_task(db: DbSession, ctx: WorkspaceContext, task: Task, body: TaskReschedule) -> Task:
    tz = body.due_timezone or task.due_timezone or default_zone(db, ctx)
    new_due = _instant(body.due_at, tz, "due_at")
    if task.due_at is not None and task.remind_at is not None:
        # Keep the same lead time: a reminder 1 hour before stays 1 hour before.
        task.remind_at = new_due - (as_utc(task.due_at) - as_utc(task.remind_at))
    elif task.remind_at is not None and as_utc(task.remind_at) > new_due:
        task.remind_at = new_due
    task.due_at, task.due_timezone = new_due, tz
    if task.status != "open":
        task.status, task.completed_at = "open", None
    notification_svc.settle_task(db, ctx, task.id)
    db.flush()
    return task


def snooze_task(db: DbSession, ctx: WorkspaceContext, task: Task, body: TaskSnooze) -> Task:
    tz = body.due_timezone or task.due_timezone or default_zone(db, ctx)
    remind = _instant(body.remind_at, tz, "remind_at")
    if task.due_at is not None and remind > as_utc(task.due_at):
        raise _invalid("remind_at", "The reminder must not be after the due time.")
    task.remind_at, task.due_timezone = remind, task.due_timezone or tz
    notification_svc.settle_task(db, ctx, task.id)
    db.flush()
    return task


def complete_task(db: DbSession, ctx: WorkspaceContext, task: Task) -> bool:
    if task.status == "done":
        return False
    task.status, task.completed_at = "done", utcnow()
    notification_svc.settle_task(db, ctx, task.id)
    _log(db, ctx, task, "Task completed")
    db.flush()
    return True


def dismiss_task(db: DbSession, ctx: WorkspaceContext, task: Task) -> bool:
    if task.status == "dismissed":
        return False
    task.status, task.completed_at = "dismissed", None
    notification_svc.settle_task(db, ctx, task.id)
    db.flush()
    return True


def reopen_task(db: DbSession, ctx: WorkspaceContext, task: Task) -> bool:
    if task.status == "open":
        return False
    task.status, task.completed_at = "open", None
    db.flush()
    return True


# ---------------------------------------------------------------- views
def view_filter(stmt: Select[Any], view: str, now: datetime, tz_name: str) -> Select[Any]:
    """Disjoint buckets: overdue = already past due; today = still due before local midnight; upcoming = later."""
    _, end = day_bounds(now, tz_name)
    if view == "open":
        return stmt.where(Task.status == "open")
    if view == "overdue":
        return stmt.where(Task.status == "open", Task.due_at < now)
    if view == "today":
        return stmt.where(Task.status == "open", Task.due_at >= now, Task.due_at < end)
    if view == "upcoming":
        return stmt.where(Task.status == "open", Task.due_at >= end)
    if view == "undated":
        return stmt.where(Task.status == "open", Task.due_at.is_(None))
    if view == "done":
        return stmt.where(Task.status == "done")
    if view == "dismissed":
        return stmt.where(Task.status == "dismissed")
    return stmt


def summary(db: DbSession, ctx: WorkspaceContext, tz_name: str) -> TaskSummary:
    now = utcnow()

    def count(view: str) -> int:
        stmt = select(func.count()).select_from(Task).where(Task.workspace_id == ctx.workspace_id)
        return int(db.scalar(view_filter(stmt, view, now, tz_name)) or 0)

    return TaskSummary(
        timezone=tz_name,
        overdue=count("overdue"),
        today=count("today"),
        upcoming=count("upcoming"),
        undated=count("undated"),
        done=count("done"),
    )


# ---------------------------------------------------------------- serialisation
def task_outs(db: DbSession, ctx: WorkspaceContext, tasks: Sequence[Task]) -> list[TaskOut]:
    if not tasks:
        return []
    wid = ctx.workspace_id
    lead_ids = {t.lead_id for t in tasks if t.lead_id}
    opp_ids = {t.opportunity_id for t in tasks if t.opportunity_id}
    leads = (
        {
            r[0]: r[1]
            for r in db.execute(
                select(Lead.id, Lead.title).where(Lead.workspace_id == wid, Lead.id.in_(lead_ids))
            )
        }
        if lead_ids
        else {}
    )
    opps = (
        {
            r[0]: r[1]
            for r in db.execute(
                select(Opportunity.id, Opportunity.title).where(
                    Opportunity.workspace_id == wid, Opportunity.id.in_(opp_ids)
                )
            )
        }
        if opp_ids
        else {}
    )
    now = utcnow()
    return [
        TaskOut(
            id=t.id,
            title=t.title,
            description=t.description,
            status=t.status,
            priority=t.priority,
            due_at=t.due_at,
            due_timezone=t.due_timezone,
            remind_at=t.remind_at,
            completed_at=t.completed_at,
            assignee_user_id=t.assignee_user_id,
            lead=TaskLeadRef(id=t.lead_id, title=leads[t.lead_id])
            if t.lead_id and t.lead_id in leads
            else None,
            opportunity=TaskOpportunityRef(id=t.opportunity_id, title=opps[t.opportunity_id])
            if t.opportunity_id and t.opportunity_id in opps
            else None,
            conversation_id=t.conversation_id,
            created_by=t.created_by,
            is_sample=t.is_sample,
            is_overdue=t.status == "open" and t.due_at is not None and as_utc(t.due_at) < now,
            created_at=t.created_at,
            updated_at=t.updated_at,
        )
        for t in tasks
    ]
