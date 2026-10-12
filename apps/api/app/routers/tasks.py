"""Tasks and follow-ups: list by view, create (idempotent), edit, complete / reopen / dismiss, reschedule, snooze."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.pagination import Page, PageParams, page_params, paginate
from app.api.scoping import get_scoped_or_404, scoped_select
from app.clock import utcnow
from app.db.models_crm import Task
from app.deps import DbDep, SettingsDep, WorkspaceContext, WorkspaceDep, require_owner
from app.routers._common import ERRORS, audit_event, like_pattern
from app.schemas.tasks import (
    Priority,
    TaskCreate,
    TaskOut,
    TaskPatch,
    TaskReschedule,
    TaskSnooze,
    TaskSummary,
    TaskView,
)
from app.services import tasks as svc

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/tasks", tags=["tasks"])

_SORT = {
    "due_at": Task.due_at,
    "created_at": Task.created_at,
    "completed_at": Task.completed_at,
    "title": func.lower(Task.title),
    "priority": Task.priority,
}


def _get(db: DbDep, ctx: WorkspaceDep, task_id: uuid.UUID) -> Task:
    return get_scoped_or_404(
        db, Task, ctx, task_id, code="task_not_found", message="Task not found."
    )


def _out(db: DbDep, ctx: WorkspaceDep, task: Task) -> TaskOut:
    return svc.task_outs(db, ctx, [task])[0]


@router.get("", response_model=Page[TaskOut], responses=ERRORS, summary="List tasks by view")
def list_tasks(
    ctx: WorkspaceDep,
    db: DbDep,
    params: Annotated[PageParams, Depends(page_params)],
    view: Annotated[
        TaskView,
        Query(
            description="overdue = open and past due; today = open and due before local midnight; "
            "upcoming = open and due later; undated = open, no due date; done; dismissed; open = all open.",
        ),
    ] = "open",
    tz: Annotated[
        str | None,
        Query(
            max_length=64,
            description="IANA zone that defines 'today'. Defaults to the workspace's.",
        ),
    ] = None,
    lead_id: Annotated[uuid.UUID | None, Query()] = None,
    opportunity_id: Annotated[uuid.UUID | None, Query()] = None,
    conversation_id: Annotated[uuid.UUID | None, Query()] = None,
    priority: Annotated[Priority | None, Query()] = None,
    q: Annotated[
        str | None, Query(max_length=100, description="Title or description contains.")
    ] = None,
) -> Page[TaskOut]:
    zone_name = svc.view_zone(db, ctx, tz)
    stmt = svc.view_filter(scoped_select(Task, ctx), view, utcnow(), zone_name)
    if lead_id:
        stmt = stmt.where(Task.lead_id == lead_id)
    if opportunity_id:
        stmt = stmt.where(Task.opportunity_id == opportunity_id)
    if conversation_id:
        stmt = stmt.where(Task.conversation_id == conversation_id)
    if priority:
        stmt = stmt.where(Task.priority == priority)
    if q:
        like = like_pattern(q)
        stmt = stmt.where(
            or_(
                func.lower(Task.title).like(like, escape="\\"),
                func.lower(func.coalesce(Task.description, "")).like(like, escape="\\"),
            )
        )
    rows, total = paginate(
        db,
        stmt,
        params,
        allowed_sort=_SORT,
        default_sort="-completed_at" if view == "done" else "due_at",
        tie_breaker=Task.id,
    )
    return Page[TaskOut](
        items=svc.task_outs(db, ctx, rows), total=total, limit=params.limit, offset=params.offset
    )


@router.get(
    "/summary",
    response_model=TaskSummary,
    responses=ERRORS,
    summary="How many tasks are overdue, due today, upcoming, undated and done",
)
def task_summary(
    ctx: WorkspaceDep,
    db: DbDep,
    tz: Annotated[str | None, Query(max_length=64)] = None,
) -> TaskSummary:
    return svc.summary(db, ctx, svc.view_zone(db, ctx, tz))


@router.post(
    "",
    response_model=TaskOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        **ERRORS,
        200: {
            "model": TaskOut,
            "description": "The idempotency key was already used: the original task.",
        },
    },
    summary="Create a task (send an idempotency_key so a double submit can't create two)",
)
def create_task(
    body: TaskCreate,
    response: Response,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
) -> TaskOut:
    require_owner(ctx)
    task, created = svc.create_task(db, ctx, body)
    if created:
        audit_event(db, ctx, request, settings, "tasks.created", "task", task.id)
        db.commit()
    else:
        response.status_code = status.HTTP_200_OK
    return _out(db, ctx, task)


@router.get("/{task_id}", response_model=TaskOut, responses=ERRORS, summary="Get a task")
def get_task(task_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep) -> TaskOut:
    return _out(db, ctx, _get(db, ctx, task_id))


@router.patch("/{task_id}", response_model=TaskOut, responses=ERRORS, summary="Edit a task")
def update_task(
    task_id: uuid.UUID,
    body: TaskPatch,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
) -> TaskOut:
    require_owner(ctx)
    task = _get(db, ctx, task_id)
    fields = svc.update_task(db, ctx, task, body)
    audit_event(db, ctx, request, settings, "tasks.updated", "task", task.id, fields=fields)
    db.commit()
    return _out(db, ctx, task)


def _action(
    verb: str,
    task_id: uuid.UUID,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
    fn: Callable[[Session, WorkspaceContext, Task], bool],
) -> TaskOut:
    require_owner(ctx)
    task = _get(db, ctx, task_id)
    if fn(db, ctx, task):
        audit_event(db, ctx, request, settings, f"tasks.{verb}", "task", task.id)
    db.commit()
    return _out(db, ctx, task)


@router.post(
    "/{task_id}/complete", response_model=TaskOut, responses=ERRORS, summary="Mark a task done"
)
def complete_task(
    task_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> TaskOut:
    return _action("completed", task_id, ctx, db, request, settings, svc.complete_task)


@router.post(
    "/{task_id}/dismiss",
    response_model=TaskOut,
    responses=ERRORS,
    summary="Dismiss a task (not needed any more)",
)
def dismiss_task(
    task_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> TaskOut:
    return _action("dismissed", task_id, ctx, db, request, settings, svc.dismiss_task)


@router.post(
    "/{task_id}/reopen",
    response_model=TaskOut,
    responses=ERRORS,
    summary="Reopen a done or dismissed task",
)
def reopen_task(
    task_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> TaskOut:
    return _action("reopened", task_id, ctx, db, request, settings, svc.reopen_task)


@router.post(
    "/{task_id}/reschedule",
    response_model=TaskOut,
    responses=ERRORS,
    summary="Move the due time (a reminder keeps its lead time; a done task is reopened)",
)
def reschedule_task(
    task_id: uuid.UUID,
    body: TaskReschedule,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
) -> TaskOut:
    require_owner(ctx)
    task = svc.reschedule_task(db, ctx, _get(db, ctx, task_id), body)
    audit_event(db, ctx, request, settings, "tasks.rescheduled", "task", task.id)
    db.commit()
    return _out(db, ctx, task)


@router.post(
    "/{task_id}/snooze", response_model=TaskOut, responses=ERRORS, summary="Set a new reminder time"
)
def snooze_task(
    task_id: uuid.UUID,
    body: TaskSnooze,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
) -> TaskOut:
    require_owner(ctx)
    task = svc.snooze_task(db, ctx, _get(db, ctx, task_id), body)
    audit_event(db, ctx, request, settings, "tasks.snoozed", "task", task.id)
    db.commit()
    return _out(db, ctx, task)
