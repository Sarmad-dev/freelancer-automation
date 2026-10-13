"""The signed-in person's in-app notifications (MVP Prompt 7)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, update

from app.api.pagination import Page, PageParams, page_params, paginate
from app.clock import utcnow
from app.db.models_workflow import Notification
from app.deps import DbDep, WorkspaceDep
from app.errors import AppError
from app.routers._common import ERRORS
from app.schemas.tasks import MarkAllResult, NotificationCount, NotificationOut
from app.services import notifications as svc

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/notifications", tags=["notifications"])


def _own(ctx: WorkspaceDep):  # type: ignore[no-untyped-def]
    return (Notification.workspace_id == ctx.workspace_id, Notification.user_id == ctx.user.id)


def _out(n: Notification) -> NotificationOut:
    link = n.link if n.link and n.link.startswith("/") and not n.link.startswith("//") else None
    return NotificationOut(
        id=n.id,
        kind=n.kind,
        title=n.title,
        body=n.body,
        link=link,
        read_at=n.read_at,
        created_at=n.created_at,
    )


@router.get(
    "",
    response_model=Page[NotificationOut],
    responses=ERRORS,
    summary="Your notifications (newest first)",
)
def list_notifications(
    ctx: WorkspaceDep,
    db: DbDep,
    params: Annotated[PageParams, Depends(page_params)],
    unread: Annotated[bool, Query(description="Only unread notifications.")] = False,
) -> Page[NotificationOut]:
    svc.sync_task_notifications(db, ctx)
    stmt = select(Notification).where(*_own(ctx))
    if unread:
        stmt = stmt.where(Notification.read_at.is_(None))
    rows, total = paginate(
        db,
        stmt,
        params,
        allowed_sort={"created_at": Notification.created_at},
        default_sort="-created_at",
        tie_breaker=Notification.id,
    )
    return Page[NotificationOut](
        items=[_out(n) for n in rows], total=total, limit=params.limit, offset=params.offset
    )


@router.get(
    "/unread-count",
    response_model=NotificationCount,
    responses=ERRORS,
    summary="How many notifications are unread (also produces any task notifications that have come due)",
)
def unread_count(ctx: WorkspaceDep, db: DbDep) -> NotificationCount:
    svc.sync_task_notifications(db, ctx)
    return NotificationCount(unread=svc.unread_count(db, ctx))


@router.post(
    "/read-all", response_model=MarkAllResult, responses=ERRORS, summary="Mark all as read"
)
def read_all(ctx: WorkspaceDep, db: DbDep) -> MarkAllResult:
    result = db.execute(
        update(Notification)
        .where(*_own(ctx), Notification.read_at.is_(None))
        .values(read_at=utcnow())
    )
    db.commit()
    return MarkAllResult(marked=int(result.rowcount or 0))  # type: ignore[attr-defined]


@router.post(
    "/{notification_id}/read",
    response_model=NotificationOut,
    responses=ERRORS,
    summary="Mark one as read",
)
def read_one(notification_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep) -> NotificationOut:
    note = db.scalar(select(Notification).where(*_own(ctx), Notification.id == notification_id))
    if note is None:
        raise AppError(404, "notification_not_found", "Notification not found.")
    if note.read_at is None:
        note.read_at = utcnow()
        db.commit()
    return _out(note)
