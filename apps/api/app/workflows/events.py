"""Starting workflows from things that happen in the app (a lead is created, a reply arrives, a follow-up is due).

``emit`` finds the *active* workflows listening to an event and queues a run for each. It is safe to call twice for the
same occurrence: the idempotency key (event + a token that identifies the occurrence, like a message id) means the same
event cannot start a workflow twice, and a workflow already running for the same lead or conversation is not started
again. It never raises into the caller: a workflow problem must not break creating a lead or syncing mail.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models_workflow import Workflow

logger = logging.getLogger("freelancer_os.workflows")


def emit(
    db: Session,
    settings: Settings,
    workspace_id: uuid.UUID,
    event: str,
    subject_type: str,
    subject_id: uuid.UUID,
    token: str,
    now: datetime,
) -> list[uuid.UUID]:
    """Queue a run for every active workflow that listens to ``event``. Returns the ids of runs that were created."""
    from app.workflows.engine import (
        start_run,
    )  # imported here: the engine imports services that call ``emit``

    created: list[uuid.UUID] = []
    workflows = list(
        db.scalars(
            select(Workflow).where(
                Workflow.workspace_id == workspace_id,
                Workflow.status == "active",
                Workflow.trigger_event == event,
            )
        )
    )
    for workflow in workflows:
        try:
            with db.begin_nested():
                result = start_run(
                    db,
                    settings,
                    workflow,
                    trigger_type=event,
                    subject_type=subject_type,
                    subject_id=subject_id,
                    idempotency_key=f"{event}:{token}"[:200],
                    now=now,
                    started_by_user_id=None,
                    event=True,
                )
            if result.created and result.run is not None:
                created.append(result.run.id)
        except Exception as exc:  # never break the caller
            logger.warning("workflow_emit_error type=%s event=%s", type(exc).__name__, event)
    return created
