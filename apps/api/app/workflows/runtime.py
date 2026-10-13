"""What an executor is given and what it may return."""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.db.models import Membership, User, Workspace
from app.db.models_workflow import WorkflowRun, WorkflowStepRun
from app.deps import WorkspaceContext
from app.workflows.errors import StepFailure

if TYPE_CHECKING:
    from fastapi import FastAPI

    from app.ai.service import AiService
    from app.config import Settings
    from app.mailbox.registry import ConnectorRegistry
    from app.ratelimit import RateLimiter
    from app.security.credentials import CredentialStore

ACTIVE_STATUSES = ("queued", "running", "waiting_approval", "waiting_delay")
TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")


@dataclass
class EngineDeps:
    """Everything the engine needs from the running application (the same objects the API uses)."""

    settings: Settings
    ai_for: Callable[[uuid.UUID, int], AiService]
    store: CredentialStore
    registry: ConnectorRegistry
    limiter: RateLimiter
    now: Callable[[], datetime] = utcnow


def deps_from_app(app: FastAPI) -> EngineDeps:
    from app.ai.service import AiLimits, AiService
    from app.config import get_settings

    settings = get_settings()
    base = AiLimits.from_settings(settings)

    def ai_for(workspace_id: uuid.UUID, budget_seconds: int) -> AiService:
        # A node's timeout bounds the whole AI call, retries included.
        limits = replace(
            base,
            total_budget_seconds=min(base.total_budget_seconds, float(budget_seconds)),
            timeout_seconds=min(base.timeout_seconds, float(budget_seconds)),
        )
        return AiService(
            app.state.ai_provider,
            limits,
            workspace_id=workspace_id,
            limiter=app.state.rate_limiter,
        )

    return EngineDeps(
        settings=settings,
        ai_for=ai_for,
        store=app.state.credentials,
        registry=app.state.mailbox,
        limiter=app.state.rate_limiter,
    )


# ----------------------------------------------------------------------------- step results


@dataclass
class Advance:
    """The step is done: leave through ``port`` and remember ``context``."""

    port: str = "next"
    output: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class WaitDelay:
    wake_at: datetime
    output: dict[str, Any] = field(default_factory=dict)


@dataclass
class WaitApproval:
    approval_id: uuid.UUID
    output: dict[str, Any] = field(default_factory=dict)


@dataclass
class Finish:
    outcome: Literal["success", "failure"]
    reason: str | None = None
    output: dict[str, Any] = field(default_factory=dict)


StepResult = Advance | WaitDelay | WaitApproval | Finish


@dataclass
class StepEnv:
    db: Session
    run: WorkflowRun
    step: WorkflowStepRun
    node_key: str
    node_type: str
    cfg: BaseModel
    attempt: int
    ctx: WorkspaceContext
    deps: EngineDeps
    now: datetime
    mode: str
    timeout_seconds: int

    @property
    def workspace_id(self) -> uuid.UUID:
        return self.run.workspace_id

    @property
    def simulated(self) -> bool:
        return self.mode != "live"

    def node_hash(self) -> str:
        return hashlib.sha1(self.node_key.encode()).hexdigest()[:8]  # noqa: S324 - not security relevant

    def effect_key(self) -> str:
        """Stable for this run and node (not per attempt): what an idempotent side effect is keyed on."""
        return f"wf-{self.run.id.hex}-{self.node_hash()}"

    def send_key_prefix(self) -> str:
        return f"wf-{self.run.id.hex[:24]}-{self.node_hash()}-"


# ----------------------------------------------------------------------------- helpers

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def safe_summary(value: dict[str, Any]) -> dict[str, Any]:
    """Reduce a step's output to what is safe to store and show: short scalars and short lists of them.

    Executors only put ids, counts and enumerations here already; this is the second line of defence, so an executor
    that gets careless still cannot store a long text, a nested structure or an object.
    """

    def scalar(v: Any) -> Any:
        if v is None or isinstance(v, (bool, int, float)):
            return v
        if isinstance(v, str):
            return _CONTROL.sub(" ", v)[:120]
        return None

    out: dict[str, Any] = {}
    for key, v in list(value.items())[:20]:
        name = str(key)[:40]
        if isinstance(v, (list, tuple)):
            out[name] = [scalar(i) for i in v[:10]]
        else:
            out[name] = scalar(v)
    return out


def owner_context(db: Session, workspace_id: uuid.UUID) -> WorkspaceContext:
    """The identity runs act as: the workspace owner. Without one, nothing runs."""
    row = db.execute(
        select(Membership, User, Workspace)
        .join(User, User.id == Membership.user_id)
        .join(Workspace, Workspace.id == Membership.workspace_id)
        .where(Membership.workspace_id == workspace_id, Membership.role == "owner")
        .order_by(Membership.created_at, Membership.id)
        .limit(1)
    ).first()
    if row is None:
        raise StepFailure("no_owner")
    membership, user, workspace = row
    return WorkspaceContext(user=user, workspace=workspace, membership=membership)
