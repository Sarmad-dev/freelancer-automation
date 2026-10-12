"""Shared column mixins and constraint helpers for ORM models."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Uuid
from sqlalchemy.orm import Mapped, MappedColumn, mapped_column

from app.clock import utcnow


def new_uuid() -> uuid.UUID:
    """Primary keys are random UUIDv4: unguessable in URLs and safe to generate client-side or in workers."""
    return uuid.uuid4()


def pk_column() -> MappedColumn[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=new_uuid)


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class TenantMixin:
    """Marks a tenant-owned table. Deleting the workspace deletes every row (cascade)."""

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )


def tenant_fk(
    table: str, column: str, target: str, *, ondelete: str | None = None
) -> ForeignKeyConstraint:
    """Composite foreign key ``(workspace_id, <column>) -> target(workspace_id, id)``.

    The database itself then refuses a reference to a row that belongs to a different workspace, so a
    bug in application code cannot link, say, a lead to another tenant's company. Targets must declare
    ``UniqueConstraint("workspace_id", "id")``. When ``<column>`` is NULL the constraint is not checked
    (standard MATCH SIMPLE behaviour), so optional relations work as expected.
    """
    return ForeignKeyConstraint(
        ["workspace_id", column],
        [f"{target}.workspace_id", f"{target}.id"],
        name=f"fk_{table}_{column}_{target}",
        ondelete=ondelete,
    )


def check_in(column: str, values: tuple[str, ...], name: str | None = None) -> CheckConstraint:
    allowed = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({allowed})", name=name or column)
