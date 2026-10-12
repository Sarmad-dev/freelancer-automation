"""Contacts: list/detail/create/edit/archive (MVP Prompt 6)."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, or_

from app.api.pagination import Page, PageParams, page_params, paginate
from app.api.scoping import get_scoped_or_404, scoped_select
from app.clock import utcnow
from app.db.models_crm import Contact
from app.deps import DbDep, SettingsDep, WorkspaceDep, require_owner
from app.routers._common import ERRORS, archive_filter, audit_event, like_pattern, sample_filter
from app.schemas.leads import Archived, ContactCreate, ContactOut, ContactPatch
from app.services import crm

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/contacts", tags=["contacts"])

_SORT = {
    "full_name": func.lower(Contact.full_name),
    "created_at": Contact.created_at,
    "updated_at": Contact.updated_at,
    "email": Contact.email,
}


def _get(db: DbDep, ctx: WorkspaceDep, contact_id: uuid.UUID) -> Contact:
    return get_scoped_or_404(
        db, Contact, ctx, contact_id, code="contact_not_found", message="Contact not found."
    )


@router.get("", response_model=Page[ContactOut], responses=ERRORS, summary="List contacts")
def list_contacts(
    ctx: WorkspaceDep,
    db: DbDep,
    params: Annotated[PageParams, Depends(page_params)],
    q: Annotated[
        str | None, Query(max_length=100, description="Name, email or role contains.")
    ] = None,
    company_id: Annotated[uuid.UUID | None, Query()] = None,
    archived: Annotated[Archived, Query()] = "active",
    sample: Annotated[Literal["only", "exclude"] | None, Query()] = None,
) -> Page[ContactOut]:
    stmt = archive_filter(scoped_select(Contact, ctx), Contact, archived)
    stmt = sample_filter(stmt, Contact, sample)
    if q:
        like = like_pattern(q)
        stmt = stmt.where(
            or_(
                func.lower(Contact.full_name).like(like, escape="\\"),
                func.lower(func.coalesce(Contact.email_normalized, "")).like(like, escape="\\"),
                func.lower(func.coalesce(Contact.role_title, "")).like(like, escape="\\"),
            )
        )
    if company_id:
        stmt = stmt.where(Contact.company_id == company_id)
    rows, total = paginate(
        db, stmt, params, allowed_sort=_SORT, default_sort="full_name", tie_breaker=Contact.id
    )
    return Page[ContactOut](
        items=crm.contact_outs(db, ctx, rows), total=total, limit=params.limit, offset=params.offset
    )


@router.post(
    "",
    response_model=ContactOut,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
    summary="Create a contact",
)
def create_contact(
    body: ContactCreate, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> ContactOut:
    require_owner(ctx)
    contact = crm.create_contact(db, ctx, body)
    audit_event(db, ctx, request, settings, "crm.contact_created", "contact", contact.id)
    db.commit()
    return crm.contact_outs(db, ctx, [contact])[0]


@router.get("/{contact_id}", response_model=ContactOut, responses=ERRORS, summary="Get a contact")
def get_contact(contact_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep) -> ContactOut:
    return crm.contact_outs(db, ctx, [_get(db, ctx, contact_id)])[0]


@router.patch(
    "/{contact_id}", response_model=ContactOut, responses=ERRORS, summary="Edit a contact"
)
def update_contact(
    contact_id: uuid.UUID,
    body: ContactPatch,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
) -> ContactOut:
    require_owner(ctx)
    contact = _get(db, ctx, contact_id)
    fields = crm.update_contact(db, ctx, contact, body)
    audit_event(
        db, ctx, request, settings, "crm.contact_updated", "contact", contact.id, fields=fields
    )
    db.commit()
    return crm.contact_outs(db, ctx, [contact])[0]


@router.post(
    "/{contact_id}/archive",
    response_model=ContactOut,
    responses=ERRORS,
    summary="Archive a contact (hidden from lists; leads keep their link)",
)
def archive_contact(
    contact_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> ContactOut:
    require_owner(ctx)
    contact = _get(db, ctx, contact_id)
    if contact.archived_at is None:
        contact.archived_at = utcnow()
        audit_event(db, ctx, request, settings, "crm.contact_archived", "contact", contact.id)
        db.commit()
    return crm.contact_outs(db, ctx, [contact])[0]


@router.post(
    "/{contact_id}/restore",
    response_model=ContactOut,
    responses=ERRORS,
    summary="Restore a contact",
)
def restore_contact(
    contact_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> ContactOut:
    require_owner(ctx)
    contact = _get(db, ctx, contact_id)
    if contact.archived_at is not None:
        contact.archived_at = None
        audit_event(db, ctx, request, settings, "crm.contact_restored", "contact", contact.id)
        db.commit()
    return crm.contact_outs(db, ctx, [contact])[0]
