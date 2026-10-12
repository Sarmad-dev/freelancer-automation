"""Workspace scoping helpers. Every query for tenant data must go through these (or filter by
``ctx.workspace_id`` explicitly): the workspace comes from the authorised context, never from the client."""

from __future__ import annotations

import uuid
from typing import TypeVar

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.deps import WorkspaceContext
from app.errors import AppError

M = TypeVar("M")


def scoped_select[M](model: type[M], ctx: WorkspaceContext) -> Select[tuple[M]]:
    return select(model).where(model.workspace_id == ctx.workspace_id)  # type: ignore[attr-defined]


def get_scoped_or_404[M](
    db: Session,
    model: type[M],
    ctx: WorkspaceContext,
    object_id: uuid.UUID,
    *,
    code: str,
    message: str,
) -> M:
    """Fetch by id within the workspace; foreign and missing ids are indistinguishable (404)."""
    row = db.scalar(scoped_select(model, ctx).where(model.id == object_id))  # type: ignore[attr-defined]
    if row is None:
        raise AppError(404, code, message)
    return row
