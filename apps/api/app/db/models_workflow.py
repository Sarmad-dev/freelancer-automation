"""Workflow definitions and executions, approvals, usage accounting and notifications.

A workflow version is an immutable snapshot (rows in ``workflow_nodes``/``workflow_edges``) so a run stays
pinned to the definition it started with. Runs and step runs record execution state durably; secrets and
message content are never stored here (only redacted summaries).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app import domain
from app.clock import utcnow
from app.db.base import Base
from app.db.mixins import TenantMixin, Timestamps, check_in, pk_column, tenant_fk


class Workflow(TenantMixin, Timestamps, Base):
    __tablename__ = "workflows"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_workflows_workspace_id_id"),
        check_in("status", domain.WORKFLOW_STATUSES),
        check_in("mode", domain.WORKFLOW_MODES),
        Index("ix_workflows_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000))
    # New workflows start in draft + test mode; going live is an explicit, audited action.
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="draft")
    mode: Mapped[str] = mapped_column(String(10), nullable=False, default="test")
    active_version: Mapped[int | None] = mapped_column(Integer)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )


class WorkflowVersion(TenantMixin, Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_workflow_versions_workspace_id_id"),
        UniqueConstraint("workflow_id", "id", name="uq_workflow_versions_workflow_id_id"),
        UniqueConstraint("workflow_id", "version", name="uq_workflow_versions_workflow_version"),
        CheckConstraint("version >= 1", name="version_positive"),
        tenant_fk("workflow_versions", "workflow_id", "workflows", ondelete="CASCADE"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    workflow_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Integrity check over the canonical node/edge content of this version.
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str | None] = mapped_column(String(300))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class WorkflowNode(TenantMixin, Base):
    __tablename__ = "workflow_nodes"
    __table_args__ = (
        UniqueConstraint("version_id", "node_key", name="uq_workflow_nodes_version_key"),
        tenant_fk("workflow_nodes", "version_id", "workflow_versions", ondelete="CASCADE"),
        Index("ix_workflow_nodes_workspace_type", "workspace_id", "type"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    version_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    node_key: Mapped[str] = mapped_column(String(80), nullable=False)
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    label: Mapped[str | None] = mapped_column(String(120))
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    position_x: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    position_y: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class WorkflowEdge(TenantMixin, Base):
    __tablename__ = "workflow_edges"
    __table_args__ = (
        UniqueConstraint("version_id", "edge_key", name="uq_workflow_edges_version_key"),
        tenant_fk("workflow_edges", "version_id", "workflow_versions", ondelete="CASCADE"),
        # Endpoints must be nodes of the same version.
        ForeignKeyConstraint(
            ["version_id", "source_key"],
            ["workflow_nodes.version_id", "workflow_nodes.node_key"],
            name="fk_workflow_edges_source_workflow_nodes",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["version_id", "target_key"],
            ["workflow_nodes.version_id", "workflow_nodes.node_key"],
            name="fk_workflow_edges_target_workflow_nodes",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = pk_column()
    version_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    edge_key: Mapped[str] = mapped_column(String(80), nullable=False)
    source_key: Mapped[str] = mapped_column(String(80), nullable=False)
    target_key: Mapped[str] = mapped_column(String(80), nullable=False)
    branch: Mapped[str | None] = mapped_column(String(60))


class WorkflowRun(TenantMixin, Timestamps, Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_workflow_runs_workspace_id_id"),
        # Event de-duplication: the same trigger event cannot start a workflow twice.
        UniqueConstraint(
            "workspace_id", "workflow_id", "idempotency_key", name="uq_workflow_runs_event"
        ),
        check_in("status", domain.RUN_STATUSES),
        check_in("mode", domain.WORKFLOW_MODES),
        tenant_fk("workflow_runs", "workflow_id", "workflows", ondelete="CASCADE"),
        tenant_fk("workflow_runs", "version_id", "workflow_versions"),
        # The pinned version must belong to the run's workflow.
        ForeignKeyConstraint(
            ["workflow_id", "version_id"],
            ["workflow_versions.workflow_id", "workflow_versions.id"],
            name="fk_workflow_runs_version_belongs_to_workflow",
        ),
        Index("ix_workflow_runs_workspace_status", "workspace_id", "status"),
        Index(
            "ix_workflow_runs_workspace_workflow_started",
            "workspace_id",
            "workflow_id",
            "started_at",
        ),
        Index("ix_workflow_runs_correlation", "correlation_id"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    workflow_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    mode: Mapped[str] = mapped_column(String(10), nullable=False, default="test")
    trigger_type: Mapped[str] = mapped_column(String(40), nullable=False)
    # Redacted trigger payload (no message bodies, no secrets).
    trigger_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    wake_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_category: Mapped[str | None] = mapped_column(String(40))
    error_summary: Mapped[str | None] = mapped_column(String(500))


class WorkflowStepRun(TenantMixin, Timestamps, Base):
    __tablename__ = "workflow_step_runs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_workflow_step_runs_workspace_id_id"),
        UniqueConstraint("run_id", "node_key", "attempt", name="uq_workflow_step_runs_attempt"),
        # A side effect with the same idempotency key can only be recorded once per workspace.
        UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_workflow_step_runs_idempotency"
        ),
        check_in("status", domain.STEP_STATUSES),
        CheckConstraint("attempt >= 1", name="attempt_positive"),
        tenant_fk("workflow_step_runs", "run_id", "workflow_runs", ondelete="CASCADE"),
        Index("ix_workflow_step_runs_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    node_key: Mapped[str] = mapped_column(String(80), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    input_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    output_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_category: Mapped[str | None] = mapped_column(String(40))
    error_summary: Mapped[str | None] = mapped_column(String(500))


class ApprovalRequest(TenantMixin, Timestamps, Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_approval_requests_workspace_id_id"),
        check_in("status", domain.APPROVAL_STATUSES),
        tenant_fk("approval_requests", "run_id", "workflow_runs", ondelete="CASCADE"),
        tenant_fk("approval_requests", "step_run_id", "workflow_step_runs", ondelete="CASCADE"),
        tenant_fk("approval_requests", "draft_id", "drafts", ondelete="CASCADE"),
        Index(
            "ix_approval_requests_workspace_status_expires", "workspace_id", "status", "expires_at"
        ),
    )

    id: Mapped[uuid.UUID] = pk_column()
    run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    step_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    draft_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(64))
    # Approval is bound to the exact proposed action: if this hash changes, approval is void.
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    proposed_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="pending")
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(String(500))
    invalidated_reason: Mapped[str | None] = mapped_column(String(200))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UsageRecord(TenantMixin, Base):
    """Metering for AI calls and other billable/limited actions. Never stores prompts or content."""

    __tablename__ = "usage_records"
    __table_args__ = (
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0", name="input_tokens_non_negative"
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0", name="output_tokens_non_negative"
        ),
        Index("ix_usage_records_workspace_time", "workspace_id", "occurred_at"),
        Index("ix_usage_records_workspace_kind_time", "workspace_id", "kind", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(80))
    task_type: Mapped[str | None] = mapped_column(String(40))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    # Estimated cost in millionths of a currency unit (integer: no float rounding in sums).
    estimated_cost_micros: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_mock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class Notification(TenantMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        # Producers (e.g. "task due") can retry without notifying twice.
        UniqueConstraint("user_id", "dedupe_key", name="uq_notifications_user_dedupe"),
        Index("ix_notifications_workspace_user_read", "workspace_id", "user_id", "read_at"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(String(500))
    link: Mapped[str | None] = mapped_column(String(300))
    dedupe_key: Mapped[str | None] = mapped_column(String(120))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
