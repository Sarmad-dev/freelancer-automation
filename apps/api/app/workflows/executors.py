"""One function per node type. Each is given a ``StepEnv`` and returns a result or raises ``StepFailure``.

Rules every executor follows:

* **Never send, approve or decide on its own.** AI nodes produce suggestions (a fit rating, a category, a draft); only a
  person's decision at an approval gate lets ``send_email`` act, and even then the normal guarded send runs.
* **Outputs are ids and short enumerations**, never message text or addresses (they end up in step logs).
* **Internal writes are atomic with the step**: they commit together with the step's result, so a crash cannot leave a
  half-finished step behind. **External effects** (the provider send) carry an idempotency key, and the send path itself
  refuses a second send.
* **Test mode simulates** record changes (``upsert_record``) and sending (``send_email``) and says so in the step output.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.ai import inputs as ai_inputs
from app.ai.schemas import (
    AssessLeadFitInput,
    ClassifyReplyInput,
    DraftOutreachInput,
)
from app.clock import as_utc
from app.db.models import Membership
from app.db.models_crm import Company, Contact, Lead
from app.db.models_email import Conversation, Draft
from app.db.models_workflow import ApprovalRequest, Notification
from app.errors import AppError
from app.schemas.drafts import DraftCreate
from app.schemas.leads import LeadPatch
from app.schemas.pipeline import OpportunityCreate
from app.schemas.tasks import TaskCreate
from app.services import drafts as draft_service
from app.services import email_jobs, opportunities, replies, suppression, tasks
from app.services import leads as lead_service
from app.services.ai_context import build_context
from app.services.fit_scoring import Scorer
from app.workflows import catalog
from app.workflows.catalog import (
    AiDraftConfig,
    ApprovalGateConfig,
    ConditionConfig,
    CreateTaskConfig,
    DelayConfig,
    EndConfig,
    NotifyConfig,
    TriggerConfig,
    UpsertRecordConfig,
)
from app.workflows.errors import StepFailure, from_ai_failure, from_app_error
from app.workflows.runtime import (
    Advance,
    Finish,
    StepEnv,
    StepResult,
    WaitApproval,
    WaitDelay,
)

DEFAULT_OUTREACH_GOAL = (
    "Introduce my services and ask whether a short conversation would be useful."
)


# ----------------------------------------------------------------------------- shared lookups


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def owner_ids(db: Session, workspace_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        db.scalars(
            select(Membership.user_id).where(
                Membership.workspace_id == workspace_id, Membership.role == "owner"
            )
        )
    )


def notify_owners(
    db: Session,
    workspace_id: uuid.UUID,
    *,
    kind: str,
    title: str,
    body: str | None,
    link: str | None,
    dedupe_key: str,
) -> int:
    """One notification per owner. A repeated ``dedupe_key`` changes nothing (the database's unique key decides)."""
    from sqlalchemy.exc import IntegrityError

    created = 0
    for user_id in owner_ids(db, workspace_id):
        existing = db.scalar(
            select(Notification.id).where(
                Notification.user_id == user_id, Notification.dedupe_key == dedupe_key
            )
        )
        if existing is not None:
            continue
        try:
            with db.begin_nested():
                db.add(
                    Notification(
                        workspace_id=workspace_id,
                        user_id=user_id,
                        kind=kind,
                        title=title[:200],
                        body=(body or "")[:500] or None,
                        link=link,
                        dedupe_key=dedupe_key[:120],
                    )
                )
                db.flush()
            created += 1
        except IntegrityError:
            continue
    return created


def _lead(env: StepEnv) -> Lead:
    lead: Lead | None = db_get_scoped(
        env.db, Lead, env.workspace_id, _uuid(env.run.context.get("lead_id"))
    )
    if lead is None:
        raise StepFailure("subject_missing")
    return lead


def _conversation(env: StepEnv) -> Conversation:
    conversation: Conversation | None = db_get_scoped(
        env.db, Conversation, env.workspace_id, _uuid(env.run.context.get("conversation_id"))
    )
    if conversation is None:
        raise StepFailure("subject_missing")
    return conversation


def db_get_scoped(db: Session, model: Any, workspace_id: uuid.UUID, id_: uuid.UUID | None) -> Any:
    if id_ is None:
        return None
    return db.scalar(select(model).where(model.id == id_, model.workspace_id == workspace_id))


def _contact_email(env: StepEnv, lead: Lead) -> str | None:
    if lead.contact_id is None:
        return None
    contact = db_get_scoped(env.db, Contact, env.workspace_id, lead.contact_id)
    return contact.email if contact is not None and contact.email else None


def _template_values(env: StepEnv) -> dict[str, str]:
    values: dict[str, str] = {}
    ctx = env.run.context
    lead_id = _uuid(ctx.get("lead_id"))
    if lead_id is not None:
        lead = db_get_scoped(env.db, Lead, env.workspace_id, lead_id)
        if lead is not None:
            values["lead_title"] = lead.title
            company = db_get_scoped(env.db, Company, env.workspace_id, lead.company_id)
            values["company_name"] = company.name if company is not None else ""
    classification = ctx.get("classification")
    if isinstance(classification, dict):
        values["category"] = str(classification.get("category", "")).replace("_", " ")
    fit = ctx.get("fit")
    if isinstance(fit, dict):
        values["fit_rating"] = str(fit.get("rating", ""))
    return values


def _ai_failure(outcome: Any) -> StepFailure:
    failure = outcome.failure
    if failure is None:
        return StepFailure("ai_unavailable")
    return from_ai_failure(
        failure.code, retryable=failure.retryable, retry_after=failure.retry_after
    )


# ----------------------------------------------------------------------------- trigger, condition, end


def run_trigger(env: StepEnv) -> StepResult:
    cfg = env.cfg
    assert isinstance(cfg, TriggerConfig)
    return Advance(output={"event": cfg.event, "mode": env.mode})


def _field_value(env: StepEnv, name: str) -> Any:
    ctx = env.run.context
    if name == "fit.rating":
        fit = ctx.get("fit")
        return fit.get("rating") if isinstance(fit, dict) else None
    if name == "classification.category":
        c = ctx.get("classification")
        return c.get("category") if isinstance(c, dict) else None
    if name == "classification.needs_review":
        c = ctx.get("classification")
        return bool(c.get("needs_review")) if isinstance(c, dict) else None
    lead = _lead(env)
    if name == "lead.status":
        return lead.status
    if name == "lead.score":
        return lead.fit_score
    email = _contact_email(env, lead)
    if name == "lead.has_contact_email":
        return email is not None
    if name == "contact.suppressed":
        return email is not None and suppression.find(env.db, env.workspace_id, email) is not None
    raise StepFailure("validation")


def evaluate(cfg: ConditionConfig, actual: Any) -> bool:
    """A missing value never satisfies a comparison (and never satisfies ``ne``/``not_in`` either: unknown is unknown)."""
    op = cfg.op
    if op == "is_true":
        return actual is True
    if op == "is_false":
        return actual is False
    if actual is None:
        return False
    value = cfg.value
    if op == "eq":
        return bool(actual == value)
    if op == "ne":
        return bool(actual != value)
    if op == "in":
        return isinstance(value, list) and actual in value
    if op == "not_in":
        return isinstance(value, list) and actual not in value
    if op == "gte":
        return isinstance(value, (int, float)) and actual >= value
    if op == "lte":
        return isinstance(value, (int, float)) and actual <= value
    raise StepFailure("validation")


def run_condition(env: StepEnv) -> StepResult:
    cfg = env.cfg
    assert isinstance(cfg, ConditionConfig)
    result = evaluate(cfg, _field_value(env, cfg.field))
    return Advance(
        port="true" if result else "false",
        output={"field": cfg.field, "op": cfg.op, "result": result},
    )


def run_end(env: StepEnv) -> StepResult:
    cfg = env.cfg
    assert isinstance(cfg, EndConfig)
    return Finish(cfg.outcome, cfg.reason, {"outcome": cfg.outcome})


# ----------------------------------------------------------------------------- AI steps


def run_assess_fit(env: StepEnv) -> StepResult:
    lead = _lead(env)
    try:
        facts = ai_inputs.lead_facts(env.db, env.ctx, lead.id)
    except AppError as exc:
        raise from_app_error(exc) from None
    ai = env.deps.ai_for(env.workspace_id, env.timeout_seconds)
    outcome = ai.assess_lead_fit(
        AssessLeadFitInput(lead=facts, rule_score=lead.fit_score), build_context(env.db, env.ctx)
    )
    if not outcome.ok or outcome.data is None:
        raise _ai_failure(outcome)
    data = outcome.data
    return Advance(
        output={
            "assessment": data.assessment,
            "confidence": round(data.confidence, 2),
            "reasons": len(data.reasons),
            "demo_ai": outcome.meta.is_mock,
        },
        context={"fit": {"rating": data.assessment}},
    )


def run_classify_reply(env: StepEnv) -> StepResult:
    conversation = _conversation(env)
    message = email_jobs.latest_inbound(env.db, conversation.id)
    if message is None:
        raise StepFailure(
            "missing_data", summary="This conversation has no incoming reply to classify."
        )
    reused = (
        conversation.classified_message_id == message.id
        and conversation.classification not in (None, "", "unclassified")
    )
    confidence = conversation.classification_confidence
    if not reused:
        text = email_jobs.body_for(env.db, message)
        ai = env.deps.ai_for(env.workspace_id, env.timeout_seconds)
        outcome = ai.classify_reply(
            ClassifyReplyInput(
                subject=message.subject,
                body=text[:20_000],
                previous_outbound=email_jobs.previous_outbound(env.db, message),
            )
        )
        if not outcome.ok or outcome.data is None:
            raise _ai_failure(outcome)
        email_jobs.apply_classification(env.db, conversation, message, outcome, text, env.now)
        confidence = outcome.data.confidence
    return Advance(
        output={
            "category": conversation.classification,
            "confidence": round(confidence, 2) if confidence is not None else None,
            "needs_review": bool(conversation.needs_review),
            "reused": reused,
        },
        context={
            "classification": {
                "category": conversation.classification,
                "needs_review": bool(conversation.needs_review),
            }
        },
    )


def run_ai_draft(env: StepEnv) -> StepResult:
    cfg = env.cfg
    assert isinstance(cfg, AiDraftConfig)
    if cfg.mode == "reply":
        conversation = _conversation(env)
        ai = env.deps.ai_for(env.workspace_id, env.timeout_seconds)
        try:
            draft, regenerated, _warnings, _label, is_demo = replies.suggest_reply(
                env.db, env.ctx, conversation, ai, env.now
            )
        except AppError as exc:
            raise from_app_error(exc) from None
        return Advance(
            output={
                "draft_id": str(draft.id),
                "regenerated": regenerated,
                "demo_ai": is_demo,
                "facts_used": len(draft.facts_used or []),
            },
            context={"draft_id": str(draft.id)},
        )

    lead = _lead(env)
    email = _contact_email(env, lead)
    if email is None:
        raise StepFailure("missing_data", summary="The lead has no contact email to write to.")
    if suppression.find(env.db, env.workspace_id, email) is not None:
        raise StepFailure("suppressed")
    try:
        target, first_name = ai_inputs.draft_target(env.db, env.ctx, lead.id)
    except AppError as exc:
        raise from_app_error(exc) from None
    ai = env.deps.ai_for(env.workspace_id, env.timeout_seconds)
    outcome = ai.draft_outreach(
        DraftOutreachInput(
            lead=target,
            recipient_first_name=first_name,
            goal=cfg.goal or DEFAULT_OUTREACH_GOAL,
        ),
        build_context(env.db, env.ctx),
    )
    if not outcome.ok or outcome.data is None:
        raise _ai_failure(outcome)
    data = outcome.data
    try:
        draft = draft_service.create_draft(
            env.db,
            env.ctx,
            DraftCreate(
                lead_id=lead.id, to_address=email, subject=data.subject, body_text=data.body
            ),
        )
    except AppError as exc:
        raise from_app_error(exc) from None
    draft.author = "ai"
    draft.facts_used = [str(i) for i in data.facts_used]
    env.db.flush()
    return Advance(
        output={
            "draft_id": str(draft.id),
            "regenerated": False,
            "demo_ai": outcome.meta.is_mock,
            "facts_used": len(data.facts_used),
        },
        context={"draft_id": str(draft.id)},
    )


# ----------------------------------------------------------------------------- records, tasks, notifications


def run_upsert_record(env: StepEnv) -> StepResult:
    cfg = env.cfg
    assert isinstance(cfg, UpsertRecordConfig)
    if env.simulated:
        return Advance(output={"simulated": True, "action": cfg.action})
    lead = _lead(env)
    stage = None
    if cfg.stage_key is not None:
        stage = lead_service.stages_by_key(env.db, env.ctx).get(cfg.stage_key)
        if stage is None:
            raise StepFailure("missing_data", summary="That pipeline stage does not exist.")
    try:
        if cfg.action == "update_lead":
            assert stage is not None
            lead_service.update_lead(
                env.db, env.ctx, lead, LeadPatch(stage_id=stage.id), Scorer.load(env.db, env.ctx)
            )
            return Advance(
                output={"simulated": False, "action": cfg.action, "stage": cfg.stage_key}
            )
        opp = opportunities.create_opportunity(
            env.db,
            env.ctx,
            OpportunityCreate(
                lead_id=lead.id, title=cfg.title, stage_id=stage.id if stage else None
            ),
        )
    except AppError as exc:
        raise from_app_error(exc) from None
    return Advance(
        output={"simulated": False, "action": cfg.action, "opportunity_id": str(opp.id)},
        context={"opportunity_id": str(opp.id)},
    )


def run_create_task(env: StepEnv) -> StepResult:
    cfg = env.cfg
    assert isinstance(cfg, CreateTaskConfig)
    values = _template_values(env)
    title = catalog.render(cfg.title, values).strip()[:200] or "Follow up"
    description = catalog.render(cfg.description, values).strip() if cfg.description else None
    started = as_utc(env.run.started_at or env.run.created_at)
    due = started + timedelta(days=cfg.due_in_days) if cfg.due_in_days is not None else None
    lead_id = _uuid(env.run.context.get("lead_id"))
    conversation_id = _uuid(env.run.context.get("conversation_id"))
    body = TaskCreate(
        title=title,
        description=(description or None) and description[:1_000],
        priority=cfg.priority,
        due_at=due,
        lead_id=lead_id,
        conversation_id=conversation_id,
        idempotency_key=env.effect_key(),
    )
    try:
        task, created = tasks.create_task(env.db, env.ctx, body)
    except AppError as exc:
        if exc.code == "idempotency_conflict":
            existing = tasks._existing_by_key(env.db, env.ctx, env.effect_key())
            if existing is None:
                raise from_app_error(exc) from None
            task, created = existing, False
        else:
            raise from_app_error(exc) from None
    if created:
        task.created_by = "workflow"
    return Advance(
        output={"task_id": str(task.id), "created": created}, context={"task_id": str(task.id)}
    )


def run_notify(env: StepEnv) -> StepResult:
    cfg = env.cfg
    assert isinstance(cfg, NotifyConfig)
    values = _template_values(env)
    title = catalog.render(cfg.title, values).strip()[:200] or "Workflow update"
    body = catalog.render(cfg.message, values).strip()[:500] if cfg.message else None
    run = env.run
    link = "/automations"
    if run.subject_type == "lead" and run.subject_id is not None:
        link = f"/leads/{run.subject_id}"
    elif run.subject_type == "conversation" and run.subject_id is not None:
        link = f"/inbox?c={run.subject_id}"
    created = notify_owners(
        env.db,
        env.workspace_id,
        kind="workflow",
        title=title,
        body=body,
        link=link,
        dedupe_key=env.effect_key(),
    )
    return Advance(output={"notified": created})


# ----------------------------------------------------------------------------- delay and approval


def run_delay(env: StepEnv) -> StepResult:
    cfg = env.cfg
    assert isinstance(cfg, DelayConfig)
    wake_at = env.now + timedelta(seconds=cfg.seconds)
    return WaitDelay(wake_at, {"seconds": cfg.seconds, "wake_at": wake_at.isoformat()})


def _draft_for_gate(env: StepEnv) -> Draft | None:
    draft_id = _uuid(env.run.context.get("draft_id"))
    if draft_id is None:
        return None
    draft: Draft | None = db_get_scoped(env.db, Draft, env.workspace_id, draft_id)
    if draft is None or draft_service.send_locked(draft):
        raise StepFailure(
            "missing_data", summary="The draft is gone, or has already been sent or discarded."
        )
    return draft


def run_approval_gate(env: StepEnv) -> StepResult:
    cfg = env.cfg
    assert isinstance(cfg, ApprovalGateConfig)
    draft = _draft_for_gate(env)
    if draft is not None:
        if draft.to_address and suppression.find(env.db, env.workspace_id, draft.to_address):
            raise StepFailure("suppressed")
        payload_hash = draft_service.content_hash(draft.to_address, draft.subject, draft.body_text)
        draft.content_hash = payload_hash
        if draft.status == "draft":
            draft.status = "pending_approval"
    else:
        payload_hash = hashlib.sha256(f"{env.run.id}:{env.node_key}".encode()).hexdigest()
    existing = env.db.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.workspace_id == env.workspace_id,
            ApprovalRequest.step_run_id == env.step.id,
        )
    )
    if existing is not None:
        return WaitApproval(existing.id, {"approval_id": str(existing.id)})
    run = env.run
    approval = ApprovalRequest(
        workspace_id=env.workspace_id,
        run_id=run.id,
        step_run_id=env.step.id,
        draft_id=draft.id if draft is not None else None,
        kind="send_email" if draft is not None else "workflow_step",
        target_type=run.subject_type,
        target_id=str(run.subject_id) if run.subject_id else None,
        payload_hash=payload_hash,
        proposed_payload={"summary": cfg.message, "node": env.node_key, "mode": env.mode},
        status="pending",
        requested_by_user_id=run.started_by_user_id,
        expires_at=env.now + timedelta(hours=cfg.expires_hours),
    )
    env.db.add(approval)
    env.db.flush()
    notify_owners(
        env.db,
        env.workspace_id,
        kind="approval_pending",
        title="A workflow is waiting for your approval",
        body=cfg.message[:300],
        link=f"/automations?approval={approval.id}",
        dedupe_key=f"approval:{approval.id}",
    )
    return WaitApproval(approval.id, {"approval_id": str(approval.id)})


