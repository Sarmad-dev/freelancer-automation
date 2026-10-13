"""Opportunities (deals): creation, editing, stage moves with their rules, and the pipeline board."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.clock import utcnow
from app.db.models_crm import Company, Lead, Opportunity, PipelineStage, Task
from app.deps import WorkspaceContext
from app.errors import AppError
from app.schemas.crm import PipelineStageOut
from app.schemas.pipeline import (
    BoardColumn,
    MoneyTotal,
    OpportunityCreate,
    OpportunityLeadRef,
    OpportunityMove,
    OpportunityOut,
    OpportunityPatch,
    PipelineBoard,
)
from app.services import crm
from app.services import leads as lead_svc

BOARD_COLUMN_LIMIT = 50
_CENT = Decimal("0.01")


def _stage_error(message: str = "Stage not found.") -> AppError:
    return AppError(
        422, "validation_error", "Some fields are invalid.", fields={"stage_id": message}
    )


def stage_map(db: DbSession, ctx: WorkspaceContext) -> dict[uuid.UUID, PipelineStage]:
    return {s.id: s for s in lead_svc.stages_by_key(db, ctx).values()}


def require_stage(db: DbSession, ctx: WorkspaceContext, stage_id: uuid.UUID) -> PipelineStage:
    stage = stage_map(db, ctx).get(stage_id)
    if stage is None:
        raise _stage_error()
    return stage


def _is_closed_stage(stage: PipelineStage) -> bool:
    return stage.is_won or stage.is_lost


def default_open_stage(db: DbSession, ctx: WorkspaceContext, lead: Lead) -> PipelineStage:
    stages = sorted(stage_map(db, ctx).values(), key=lambda s: s.position)
    current = next((s for s in stages if s.id == lead.stage_id), None)
    if current is not None and not _is_closed_stage(current):
        return current
    return next(s for s in stages if not _is_closed_stage(s))


def _lead(db: DbSession, ctx: WorkspaceContext, lead_id: uuid.UUID) -> Lead:
    lead = db.scalar(select(Lead).where(Lead.workspace_id == ctx.workspace_id, Lead.id == lead_id))
    if lead is None:
        raise crm.invalid_ref("lead_id", "Lead")
    return lead


def create_opportunity(
    db: DbSession, ctx: WorkspaceContext, body: OpportunityCreate
) -> Opportunity:
    lead = _lead(db, ctx, body.lead_id)
    crm.ensure_editable(lead.archived_at, "lead")
    if body.stage_id is not None:
        stage = require_stage(db, ctx, body.stage_id)
        if _is_closed_stage(stage):
            raise _stage_error(
                "A new deal starts in an open stage. Close it from the board when it is decided."
            )
    else:
        stage = default_open_stage(db, ctx, lead)
    opp = Opportunity(
        workspace_id=ctx.workspace_id,
        lead_id=lead.id,
        stage_id=stage.id,
        title=body.title or lead.title[:200],
        status="open",
        value_amount=body.value_amount,
        currency=body.currency,
        probability=body.probability,
        expected_close_date=body.expected_close_date,
        next_action=body.next_action,
        owner_user_id=ctx.user.id,
    )
    db.add(opp)
    db.flush()
    lead_svc.add_activity(
        db,
        ctx,
        lead,
        "system",
        f"Opportunity created: {opp.title}",
        opportunity_id=opp.id,
        details={"to": stage.key},
    )
    db.flush()
    return opp


def update_opportunity(
    db: DbSession, ctx: WorkspaceContext, opp: Opportunity, body: OpportunityPatch
) -> list[str]:
    changes = body.model_dump(exclude_unset=True)
    for required in ("title", "currency"):
        if required in changes and changes[required] is None:
            changes.pop(required)
    if changes.get("loss_reason") is not None and opp.status != "lost":
        raise AppError(
            422,
            "validation_error",
            "Some fields are invalid.",
            fields={"loss_reason": "Only lost deals have a loss reason."},
        )
    for name, value in changes.items():
        setattr(opp, name, value)
    db.flush()
    return sorted(changes)


def _locked(db: DbSession, ctx: WorkspaceContext, opp: Opportunity) -> Opportunity:
    """Re-read the deal with a row lock (PostgreSQL) so two simultaneous moves can't both pass the checks."""
    row = db.scalar(
        select(Opportunity)
        .where(Opportunity.workspace_id == ctx.workspace_id, Opportunity.id == opp.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert row is not None
    return row


def move_opportunity(
    db: DbSession, ctx: WorkspaceContext, opp: Opportunity, body: OpportunityMove
) -> tuple[Opportunity, bool]:
    """Move to another stage. Returns ``(deal, changed)``."""
    opp = _locked(db, ctx, opp)
    stages = stage_map(db, ctx)
    target = stages.get(body.stage_id)
    if target is None:
        raise _stage_error()
    if body.expected_stage_id is not None and opp.stage_id != body.expected_stage_id:
        raise AppError(
            409,
            "stale_stage",
            "This deal was moved by someone else. The board has been refreshed; try again.",
        )
    if opp.stage_id == target.id:
        return opp, False
    if opp.status != "open":
        raise AppError(
            409,
            "opportunity_closed",
            "This deal is already won or lost. Reopen it before moving it.",
        )
    if body.loss_reason and not target.is_lost:
        raise AppError(
            422,
            "validation_error",
            "Some fields are invalid.",
            fields={"loss_reason": "Only lost deals have a loss reason."},
        )
    previous = stages.get(opp.stage_id)
    now = utcnow()
    opp.stage_id = target.id
    if target.is_won:
        opp.status, opp.closed_at, opp.loss_reason = "won", now, None
    elif target.is_lost:
        opp.status, opp.closed_at, opp.loss_reason = "lost", now, body.loss_reason
    lead = db.get(Lead, opp.lead_id)
    assert lead is not None
    lead_svc.add_activity(
        db,
        ctx,
        lead,
        "stage_change",
        f"Deal moved to {target.name}",
        opportunity_id=opp.id,
        details={
            "from": previous.key if previous else None,
            "to": target.key,
            "deal": opp.title[:100],
        },
    )
    db.flush()
    return opp, True


def reopen_opportunity(
    db: DbSession, ctx: WorkspaceContext, opp: Opportunity, stage_id: uuid.UUID
) -> Opportunity:
    opp = _locked(db, ctx, opp)
    if opp.status == "open":
        raise AppError(409, "opportunity_open", "This deal is already open.")
    stage = require_stage(db, ctx, stage_id)
    if _is_closed_stage(stage):
        raise _stage_error("Reopen into an open stage.")
    opp.status, opp.closed_at, opp.loss_reason, opp.stage_id = "open", None, None, stage.id
    lead = db.get(Lead, opp.lead_id)
    assert lead is not None
    lead_svc.add_activity(
        db,
        ctx,
        lead,
        "stage_change",
        f"Deal reopened in {stage.name}",
        opportunity_id=opp.id,
        details={"to": stage.key, "deal": opp.title[:100]},
    )
    db.flush()
    return opp


# ---------------------------------------------------------------- serialisation
def _weighted(opp: Opportunity) -> Decimal | None:
    if opp.status != "open" or opp.value_amount is None or opp.probability is None:
        return None
    return (Decimal(opp.value_amount) * opp.probability / 100).quantize(_CENT, ROUND_HALF_UP)


def opportunity_outs(
    db: DbSession, ctx: WorkspaceContext, opps: Sequence[Opportunity]
) -> list[OpportunityOut]:
    if not opps:
        return []
    stages = stage_map(db, ctx)
    lead_ids = {o.lead_id for o in opps}
    leads = {
        row.id: row
        for row in db.scalars(
            select(Lead).where(Lead.workspace_id == ctx.workspace_id, Lead.id.in_(lead_ids))
        )
    }
    company_ids = {lead.company_id for lead in leads.values() if lead.company_id}
    companies: dict[uuid.UUID, str] = (
        {
            row[0]: row[1]
            for row in db.execute(
                select(Company.id, Company.name).where(
                    Company.workspace_id == ctx.workspace_id, Company.id.in_(company_ids)
                )
            )
        }
        if company_ids
        else {}
    )
    counts = {
        row[0]: int(row[1])
        for row in db.execute(
            select(Task.opportunity_id, func.count())
            .where(
                Task.workspace_id == ctx.workspace_id,
                Task.opportunity_id.in_([o.id for o in opps]),
                Task.status == "open",
            )
            .group_by(Task.opportunity_id)
        )
    }
    out: list[OpportunityOut] = []
    for o in opps:
        lead = leads[o.lead_id]
        out.append(
            OpportunityOut(
                id=o.id,
                lead=OpportunityLeadRef(
                    id=lead.id,
                    title=lead.title,
                    company_name=companies.get(lead.company_id) if lead.company_id else None,
                ),
                stage=PipelineStageOut.model_validate(stages[o.stage_id]),
                status=o.status,
                title=o.title,
                value_amount=o.value_amount,
                currency=o.currency,
                probability=o.probability,
                weighted_value=_weighted(o),
                expected_close_date=o.expected_close_date,
                next_action=o.next_action,
                loss_reason=o.loss_reason,
                closed_at=o.closed_at,
                owner_user_id=o.owner_user_id,
                is_sample=o.is_sample,
                open_tasks=counts.get(o.id, 0),
                created_at=o.created_at,
                updated_at=o.updated_at,
            )
        )
    return out


def board(db: DbSession, ctx: WorkspaceContext) -> PipelineBoard:
    stages = sorted(stage_map(db, ctx).values(), key=lambda s: s.position)
    wid = ctx.workspace_id
    counts = {
        row[0]: int(row[1])
        for row in db.execute(
            select(Opportunity.stage_id, func.count())
            .where(Opportunity.workspace_id == wid)
            .group_by(Opportunity.stage_id)
        )
    }
    sums: dict[uuid.UUID, dict[str, list[Any]]] = defaultdict(dict)
    for stage_id, currency, total, valued in db.execute(
        select(
            Opportunity.stage_id,
            Opportunity.currency,
            func.sum(Opportunity.value_amount),
            func.count(Opportunity.value_amount),
        )
        .where(Opportunity.workspace_id == wid)
        .group_by(Opportunity.stage_id, Opportunity.currency)
    ):
        sums[stage_id][currency] = [Decimal(total or 0), 0, valued]
    # Weighted values need value x probability per row; computed in Python so SQLite and PostgreSQL agree.
    weighted: dict[tuple[uuid.UUID, str], Decimal] = defaultdict(Decimal)
    estimated: dict[tuple[uuid.UUID, str], int] = defaultdict(int)
    for stage_id, currency, value, probability in db.execute(
        select(
            Opportunity.stage_id,
            Opportunity.currency,
            Opportunity.value_amount,
            Opportunity.probability,
        ).where(
            Opportunity.workspace_id == wid,
            Opportunity.status == "open",
            Opportunity.value_amount.is_not(None),
            Opportunity.probability.is_not(None),
        )
    ):
        weighted[(stage_id, currency)] += Decimal(value) * probability / 100
        estimated[(stage_id, currency)] += 1
    columns: list[BoardColumn] = []
    for stage in stages:
        rows = list(
            db.scalars(
                select(Opportunity)
                .where(Opportunity.workspace_id == wid, Opportunity.stage_id == stage.id)
                .order_by(Opportunity.updated_at.desc(), Opportunity.id)
                .limit(BOARD_COLUMN_LIMIT)
            )
        )
        closed = _is_closed_stage(stage)
        in_stage = counts.get(stage.id, 0)
        totals = [
            MoneyTotal(
                currency=currency,
                amount=Decimal(total).quantize(_CENT, ROUND_HALF_UP),
                # No estimate, no weighted figure: "$0 weighted" would claim a forecast we don't have.
                weighted=None
                if closed or not estimated[(stage.id, currency)]
                else weighted[(stage.id, currency)].quantize(_CENT, ROUND_HALF_UP),
            )
            for currency, (total, _, _valued) in sorted(sums.get(stage.id, {}).items())
        ]
        valued_total = sum(v[2] for v in sums.get(stage.id, {}).values())
        columns.append(
            BoardColumn(
                stage=PipelineStageOut.model_validate(stage),
                count=in_stage,
                unvalued=in_stage - valued_total,
                totals=totals,
                items=opportunity_outs(db, ctx, rows),
            )
        )
    return PipelineBoard(
        columns=columns, per_column_limit=BOARD_COLUMN_LIMIT, generated_at=utcnow()
    )
