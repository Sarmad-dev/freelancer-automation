"""Workflow API shapes (MVP Prompt 11)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.workflows.definition import WorkflowDefinition

RunStatus = Literal[
    "queued", "running", "waiting_approval", "waiting_delay", "succeeded", "failed", "cancelled"
]
StepStatus = Literal["pending", "running", "succeeded", "failed", "skipped", "waiting", "cancelled"]
ApprovalStatus = Literal["pending", "approved", "rejected", "expired", "cancelled", "invalidated"]
WorkflowStatus = Literal["draft", "active", "paused", "archived"]
Mode = Literal["test", "live"]
SubjectType = Literal["lead", "conversation"]


class IssueOut(BaseModel):
    code: str
    message: str
    node_id: str | None = None
    edge_id: str | None = None
    field: str | None = None


class ValidationOut(BaseModel):
    valid: bool
    issues: list[IssueOut]
    trigger_event: str | None = None


class ValidateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: WorkflowDefinition


# ----------------------------------------------------------------------------- catalogue


class NodeTypeOut(BaseModel):
    type: str
    label: str
    description: str
    ports: list[str]
    side_effect: bool = Field(
        description="Changes records or leaves the system; simulated in test mode."
    )
    default_max_attempts: int
    default_timeout_seconds: int
    config_schema: dict[str, Any] = Field(description="JSON Schema of this node's settings.")


class ConditionFieldOut(BaseModel):
    field: str
    label: str
    kind: Literal["enum", "string", "number", "bool"]
    values: list[str]
    ops: list[str]


class CatalogOut(BaseModel):
    nodes: list[NodeTypeOut]
    trigger_events: list[str]
    condition_fields: list[ConditionFieldOut]
    placeholders: list[str]
    max_nodes: int
    max_edges: int


# ----------------------------------------------------------------------------- workflows and versions


class VersionSummary(BaseModel):
    version: int
    valid: bool
    issue_count: int
    trigger_event: str | None
    note: str | None
    created_at: datetime
    active: bool


class WorkflowSummary(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    status: WorkflowStatus
    mode: Mode
    active_version: int | None
    latest_version: int | None
    latest_valid: bool
    trigger_event: str | None
    runs_in_progress: int
    created_at: datetime
    updated_at: datetime


class VersionOut(BaseModel):
    version: int
    valid: bool
    issues: list[IssueOut]
    trigger_event: str | None
    note: str | None
    created_at: datetime
    active: bool
    definition: WorkflowDefinition


class WorkflowDetail(WorkflowSummary):
    latest: VersionOut | None
    versions: list[VersionSummary]


class WorkflowCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1_000)
    definition: WorkflowDefinition | None = None


class WorkflowPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1_000)


class VersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: WorkflowDefinition
    note: str | None = Field(default=None, max_length=300)


class ActivateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int | None = Field(default=None, ge=1, description="Defaults to the latest version.")


class ModeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Mode
    confirm: bool = Field(
        default=False,
        description="Must be true to go live: live runs change records and can send approved email.",
    )


# ----------------------------------------------------------------------------- runs and approvals


class RunStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_type: SubjectType
    subject_id: uuid.UUID
    idempotency_key: str | None = Field(
        default=None,
        min_length=8,
        max_length=100,
        pattern=r"^[A-Za-z0-9._:-]+$",
        description="Send the same key to retry safely: the same run comes back instead of a duplicate.",
    )


class StepRunOut(BaseModel):
    id: uuid.UUID
    node_key: str
    node_type: str | None
    node_label: str | None
    attempt: int
    status: StepStatus
    port: str | None
    started_at: datetime | None
    finished_at: datetime | None
    next_attempt_at: datetime | None
    output_summary: dict[str, Any]
    error_category: str | None
    error_summary: str | None


class ApprovalOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID | None
    workflow_id: uuid.UUID | None
    workflow_name: str | None
    kind: str
    status: ApprovalStatus
    mode: str | None
    summary: str | None
    draft_id: uuid.UUID | None
    target_type: str | None
    target_id: str | None
    expires_at: datetime | None
    decided_at: datetime | None
    decision_note: str | None
    invalidated_reason: str | None
    created_at: datetime


class RunSummary(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    workflow_name: str | None
    version: int | None
    status: RunStatus
    mode: Mode
    trigger_type: str
    subject_type: SubjectType | None
    subject_id: uuid.UUID | None
    current_node_key: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    wake_at: datetime | None
    error_category: str | None
    error_summary: str | None
    cancel_requested: bool
    correlation_id: str


class RunDetail(RunSummary):
    steps: list[StepRunOut]
    approvals: list[ApprovalOut]
    context: dict[str, Any]


class StartRunOut(BaseModel):
    run: RunSummary
    created: bool = Field(description="False when the idempotency key matched an earlier run.")


class CancelOut(BaseModel):
    status: Literal["cancelled", "cancelling"]
    run: RunSummary


class DecideIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=500)
