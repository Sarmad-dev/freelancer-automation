"""List-endpoint conventions: limit/offset pagination, allow-listed sorting, one response shape.

Every list endpoint returns ``{"items": [...], "total": N, "limit": L, "offset": O}``. Query params:
``limit`` (1-100, default 25), ``offset`` (>= 0), ``sort`` (comma-separated, ``-`` prefix = descending,
only fields the endpoint allow-lists). Results are always ordered deterministically (a unique tie-breaker
is appended) so pages never overlap or skip rows.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import ColumnElement, Select, SQLColumnExpression, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.errors import AppError

MAX_LIMIT = 100
DEFAULT_LIMIT = 25
MAX_OFFSET = 100_000
MAX_SORT_FIELDS = 3


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class PageParams:
    limit: int
    offset: int
    sort: str | None


def page_params(
    limit: Annotated[
        int, Query(ge=1, le=MAX_LIMIT, description="Page size (1-100).")
    ] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0, le=MAX_OFFSET, description="Rows to skip.")] = 0,
    sort: Annotated[
        str | None,
        Query(max_length=100, description="Comma-separated fields; prefix '-' for descending."),
    ] = None,
) -> PageParams:
    return PageParams(limit=limit, offset=offset, sort=sort)


def parse_sort(
    sort: str | None, allowed: Mapping[str, SQLColumnExpression[Any]], default: str
) -> list[ColumnElement[Any]]:
    """Translate ``"-created_at,name"`` into ORDER BY expressions, rejecting anything not allow-listed."""
    spec = (sort or default).strip()
    parts = [p.strip() for p in spec.split(",") if p.strip()]
    if not parts or len(parts) > MAX_SORT_FIELDS:
        raise AppError(
            422,
            "validation_error",
            "Some fields are invalid.",
            fields={"sort": f"Use 1-{MAX_SORT_FIELDS} comma-separated fields."},
        )
    clauses: list[ColumnElement[Any]] = []
    for part in parts:
        descending = part.startswith("-")
        name = part.lstrip("-+")
        column = allowed.get(name)
        if column is None:
            raise AppError(
                422,
                "validation_error",
                "Some fields are invalid.",
                fields={"sort": f"Cannot sort by '{name}'. Allowed: {', '.join(sorted(allowed))}."},
            )
        # NULLs always last, so SQLite and PostgreSQL order unscored/undated rows the same way.
        clauses.append(column.desc().nulls_last() if descending else column.asc().nulls_last())
    return clauses


def paginate(
    db: Session,
    stmt: Select,  # type: ignore[type-arg]
    params: PageParams,
    *,
    allowed_sort: Mapping[str, SQLColumnExpression[Any]],
    default_sort: str,
    tie_breaker: InstrumentedAttribute[Any],
) -> tuple[list, int]:  # type: ignore[type-arg]
    """Run ``stmt`` (already filtered and workspace-scoped) and return ``(rows, total)``."""
    order = parse_sort(params.sort, allowed_sort, default_sort)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(
        stmt.order_by(*order, tie_breaker.asc()).limit(params.limit).offset(params.offset)
    ).all()
    return list(rows), int(total)