def resume_approval(env: StepEnv, approval: ApprovalRequest) -> StepResult:
    """The step was waiting and a decision (or expiry) has arrived."""
    if approval.status in ("rejected", "expired"):
        return Advance(
            port="rejected",
            output={"approval_id": str(approval.id), "decision": approval.status},
        )
    if approval.status != "approved":
        raise StepFailure("approval_invalidated")
    context: dict[str, Any] = {"approval_id": str(approval.id)}
    if approval.draft_id is not None:
        draft = db_get_scoped(env.db, Draft, env.workspace_id, approval.draft_id)
        if (
            draft is None
            or not draft_service.approval_is_current(draft)
            or draft.content_hash != approval.payload_hash
        ):
            raise StepFailure("approval_invalidated")
        context["approved_draft_id"] = str(draft.id)
    return Advance(
        port="approved",
        output={"approval_id": str(approval.id), "decision": "approved"},
        context=context,
    )


# ----------------------------------------------------------------------------- send


def run_send_email(env: StepEnv) -> StepResult:
    run = env.run
    draft_id = _uuid(run.context.get("draft_id"))
    approval_id = _uuid(run.context.get("approval_id"))
    approved_draft = _uuid(run.context.get("approved_draft_id"))
    if draft_id is None or approval_id is None or approved_draft != draft_id:
        raise StepFailure("not_approved")
    draft = db_get_scoped(env.db, Draft, env.workspace_id, draft_id)
    approval = db_get_scoped(env.db, ApprovalRequest, env.workspace_id, approval_id)
    if draft is None or approval is None:
        raise StepFailure("not_approved")

    # A previous attempt of this very step already delivered it (the worker died before recording the result).
    prefix = env.send_key_prefix()
    if (
        draft.status == "sent"
        and draft.send_idempotency_key
        and draft.send_idempotency_key.startswith(prefix)
    ):
        return Advance(output={"delivery_state": "sent", "replayed": True})

    if (
        approval.status != "approved"
        or approval.run_id != run.id
        or approval.draft_id != draft.id
        or approval.payload_hash != draft.content_hash
        or not draft_service.approval_is_current(draft)
    ):
        raise StepFailure("not_approved")
    if draft.to_address and suppression.find(env.db, env.workspace_id, draft.to_address):
        raise StepFailure("suppressed")

    if env.simulated:
        return Advance(
            output={"simulated": True, "delivery_state": "not_sent_test_mode"},
        )

    if (
        draft.send_idempotency_key
        and draft.send_idempotency_key.startswith(prefix)
        and draft.status != "sent"
    ):
        # An earlier attempt of this step left the send in an unconfirmed state: never send again on a guess.
        raise StepFailure("outcome_unknown")

    key = f"{prefix}{env.attempt}"
    try:
        result = draft_service.send_draft(
            env.db,
            env.ctx,
            draft.id,
            key,
            now=env.now,
            info=audit.RequestInfo(ip=None, user_agent=None),
            settings=env.deps.settings,
            store=env.deps.store,
            registry=env.deps.registry,
            limiter=env.deps.limiter,
        )
    except AppError as exc:
        env.db.rollback()
        raise from_app_error(exc) from None
    if result.unknown or result.message.delivery_state in ("unknown", "queued"):
        raise StepFailure("outcome_unknown")
    if result.message.delivery_state == "failed":
        raise StepFailure("send_failed")
    return Advance(
        output={"delivery_state": result.message.delivery_state, "replayed": result.replayed},
    )


EXECUTORS: dict[str, Callable[[StepEnv], StepResult]] = {
    "trigger": run_trigger,
    "condition": run_condition,
    "ai_assess_fit": run_assess_fit,
    "ai_classify_reply": run_classify_reply,
    "ai_draft": run_ai_draft,
    "upsert_record": run_upsert_record,
    "create_task": run_create_task,
    "approval_gate": run_approval_gate,
    "send_email": run_send_email,
    "delay": run_delay,
    "notify": run_notify,
    "end": run_end,
}
