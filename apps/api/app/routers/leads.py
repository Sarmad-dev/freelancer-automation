"""Leads: list/detail/create/edit/archive, tags, activity timeline, fit score and CSV export (MVP Prompt 6)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response, status
from sqlalchemy import Select, exists, func, or_, select

from app.api.pagination import Page, PageParams, page_params, paginate
from app.api.scoping import get_scoped_or_404, scoped_select
from app.clock import utcnow
from app.db.models_crm import Activity, Company, Contact, Lead, LeadTag
from app.deps import DbDep, SettingsDep, WorkspaceContext, WorkspaceDep, require_owner
from app.errors import AppError
from app.routers._common import ERRORS, archive_filter, audit_event, like_pattern, sample_filter
from app.schemas.leads import (
    ActivityCreate,
    ActivityOut,
    Archived,
    BulkTagRequest,
    BulkTagResult,
    LeadCreate,
    LeadDetail,
    LeadOut,
    LeadPatch,
    LeadStatus,
    LeadTagsPut,
)
from app.services import leads as svc
from app.services.fit_scoring import BAND_POSSIBLE, BAND_STRONG, Scorer
from app.services.lead_export import MAX_EXPORT_ROWS, export_csv
from app.workflows import engine as workflow_engine
from app.workflows import events as workflow_events

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/leads", tags=["leads"])

FitFilter = Literal["strong", "possible", "weak", "unscored"]
_SORT = {
    "updated_at": Lead.updated_at,
    "created_at": Lead.created_at,
    "title": func.lower(Lead.title),
    "status": Lead.status,
    "fit_score": Lead.fit_score,
    "last_activity_at": Lead.last_activity_at,
    "next_action_at": Lead.next_action_at,
}
_CSV_RESPONSE: dict[int | str, dict[str, Any]] = {
    200: {"content": {"text/csv": {"schema": {"type": "string"}}}, "description": "CSV file"}
}


@dataclass(frozen=True)
class LeadFilters:
    q: str | None
    status: list[str] | None
    stage_id: uuid.UUID | None
    tag_id: uuid.UUID | None
    company_id: uuid.UUID | None
    contact_id: uuid.UUID | None
    source: str | None
    industry: str | None
    fit: str | None
    archived: str
    sample: str | None
    overdue: bool | None
    has_next_action: bool | None


def lead_filters(
    q: Annotated[
        str | None, Query(max_length=100, description="Title, notes, company or contact contains.")
    ] = None,
    status: Annotated[list[LeadStatus] | None, Query(description="One or more statuses.")] = None,
    stage_id: Annotated[uuid.UUID | None, Query()] = None,
    tag_id: Annotated[uuid.UUID | None, Query()] = None,
    company_id: Annotated[uuid.UUID | None, Query()] = None,
    contact_id: Annotated[uuid.UUID | None, Query()] = None,
    source: Annotated[str | None, Query(max_length=100)] = None,
    industry: Annotated[str | None, Query(max_length=100, description="Industry contains.")] = None,
    fit: Annotated[
        FitFilter | None,
        Query(description="strong >= 70, possible 45-69, weak < 45, unscored = no score yet."),
    ] = None,
    archived: Annotated[Archived, Query()] = "active",
    sample: Annotated[Literal["only", "exclude"] | None, Query()] = None,
    overdue: Annotated[bool | None, Query(description="Next action is past due.")] = None,
    has_next_action: Annotated[bool | None, Query()] = None,
) -> LeadFilters:
    return LeadFilters(
        q, list(status) if status else None, stage_id, tag_id, company_id, contact_id, source, industry, fit,
        archived, sample, overdue, has_next_action,
    )  # fmt: skip


FiltersDep = Annotated[LeadFilters, Depends(lead_filters)]


def _filtered(ctx: WorkspaceContext, f: LeadFilters) -> Select[tuple[Lead]]:
    stmt = archive_filter(scoped_select(Lead, ctx), Lead, f.archived)
    stmt = sample_filter(stmt, Lead, f.sample)
    if f.q:
        like = like_pattern(f.q)
        company_hit = exists().where(
            Company.workspace_id == ctx.workspace_id,
            Company.id == Lead.company_id,
            func.lower(Company.name).like(like, escape="\\"),
        )
        contact_hit = exists().where(
            Contact.workspace_id == ctx.workspace_id,
            Contact.id == Lead.contact_id,
            or_(
                func.lower(Contact.full_name).like(like, escape="\\"),
                func.lower(func.coalesce(Contact.email_normalized, "")).like(like, escape="\\"),
            ),
        )
        stmt = stmt.where(
            or_(
                func.lower(Lead.title).like(like, escape="\\"),
                func.lower(func.coalesce(Lead.notes, "")).like(like, escape="\\"),
                company_hit,
                contact_hit,
            )
        )
    if f.status:
        stmt = stmt.where(Lead.status.in_(f.status))
    if f.stage_id:
        stmt = stmt.where(Lead.stage_id == f.stage_id)
    if f.tag_id:
        stmt = stmt.where(
            Lead.id.in_(
                select(LeadTag.lead_id).where(
                    LeadTag.workspace_id == ctx.workspace_id, LeadTag.tag_id == f.tag_id
                )
            )
        )
    if f.company_id:
        stmt = stmt.where(Lead.company_id == f.company_id)
    if f.contact_id:
        stmt = stmt.where(Lead.contact_id == f.contact_id)
    if f.source:
        stmt = stmt.where(func.lower(func.coalesce(Lead.source, "")) == f.source.casefold())
    if f.industry:
        stmt = stmt.where(
            func.lower(func.coalesce(Lead.industry, "")).like(like_pattern(f.industry), escape="\\")
        )
    if f.fit == "strong":
        stmt = stmt.where(Lead.fit_score >= BAND_STRONG)
    elif f.fit == "possible":
        stmt = stmt.where(Lead.fit_score >= BAND_POSSIBLE, Lead.fit_score < BAND_STRONG)
    elif f.fit == "weak":
        stmt = stmt.where(Lead.fit_score < BAND_POSSIBLE)
    elif f.fit == "unscored":
        stmt = stmt.where(Lead.fit_score.is_(None))
    if f.overdue:
        stmt = stmt.where(
            Lead.next_action_at < utcnow(),
            Lead.status.not_in(("won", "lost")),
            Lead.archived_at.is_(None),
        )
    if f.has_next_action is True:
        stmt = stmt.where(Lead.next_action.is_not(None))
    elif f.has_next_action is False:
        stmt = stmt.where(Lead.next_action.is_(None))
    return stmt


def _get(db: DbDep, ctx: WorkspaceDep, lead_id: uuid.UUID) -> Lead:
    return get_scoped_or_404(
        db, Lead, ctx, lead_id, code="lead_not_found", message="Lead not found."
    )


@router.get("", response_model=Page[LeadOut], responses=ERRORS, summary="List leads")
def list_leads(
    ctx: WorkspaceDep,
    db: DbDep,
    params: Annotated[PageParams, Depends(page_params)],
    filters: FiltersDep,
) -> Page[LeadOut]:
    rows, total = paginate(
        db,
        _filtered(ctx, filters),
        params,
        allowed_sort=_SORT,
        default_sort="-updated_at",
        tie_breaker=Lead.id,
    )
    return Page[LeadOut](
        items=svc.lead_outs(db, ctx, rows), total=total, limit=params.limit, offset=params.offset
    )


@router.get(
    "/export",
    response_class=Response,
    responses={**ERRORS, **_CSV_RESPONSE},
    summary="Export the filtered leads as CSV (owner only)",
)
def export_leads(
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
    filters: FiltersDep,
    sort: Annotated[str | None, Query(max_length=100)] = None,
) -> Response:
    require_owner(ctx)
    stmt = _filtered(ctx, filters)
    rows, total = paginate(
        db,
        stmt,
        PageParams(limit=MAX_EXPORT_ROWS, offset=0, sort=sort),
        allowed_sort=_SORT,
        default_sort="-updated_at",
        tie_breaker=Lead.id,
    )
    if total > MAX_EXPORT_ROWS:
        raise AppError(
            422,
            "export_too_large",
            f"Too many leads to export at once ({total:,}). Narrow the filters to {MAX_EXPORT_ROWS:,} or fewer.",
        )
    body = export_csv(db, ctx, rows)
    audit_event(db, ctx, request, settings, "leads.exported", "lead", None, count=len(rows))
    db.commit()
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="leads-{date.today().isoformat()}.csv"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "",
    response_model=LeadDetail,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
    summary="Create a lead (manual entry; no external source needed)",
)
def create_lead(
    body: LeadCreate,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
    background: BackgroundTasks,
) -> LeadDetail:
    require_owner(ctx)
    scorer = Scorer.load(db, ctx)
    lead = svc.create_lead(db, ctx, body, scorer)
    audit_event(db, ctx, request, settings, "leads.created", "lead", lead.id)
    queued = workflow_events.emit(
        db, settings, ctx.workspace_id, "lead_created", "lead", lead.id, str(lead.id), utcnow()
    )
    db.commit()
    if queued:  # workflows listening for new leads run after the response, never inside it
        background.add_task(workflow_engine.run_worker, request.app, workspace_id=ctx.workspace_id)
    return svc.lead_detail(db, ctx, lead, scorer)


@router.post(
    "/bulk-tags",
    response_model=BulkTagResult,
    responses=ERRORS,
    summary="Add and/or remove tags on many leads",
)
def bulk_tag(
    body: BulkTagRequest, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> BulkTagResult:
    require_owner(ctx)
    leads, added, removed = svc.bulk_tags(
        db, ctx, body.lead_ids, body.add_tag_ids, body.remove_tag_ids
    )
    audit_event(db, ctx, request, settings, "leads.bulk_tagged", "lead", None, count=leads)
    db.commit()
    return BulkTagResult(leads=leads, tags_added=added, tags_removed=removed)


@router.get("/{lead_id}", response_model=LeadDetail, responses=ERRORS, summary="Get a lead")
def get_lead(lead_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep) -> LeadDetail:
    lead = _get(db, ctx, lead_id)
    return svc.lead_detail(db, ctx, lead, Scorer.load(db, ctx))


@router.patch("/{lead_id}", response_model=LeadDetail, responses=ERRORS, summary="Edit a lead")
def update_lead(
    lead_id: uuid.UUID,
    body: LeadPatch,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
) -> LeadDetail:
    require_owner(ctx)
    lead = _get(db, ctx, lead_id)
    scorer = Scorer.load(db, ctx)
    fields = svc.update_lead(db, ctx, lead, body, scorer)
    audit_event(db, ctx, request, settings, "leads.updated", "lead", lead.id, fields=fields)
    db.commit()
    return svc.lead_detail(db, ctx, lead, scorer)


@router.post(
    "/{lead_id}/archive", response_model=LeadDetail, responses=ERRORS, summary="Archive a lead"
)
def archive_lead(
    lead_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> LeadDetail:
    require_owner(ctx)
    lead = _get(db, ctx, lead_id)
    if lead.archived_at is None:
        lead.archived_at = utcnow()
        svc.add_activity(db, ctx, lead, "system", "Lead archived", bump=False)
        audit_event(db, ctx, request, settings, "leads.archived", "lead", lead.id)
        db.commit()
    return svc.lead_detail(db, ctx, lead, Scorer.load(db, ctx))


@router.post(
    "/{lead_id}/restore", response_model=LeadDetail, responses=ERRORS, summary="Restore a lead"
)
def restore_lead(
    lead_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> LeadDetail:
    require_owner(ctx)
    lead = _get(db, ctx, lead_id)
    if lead.archived_at is not None:
        lead.archived_at = None
        svc.add_activity(db, ctx, lead, "system", "Lead restored", bump=False)
        audit_event(db, ctx, request, settings, "leads.restored", "lead", lead.id)
        db.commit()
    return svc.lead_detail(db, ctx, lead, Scorer.load(db, ctx))


@router.put(
    "/{lead_id}/tags", response_model=LeadDetail, responses=ERRORS, summary="Replace a lead's tags"
)
def put_tags(
    lead_id: uuid.UUID,
    body: LeadTagsPut,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
) -> LeadDetail:
    require_owner(ctx)
    lead = _get(db, ctx, lead_id)
    svc.set_tags(db, ctx, lead, body.tag_ids)
    audit_event(
        db, ctx, request, settings, "leads.tagged", "lead", lead.id, count=len(body.tag_ids)
    )
    db.commit()
    return svc.lead_detail(db, ctx, lead, Scorer.load(db, ctx))


@router.post(
    "/{lead_id}/score",
    response_model=LeadDetail,
    responses=ERRORS,
    summary="Recompute the fit score with the current criteria and profile",
)
def rescore_lead(
    lead_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> LeadDetail:
    require_owner(ctx)
    lead = _get(db, ctx, lead_id)
    scorer = Scorer.load(db, ctx)
    company = db.get(Company, lead.company_id) if lead.company_id else None
    scorer.apply(lead, company)
    audit_event(db, ctx, request, settings, "leads.scored", "lead", lead.id)
    db.commit()
    return svc.lead_detail(db, ctx, lead, scorer)


@router.get(
    "/{lead_id}/activities",
    response_model=Page[ActivityOut],
    responses=ERRORS,
    summary="Activity timeline (newest first)",
)
def list_activities(
    lead_id: uuid.UUID,
    ctx: WorkspaceDep,
    db: DbDep,
    params: Annotated[PageParams, Depends(page_params)],
) -> Page[ActivityOut]:
    lead = _get(db, ctx, lead_id)
    rows, total = paginate(
        db,
        scoped_select(Activity, ctx).where(Activity.lead_id == lead.id),
        params,
        allowed_sort={"occurred_at": Activity.occurred_at},
        default_sort="-occurred_at",
        tie_breaker=Activity.id,
    )
    return Page[ActivityOut](
        items=[
            ActivityOut(
                id=a.id,
                kind=a.kind,
                summary=a.summary,
                body=a.body,
                details=a.details or {},
                actor_user_id=a.actor_user_id,
                occurred_at=a.occurred_at,
            )
            for a in rows
        ],
        total=total,
        limit=params.limit,
        offset=params.offset,
    )


@router.post(
    "/{lead_id}/activities",
    response_model=ActivityOut,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
    summary="Log a note, call or meeting",
)
def add_activity(
    lead_id: uuid.UUID,
    body: ActivityCreate,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
) -> ActivityOut:
    require_owner(ctx)
    lead = _get(db, ctx, lead_id)
    a = svc.add_activity(db, ctx, lead, body.kind, body.summary, body=body.body)
    db.flush()
    audit_event(
        db, ctx, request, settings, "leads.activity_logged", "lead", lead.id, kind=body.kind
    )
    db.commit()
    return ActivityOut(
        id=a.id,
        kind=a.kind,
        summary=a.summary,
        body=a.body,
        details=a.details or {},
        actor_user_id=a.actor_user_id,
        occurred_at=a.occurred_at,
    )
