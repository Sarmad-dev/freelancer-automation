"""Small helpers shared by workspace-scoped routers."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy import Select
from sqlalchemy.orm import Session as DbSession

from app import audit
from app.config import Settings
from app.deps import WorkspaceContext
from app.errors import ErrorResponse

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


def like_pattern(text: str) -> str:
    """Case-insensitive 'contains' pattern with LIKE wildcards in the user's text matched literally."""
    needle = text.casefold().replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    return f"%{needle}%"


def audit_event(
    db: DbSession,
    ctx: WorkspaceContext,
    request: Request,
    settings: Settings,
    action: str,
    target_type: str,
    target_id: object | None = None,
    **details: Any,
) -> None:
    audit.record(
        db,
        action,
        info=audit.request_info(request, settings),
        actor_user_id=ctx.user.id,
        workspace_id=ctx.workspace_id,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        details=details,
    )


def archive_filter(stmt: Select[Any], model: Any, mode: str) -> Select[Any]:
    if mode == "active":
        return stmt.where(model.archived_at.is_(None))
    if mode == "archived":
        return stmt.where(model.archived_at.is_not(None))
    return stmt


def sample_filter(stmt: Select[Any], model: Any, mode: str | None) -> Select[Any]:
    if mode == "only":
        return stmt.where(model.is_sample.is_(True))
    if mode == "exclude":
        return stmt.where(model.is_sample.is_(False))
    return stmt
