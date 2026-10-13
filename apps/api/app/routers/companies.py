"""Companies: list/detail/create/edit/archive (MVP Prompt 6)."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, or_

from app.api.pagination import Page, PageParams, page_params, paginate
from app.api.scoping import get_scoped_or_404, scoped_select
from app.clock import utcnow
from app.db.models_crm import Company
from app.deps import DbDep, SettingsDep, WorkspaceDep, require_owner
from app.routers._common import ERRORS, archive_filter, audit_event, like_pattern, sample_filter
from app.schemas.leads import Archived, CompanyCreate, CompanyOut, CompanyPatch, CompanySize
from app.services import crm

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/companies", tags=["companies"])

_SORT = {
    "name": func.lower(Company.name),
    "created_at": Company.created_at,
    "updated_at": Company.updated_at,
    "industry": Company.industry,
}


def _get(db: DbDep, ctx: WorkspaceDep, company_id: uuid.UUID) -> Company:
    return get_scoped_or_404(
        db, Company, ctx, company_id, code="company_not_found", message="Company not found."
    )


@router.get("", response_model=Page[CompanyOut], responses=ERRORS, summary="List companies")
def list_companies(
    ctx: WorkspaceDep,
    db: DbDep,
    params: Annotated[PageParams, Depends(page_params)],
    q: Annotated[str | None, Query(max_length=100, description="Name or website contains.")] = None,
    industry: Annotated[str | None, Query(max_length=100)] = None,
    size_label: Annotated[CompanySize | None, Query()] = None,
    archived: Annotated[Archived, Query()] = "active",
    sample: Annotated[Literal["only", "exclude"] | None, Query()] = None,
) -> Page[CompanyOut]:
    stmt = archive_filter(scoped_select(Company, ctx), Company, archived)
    stmt = sample_filter(stmt, Company, sample)
    if q:
        like = like_pattern(q)
        stmt = stmt.where(
            or_(
                func.lower(Company.name).like(like, escape="\\"),
                func.lower(func.coalesce(Company.domain, "")).like(like, escape="\\"),
            )
        )
    if industry:
        stmt = stmt.where(
            func.lower(func.coalesce(Company.industry, "")).like(
                like_pattern(industry), escape="\\"
            )
        )
    if size_label:
        stmt = stmt.where(Company.size_label == size_label)
    rows, total = paginate(
        db, stmt, params, allowed_sort=_SORT, default_sort="name", tie_breaker=Company.id
    )
    return Page[CompanyOut](
        items=crm.company_outs(db, ctx, rows), total=total, limit=params.limit, offset=params.offset
    )


@router.post(
    "",
    response_model=CompanyOut,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
    summary="Create a company",
)
def create_company(
    body: CompanyCreate, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> CompanyOut:
    require_owner(ctx)
    company = crm.create_company(db, ctx, body)
    audit_event(db, ctx, request, settings, "crm.company_created", "company", company.id)
    db.commit()
    return crm.company_outs(db, ctx, [company])[0]


@router.get("/{company_id}", response_model=CompanyOut, responses=ERRORS, summary="Get a company")
def get_company(company_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep) -> CompanyOut:
    return crm.company_outs(db, ctx, [_get(db, ctx, company_id)])[0]


@router.patch(
    "/{company_id}", response_model=CompanyOut, responses=ERRORS, summary="Edit a company"
)
def update_company(
    company_id: uuid.UUID,
    body: CompanyPatch,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
) -> CompanyOut:
    require_owner(ctx)
    company = _get(db, ctx, company_id)
    fields = crm.update_company(db, ctx, company, body)
    audit_event(
        db, ctx, request, settings, "crm.company_updated", "company", company.id, fields=fields
    )
    db.commit()
    return crm.company_outs(db, ctx, [company])[0]


@router.post(
    "/{company_id}/archive",
    response_model=CompanyOut,
    responses=ERRORS,
    summary="Archive a company (hidden from lists; leads and contacts keep their link)",
)
def archive_company(
    company_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> CompanyOut:
    require_owner(ctx)
    company = _get(db, ctx, company_id)
    if company.archived_at is None:
        company.archived_at = utcnow()
        audit_event(db, ctx, request, settings, "crm.company_archived", "company", company.id)
        db.commit()
    return crm.company_outs(db, ctx, [company])[0]


@router.post(
    "/{company_id}/restore",
    response_model=CompanyOut,
    responses=ERRORS,
    summary="Restore a company",
)
def restore_company(
    company_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> CompanyOut:
    require_owner(ctx)
    company = _get(db, ctx, company_id)
    if company.archived_at is not None:
        company.archived_at = None
        audit_event(db, ctx, request, settings, "crm.company_restored", "company", company.id)
        db.commit()
    return crm.company_outs(db, ctx, [company])[0]
