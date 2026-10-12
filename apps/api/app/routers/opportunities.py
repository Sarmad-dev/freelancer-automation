"""Opportunities (deals): list, create, edit, move between stages, reopen and timeline (MVP Prompt 7)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import exists, func, or_

from app.api.pagination import Page, PageParams, page_params, paginate
from app.api.scoping import get_scoped_or_404, scoped_select
from app.db.models_crm import Activity, Company, Lead, Opportunity
from app.deps import DbDep, SettingsDep, WorkspaceDep, require_owner
from app.routers._common import ERRORS, audit_event, like_pattern, sample_filter
from app.schemas.leads import ActivityCreate, ActivityOut
from app.schemas.pipeline import (
    OpportunityCreate,
    OpportunityMove,
    OpportunityOut,
    OpportunityPatch,
    OpportunityReopen,
)
from app.services import leads as lead_svc
from app.services import opportunities as svc

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/opportunities", tags=["opportunities"])

_SORT = {
    "updated_at": Opportunity.updated_at,
    "created_at": Opportunity.created_at,
    "title": func.lower(Opportunity.title),
    "value_amount": Opportunity.value_amount,
    "expected_close_date": Opportunity.expected_close_date,
    "probability": Opportunity.probability,
}


def _get(db: DbDep, ctx: WorkspaceDep, opportunity_id: uuid.UUID) -> Opportunity:
    return get_scoped_or_404(
        db,
        Opportunity,
        ctx,
        opportunity_id,
        code="opportunity_not_found",
        message="Opportunity not found.",
    )


def _out(db: DbDep, ctx: WorkspaceDep, opp: Opportunity) -> OpportunityOut:
    return svc.opportunity_outs(db, ctx, [opp])[0]


@router.get("", response_model=Page[OpportunityOut], responses=ERRORS, summary="List opportunities")
def list_opportunities(
    ctx: WorkspaceDep,
    db: DbDep,
    params: Annotated[PageParams, Depends(page_params)],
    q: Annotated[
        str | None, Query(max_length=100, description="Title, lead or company contains.")
    ] = None,
    status_filter: Annotated[Literal["open", "won", "lost"] | None, Query(alias="status")] = None,
    stage_id: Annotated[uuid.UUID | None, Query()] = None,
    lead_id: Annotated[uuid.UUID | None, Query()] = None,
    close_before: Annotated[date | None, Query(description="Expected close on or before.")] = None,
    close_after: Annotated[date | None, Query(description="Expected close on or after.")] = None,
    sample: Annotated[Literal["only", "exclude"] | None, Query()] = None,
) -> Page[OpportunityOut]:
    stmt = sample_filter(scoped_select(Opportunity, ctx), Opportunity, sample)
    if status_filter:
        stmt = stmt.where(Opportunity.status == status_filter)
    if stage_id:
        stmt = stmt.where(Opportunity.stage_id == stage_id)
    if lead_id:
        stmt = stmt.where(Opportunity.lead_id == lead_id)
    if close_before:
        stmt = stmt.where(Opportunity.expected_close_date <= close_before)
    if close_after:
        stmt = stmt.where(Opportunity.expected_close_date >= close_after)
    if q:
        like = like_pattern(q)
        lead_hit = exists().where(
            Lead.workspace_id == ctx.workspace_id,
            Lead.id == Opportunity.lead_id,
            or_(
                func.lower(Lead.title).like(like, escape="\\"),
                exists().where(
                    Company.workspace_id == ctx.workspace_id,
                    Company.id == Lead.company_id,
                    func.lower(Company.name).like(like, escape="\\"),
                ),
            ),
        )
        stmt = stmt.where(or_(func.lower(Opportunity.title).like(like, escape="\\"), lead_hit))
    rows, total = paginate(
        db, stmt, params, allowed_sort=_SORT, default_sort="-updated_at", tie_breaker=Opportunity.id
    )
    return Page[OpportunityOut](
        items=svc.opportunity_outs(db, ctx, rows),
        total=total,
        limit=params.limit,
        offset=params.offset,
    )


@router.post(
    "",
    response_model=OpportunityOut,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
    summary="Create an opportunity from a lead",
)
def create_opportunity(
    body: OpportunityCreate, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> OpportunityOut:
    require_owner(ctx)
    opp = svc.create_opportunity(db, ctx, body)
    audit_event(db, ctx, request, settings, "pipeline.opportunity_created", "opportunity", opp.id)
    db.commit()
    return _out(db, ctx, opp)


@router.get(
    "/{opportunity_id}",
    response_model=OpportunityOut,
    responses=ERRORS,
    summary="Get an opportunity",
)
def get_opportunity(opportunity_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep) -> OpportunityOut:
    return _out(db, ctx, _get(db, ctx, opportunity_id))


@router.patch(
    "/{opportunity_id}",
    response_model=OpportunityOut,
    responses=ERRORS,
    summary="Edit an opportunity",
)
def update_opportunity(
    opportunity_id: uuid.UUID,
    body: OpportunityPatch,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
) -> OpportunityOut:
    require_owner(ctx)
    opp = _get(db, ctx, opportunity_id)
    fields = svc.update_opportunity(db, ctx, opp, body)
    audit_event(
        db,
        ctx,
        request,
        settings,
        "pipeline.opportunity_updated",
        "opportunity",
        opp.id,
        fields=fields,
    )
    db.commit()
    return _out(db, ctx, opp)


@router.post(
    "/{opportunity_id}/move",
    response_model=OpportunityOut,
    responses=ERRORS,
    summary="Move a deal to another stage (won/lost close it; 409 if the board was stale or the deal is closed)",
)
def move_opportunity(
    opportunity_id: uuid.UUID,
    body: OpportunityMove,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
) -> OpportunityOut:
    require_owner(ctx)
    opp, changed = svc.move_opportunity(db, ctx, _get(db, ctx, opportunity_id), body)
    if changed:
        stage = svc.require_stage(db, ctx, body.stage_id)
        audit_event(
            db,
            ctx,
            request,
            settings,
            "pipeline.opportunity_moved",
            "opportunity",
            opp.id,
            to=stage.key,
        )
    db.commit()
    return _out(db, ctx, opp)


@router.post(
    "/{opportunity_id}/reopen",
    response_model=OpportunityOut,
    responses=ERRORS,
    summary="Reopen a won or lost deal into an open stage",
)
def reopen_opportunity(
    opportunity_id: uuid.UUID,
    body: OpportunityReopen,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
) -> OpportunityOut:
    require_owner(ctx)
    opp = svc.reopen_opportunity(db, ctx, _get(db, ctx, opportunity_id), body.stage_id)
    audit_event(db, ctx, request, settings, "pipeline.opportunity_reopened", "opportunity", opp.id)
    db.commit()
    return _out(db, ctx, opp)


def _activity_out(a: Activity) -> ActivityOut:
    return ActivityOut(
        id=a.id,
        kind=a.kind,
        summary=a.summary,
        body=a.body,
        details=a.details or {},
        actor_user_id=a.actor_user_id,
        occurred_at=a.occurred_at,
    )


@router.get(
    "/{opportunity_id}/activities",
    response_model=Page[ActivityOut],
    responses=ERRORS,
    summary="Timeline of this deal (newest first)",
)
def list_activities(
    opportunity_id: uuid.UUID,
    ctx: WorkspaceDep,
    db: DbDep,
    params: Annotated[PageParams, Depends(page_params)],
) -> Page[ActivityOut]:
    opp = _get(db, ctx, opportunity_id)
    rows, total = paginate(
        db,
        scoped_select(Activity, ctx).where(Activity.opportunity_id == opp.id),
        params,
        allowed_sort={"occurred_at": Activity.occurred_at},
        default_sort="-occurred_at",
        tie_breaker=Activity.id,
    )
    return Page[ActivityOut](
        items=[_activity_out(a) for a in rows],
        total=total,
        limit=params.limit,
        offset=params.offset,
    )


@router.post(
    "/{opportunity_id}/activities",
    response_model=ActivityOut,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
    summary="Log a note, call or meeting on this deal (also appears on the lead's timeline)",
)
def add_activity(
    opportunity_id: uuid.UUID,
    body: ActivityCreate,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
) -> ActivityOut:
    require_owner(ctx)
    opp = _get(db, ctx, opportunity_id)
    lead = db.get(Lead, opp.lead_id)
    assert lead is not None
    activity = lead_svc.add_activity(
        db, ctx, lead, body.kind, body.summary, body=body.body, opportunity_id=opp.id
    )
    db.flush()
    audit_event(
        db,
        ctx,
        request,
        settings,
        "pipeline.activity_logged",
        "opportunity",
        opp.id,
        kind=body.kind,
    )
    db.commit()
    return _activity_out(activity)
