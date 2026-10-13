"""In-app notifications, including "task due" and "task reminder".

Until a background job runner exists (MVP Prompt 11), due notifications are produced lazily when notifications are read.
Producing is idempotent: each (task, kind, due/remind instant) has a dedupe key, so reading ten times notifies once,
and rescheduling a task gives it a fresh notification for the new time.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.clock import utcnow
from app.db.models_crm import Task
from app.db.models_workflow import Notification
from app.deps import WorkspaceContext
from app.services.times import as_utc, zone

LOOKBACK = timedelta(days=14)
MAX_PER_SYNC = 50


def task_key(task_id: uuid.UUID, kind: str, instant_epoch: int) -> str:
    return f"task:{task_id}:{kind}:{instant_epoch}"


def _link(task: Task) -> str:
    return "/tasks"


def _local(task: Task, value) -> str:  # type: ignore[no-untyped-def]
    try:
        tz = zone(task.due_timezone)
    except ValueError:
        tz = zone("UTC")
    local = as_utc(value).astimezone(tz)
    return f"{local:%Y-%m-%d %H:%M} ({task.due_timezone or 'UTC'})"


def sync_task_notifications(db: DbSession, ctx: WorkspaceContext) -> int:
    """Create notifications for tasks whose reminder or due time has arrived. Returns how many were new."""
    now = utcnow()
    since = now - LOOKBACK
    wid, uid = ctx.workspace_id, ctx.user.id
    tasks = list(
        db.scalars(
            select(Task)
            .where(
                Task.workspace_id == wid,
                Task.status == "open",
                or_(Task.assignee_user_id == uid, Task.assignee_user_id.is_(None)),
                or_(
                    and_(Task.due_at.is_not(None), Task.due_at <= now, Task.due_at >= since),
                    and_(
                        Task.remind_at.is_not(None), Task.remind_at <= now, Task.remind_at >= since
                    ),
                ),
            )
            .order_by(Task.due_at.desc(), Task.id)  # the most recently due matter most
            .limit(MAX_PER_SYNC)
        )
    )
    candidates: dict[str, Notification] = {}
    for t in tasks:
        if t.remind_at is not None and since <= as_utc(t.remind_at) <= now:
            key = task_key(t.id, "remind", int(as_utc(t.remind_at).timestamp()))
            candidates[key] = Notification(
                workspace_id=wid,
                user_id=uid,
                kind="task_reminder",
                title=f"Reminder: {t.title}"[:200],
                body=f"Due {_local(t, t.due_at)}" if t.due_at else None,
                link=_link(t),
                dedupe_key=key,
            )
        if t.due_at is not None and since <= as_utc(t.due_at) <= now:
            key = task_key(t.id, "due", int(as_utc(t.due_at).timestamp()))
            candidates[key] = Notification(
                workspace_id=wid,
                user_id=uid,
                kind="task_due",
                title=f"Due: {t.title}"[:200],
                body=f"Was due {_local(t, t.due_at)}",
                link=_link(t),
                dedupe_key=key,
            )
    if not candidates:
        return 0
    known = set(
        db.scalars(
            select(Notification.dedupe_key).where(
                Notification.user_id == uid, Notification.dedupe_key.in_(list(candidates))
            )
        )
    )
    created = 0
    for key, note in candidates.items():
        if key in known:
            continue
        try:
            with db.begin_nested():
                db.add(note)
                db.flush()
            created += 1
        except IntegrityError:
            pass  # a concurrent read produced it first
    db.commit()
    return created


def settle_task(db: DbSession, ctx: WorkspaceContext, task_id: uuid.UUID) -> None:
    """A task was completed, dismissed or rescheduled: its pending notifications no longer need attention."""
    db.execute(
        update(Notification)
        .where(
            Notification.workspace_id == ctx.workspace_id,
            Notification.user_id == ctx.user.id,
            Notification.read_at.is_(None),
            Notification.dedupe_key.like(f"task:{task_id}:%"),
        )
        .values(read_at=utcnow())
    )


def unread_count(db: DbSession, ctx: WorkspaceContext) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.workspace_id == ctx.workspace_id,
                Notification.user_id == ctx.user.id,
                Notification.read_at.is_(None),
            )
        )
        or 0
    )
