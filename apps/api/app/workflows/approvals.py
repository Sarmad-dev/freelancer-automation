"""Approvals: the durable pause. A person's decision (or the clock) is what makes a waiting run due again.

An approval is bound to the exact thing it approves: for a draft, the hash of recipient, subject and body at the moment
it was requested. If the draft changes after that, the approval is void (``invalidated``) and the run fails with a
clear reason instead of sending something nobody read. Only a workspace owner can decide.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.clock import as_utc
from app.db.models_email import Draft
from app.db.models_workflow import ApprovalRequest, WorkflowRun
from app.deps import WorkspaceContext
from app.errors import AppError
from app.services import drafts as draft_service
from app.workflows.engine import _revert_draft
from app.workflows.executors import db_get_scoped


def _wake(db: Session, approval: ApprovalRequest) -> None:
    if approval.run_id is None:
        return
    run = db.get(WorkflowRun, approval.run_id)
    if run is not None and run.status == "waiting_approval":
        run.status = "queued"
        run.wake_at = None


def expire_due(db: Session, now: datetime) -> int:
    """Mark pending approvals past their expiry as expired and wake their runs (which take the 'rejected' path)."""
    due = list(
        db.scalars(
            select(ApprovalRequest).where(
                ApprovalRequest.status == "pending",
                ApprovalRequest.expires_at.is_not(None),
                ApprovalRequest.expires_at <= now,
            )
        )
    )
    for approval in due:
        approval.status = "expired"
        approval.invalidated_reason = "expired"
        _revert_draft(db, approval)
        _wake(db, approval)
        audit.record(
            db,
            "workflow.approval_expired",
            workspace_id=approval.workspace_id,
            target_type="approval_request",
            target_id=str(approval.id),
            details={"run_id": str(approval.run_id) if approval.run_id else None},
        )
    return len(due)


def invalidate_for_draft(
    db: Session, workspace_id: uuid.UUID, draft_id: uuid.UUID, reason: str
) -> int:
    """A draft changed: any pending approval for it no longer describes what would be sent."""
    pending = list(
        db.scalars(
            select(ApprovalRequest).where(
                ApprovalRequest.workspace_id == workspace_id,
                ApprovalRequest.draft_id == draft_id,
                ApprovalRequest.status == "pending",
            )
        )
    )
    for approval in pending:
        approval.status = "invalidated"
        approval.invalidated_reason = reason[:200]
        _wake(db, approval)
    return len(pending)


def decide(
    db: Session,
    ctx: WorkspaceContext,
    approval: ApprovalRequest,
    decision: Literal["approve", "reject"],
    note: str | None,
    now: datetime,
) -> ApprovalRequest:
    if approval.status != "pending":
        raise AppError(409, "approval_already_decided", "This approval has already been decided.")
    if approval.expires_at is not None and as_utc(approval.expires_at) <= now:
        approval.status = "expired"
        approval.invalidated_reason = "expired"
        _revert_draft(db, approval)
        _wake(db, approval)
        db.commit()
        raise AppError(409, "approval_expired", "This approval expired before it was decided.")
    run = db.get(WorkflowRun, approval.run_id) if approval.run_id else None
    if run is None or run.status != "waiting_approval":
        raise AppError(
            409, "run_not_waiting", "The workflow run is no longer waiting for this approval."
        )

    if decision == "approve":
        if approval.draft_id is not None:
            draft = db_get_scoped(db, Draft, approval.workspace_id, approval.draft_id)
            if draft is None or draft_service.send_locked(draft):
                approval.status = "invalidated"
                approval.invalidated_reason = "draft_unavailable"
                _wake(db, approval)
                db.commit()
                raise AppError(
                    409,
                    "approval_invalidated",
                    "The draft is gone or was already sent, so this approval no longer applies.",
                )
            if (
                draft_service.content_hash(draft.to_address, draft.subject, draft.body_text)
                != approval.payload_hash
            ):
                approval.status = "invalidated"
                approval.invalidated_reason = "draft_edited"
                _wake(db, approval)
                db.commit()
                raise AppError(
                    409,
                    "approval_invalidated",
                    "The draft was edited after this approval was requested. Review the new text; the run has stopped and can be retried.",
                )
            draft_service.approve(
                db, ctx, draft, now
            )  # also refuses an incomplete draft (422), changing nothing
        approval.status = "approved"
    else:
        approval.status = "rejected"
        _revert_draft(db, approval)
    approval.decided_by_user_id = ctx.user.id
    approval.decided_at = now
    approval.decision_note = (note or None) and (note or "")[:500]
    _wake(db, approval)
    audit.record(
        db,
        "workflow.approval_decided",
        actor_user_id=ctx.user.id,
        workspace_id=approval.workspace_id,
        target_type="approval_request",
        target_id=str(approval.id),
        details={
            "decision": approval.status,
            "run_id": str(approval.run_id) if approval.run_id else None,
        },
    )
    return approval
