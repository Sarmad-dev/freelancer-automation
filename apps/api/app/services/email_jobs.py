"""Background email jobs: classifying inbound messages without making anyone wait.

A job is one row per (message, kind), created when a message is stored, so enqueueing twice does nothing. A worker claims a
batch atomically (a conditional UPDATE, so two workers cannot take the same job), holds it under a lease (a crashed worker's
job is claimable again afterwards), and either finishes it, schedules a retry with backoff, or fails it for good, in which
case the conversation is sent to a person for review. Workers run after a sync request returns (``run_worker`` from a
background task) or as a separate process (``python -m app.cli process-jobs``).

Applying a result never acts on it beyond recording it, with one deliberate exception: a message that explicitly asks to
stop (confirmed by the deterministic opt-out rule, never by the model alone) puts the sender on the do-not-contact list.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app import audit
from app.ai import rules
from app.ai.schemas import AiOutcome, ClassifyReplyInput, ClassifyReplyOutput
from app.ai.service import AiService
from app.clock import utcnow
from app.db.models_email import Conversation, EmailJob, Message, MessageBody
from app.services import suppression

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger("freelancer_os.email_jobs")

REVIEW_CONFIDENCE = 0.7
LEASE = timedelta(minutes=5)
BACKOFF_SECONDS = (30, 120, 600)
MAX_ATTEMPTS = 3


@dataclass
class JobStats:
    claimed: int = 0
    classified: int = 0
    retried: int = 0
    failed: int = 0
    skipped: int = 0


def enqueue(
    db: Session,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    *,
    now: datetime | None = None,
    force: bool = False,
) -> EmailJob:
    """Make sure a classification job exists for ``message_id``. ``force`` queues it again (a re-classification)."""
    now = now or utcnow()
    job = db.scalar(
        select(EmailJob).where(EmailJob.message_id == message_id, EmailJob.kind == "classify")
    )
    if job is None:
        job = EmailJob(
            workspace_id=workspace_id,
            kind="classify",
            conversation_id=conversation_id,
            message_id=message_id,
            status="queued",
            max_attempts=MAX_ATTEMPTS,
            run_after=now,
        )
        try:
            with db.begin_nested():
                db.add(job)
                db.flush()
        except IntegrityError:  # another request enqueued it first
            existing = db.scalar(select(EmailJob).where(EmailJob.message_id == message_id))
            if existing is None:
                raise
            return existing
        return job
    if force and job.status != "running":
        job.status = "queued"
        job.attempts = 0
        job.run_after = now
        job.locked_until = None
        job.completed_at = None
        job.last_error_code = None
    return job


def claim(
    db: Session, now: datetime, limit: int, workspace_id: uuid.UUID | None = None
) -> list[uuid.UUID]:
    """Atomically take up to ``limit`` due jobs (queued, or running with an expired lease). Commits."""
    due = or_(
        (EmailJob.status == "queued") & (EmailJob.run_after <= now),
        (EmailJob.status == "running") & (EmailJob.locked_until < now),
    )
    stmt = (
        select(EmailJob.id, EmailJob.status)
        .where(due)
        .order_by(EmailJob.run_after, EmailJob.id)
        .limit(limit)
    )
    if workspace_id is not None:
        stmt = stmt.where(EmailJob.workspace_id == workspace_id)
    claimed: list[uuid.UUID] = []
    for job_id, status in db.execute(stmt).all():
        result = db.execute(
            update(EmailJob)
            .where(EmailJob.id == job_id, EmailJob.status == status, due)
            .values(status="running", attempts=EmailJob.attempts + 1, locked_until=now + LEASE)
        )
        if result.rowcount == 1:  # type: ignore[attr-defined]
            claimed.append(job_id)
    db.commit()
    return claimed


def _body_for(db: Session, message: Message) -> str:
    stored = db.scalar(select(MessageBody.body_text).where(MessageBody.message_id == message.id))
    text = stored if stored and stored.strip() else (message.snippet or "")
    return text.strip() or (message.subject or "").strip() or "(empty message)"


def _previous_outbound(db: Session, message: Message) -> str | None:
    prior = db.scalar(
        select(Message)
        .where(
            Message.conversation_id == message.conversation_id,
            Message.direction == "outbound",
            Message.sent_at <= message.sent_at,
        )
        .order_by(Message.sent_at.desc(), Message.id)
        .limit(1)
    )
    return _body_for(db, prior)[:2_000] if prior is not None else None


def latest_inbound(db: Session, conversation_id: uuid.UUID) -> Message | None:
    return db.scalar(
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.direction == "inbound",
            Message.is_bounce.is_(False),
        )
        .order_by(Message.sent_at.desc(), Message.id)
        .limit(1)
    )


def review_reason(outcome: AiOutcome[ClassifyReplyOutput], text: str) -> str | None:
    """Why a person must look at this classification, or None when it can stand."""
    assert outcome.data is not None
    if "injection_suspected" in outcome.warnings:
        return "injection_suspected"
    if outcome.data.category == "unsubscribe" and not rules.looks_like_opt_out(text):
        return "unsubscribe_unconfirmed"
    if outcome.meta.source == "rules_fallback":
        return "fallback"
    if outcome.data.confidence < REVIEW_CONFIDENCE:
        return "low_confidence"
    return None


def classification_source(outcome: AiOutcome[Any]) -> str:
    if outcome.meta.source == "rules_fallback":
        return "rules_fallback"
    return "demo_ai" if outcome.meta.is_mock else "model"


def apply_classification(
    db: Session,
    conversation: Conversation,
    message: Message,
    outcome: AiOutcome[ClassifyReplyOutput],
    text: str,
    now: datetime,
) -> None:
    data = outcome.data
    assert data is not None
    reason = review_reason(outcome, text)
    conversation.classification = data.category
    conversation.classification_confidence = data.confidence
    conversation.classification_explanation = data.rationale[:1000]
    conversation.classification_evidence = list(data.evidence)
    conversation.classification_source = classification_source(outcome)
    conversation.classified_message_id = message.id
    conversation.classified_at = now
    conversation.needs_review = reason is not None
    conversation.review_reason = reason
    audit.record(
        db,
        "email.classified",
        workspace_id=conversation.workspace_id,
        target_type="conversation",
        target_id=str(conversation.id),
        details={"kind": data.category, "state": conversation.classification_source},
    )
    if data.category == "unsubscribe" and rules.looks_like_opt_out(text):
        _, created = suppression.add(
            db,
            conversation.workspace_id,
            message.from_address,
            "unsubscribe",
            source="classification",
        )
        if created:
            audit.record(
                db,
                "email.auto_suppressed",
                workspace_id=conversation.workspace_id,
                target_type="conversation",
                target_id=str(conversation.id),
                details={"reason": "unsubscribe"},
            )


def _fail_for_good(db: Session, job: EmailJob, code: str, now: datetime) -> None:
    job.status = "failed"
    job.last_error_code = code[:40]
    job.completed_at = now
    job.locked_until = None
    conversation = db.get(Conversation, job.conversation_id)
    if conversation is not None and conversation.classified_message_id != job.message_id:
        conversation.needs_review = True
        conversation.review_reason = "classification_failed"


def run_job(db: Session, job: EmailJob, ai: AiService, now: datetime, stats: JobStats) -> None:
    message = db.get(Message, job.message_id)
    conversation = db.get(Conversation, job.conversation_id)
    if message is None or conversation is None or message.workspace_id != job.workspace_id:
        job.status = "skipped"
        job.last_error_code = "message_missing"
        job.completed_at = now
        job.locked_until = None
        stats.skipped += 1
        return
    newest = latest_inbound(db, conversation.id)
    if newest is None or newest.id != message.id:
        job.status = (
            "skipped"  # a newer message supersedes this one; its own job classifies the thread
        )
        job.last_error_code = "superseded"
        job.completed_at = now
        job.locked_until = None
        stats.skipped += 1
        return
    text = _body_for(db, message)
    outcome = ai.classify_reply(
        ClassifyReplyInput(
            subject=message.subject,
            body=text[:20_000],
            previous_outbound=_previous_outbound(db, message),
        )
    )
    if outcome.ok and outcome.data is not None:
        apply_classification(db, conversation, message, outcome, text, now)
        job.status = "succeeded"
        job.last_error_code = None
        job.completed_at = now
        job.locked_until = None
        stats.classified += 1
        return
    code = outcome.failure.code if outcome.failure else "unknown"
    if job.attempts >= job.max_attempts:
        _fail_for_good(db, job, code, now)
        stats.failed += 1
        return
    wait = outcome.failure.retry_after if outcome.failure and outcome.failure.retry_after else None
    job.status = "queued"
    job.last_error_code = code[:40]
    job.locked_until = None
    job.run_after = now + timedelta(
        seconds=wait or BACKOFF_SECONDS[min(job.attempts - 1, len(BACKOFF_SECONDS) - 1)]
    )
    stats.retried += 1


def process_batch(
    session_factory: sessionmaker[Session],
    make_ai: Callable[[uuid.UUID], AiService],
    *,
    limit: int = 25,
    workspace_id: uuid.UUID | None = None,
    now: Callable[[], datetime] = utcnow,
) -> JobStats:
    """Claim and run due jobs. Each job commits on its own, so one failure never loses another's result."""
    stats = JobStats()
    with session_factory() as db:
        ids = claim(db, now(), limit, workspace_id)
    stats.claimed = len(ids)
    for job_id in ids:
        with session_factory() as db:
            job = db.get(EmailJob, job_id)
            if job is None:
                continue
            try:
                run_job(db, job, make_ai(job.workspace_id), now(), stats)
                db.commit()
            except (
                Exception
            ) as exc:  # never let one job stop the batch; the lease expires and it is retried
                db.rollback()
                logger.warning("email_job_error type=%s job=%s", type(exc).__name__, job_id)
                with session_factory() as db2:
                    again = db2.get(EmailJob, job_id)
                    if again is not None:
                        if again.attempts >= again.max_attempts:
                            _fail_for_good(db2, again, "unexpected_error", now())
                            stats.failed += 1
                        else:
                            again.status = "queued"
                            again.locked_until = None
                            again.last_error_code = "unexpected_error"
                            again.run_after = now() + timedelta(seconds=BACKOFF_SECONDS[0])
                            stats.retried += 1
                        db2.commit()
    return stats


def run_worker(app: FastAPI, *, limit: int = 25, workspace_id: uuid.UUID | None = None) -> JobStats:
    """Process due jobs using the running app's AI provider and rate limiter (used by background tasks and the CLI)."""
    from app.ai.service import AiLimits
    from app.config import get_settings
    from app.db.session import get_sessionmaker

    settings = get_settings()

    def make_ai(wid: uuid.UUID) -> AiService:
        return AiService(
            app.state.ai_provider,
            AiLimits.from_settings(settings),
            workspace_id=wid,
            limiter=app.state.rate_limiter,
        )

    return process_batch(get_sessionmaker(), make_ai, limit=limit, workspace_id=workspace_id)


# Public names for the engine's classify-reply step (it classifies a conversation the same way the inbox worker does).
body_for = _body_for
previous_outbound = _previous_outbound
