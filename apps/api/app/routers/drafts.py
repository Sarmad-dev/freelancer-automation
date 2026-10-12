"""Drafts: create, edit, approve, discard and send. Writes are owner-only and audited without content."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app import audit
from app.api.pagination import Page, PageParams, page_params, paginate
from app.api.scoping import get_scoped_or_404, scoped_select
from app.clock import utcnow
from app.db.models_email import Draft
from app.deps import CredentialsDep, DbDep, LimiterDep, SettingsDep, WorkspaceDep, require_owner
from app.routers._common import ERRORS, audit_event
from app.routers.email import RegistryDep
from app.schemas.drafts import DraftCreate, DraftOut, DraftPatch, ResolveIn, SendIn, SendOut
from app.services import drafts as svc
from app.services.email_out import draft_out

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/drafts", tags=["drafts"])

_SORT = {"updated_at": Draft.updated_at, "created_at": Draft.created_at}


def _get(db: DbDep, ctx: WorkspaceDep, draft_id: uuid.UUID) -> Draft:
    return get_scoped_or_404(
        db, Draft, ctx, draft_id, code="draft_not_found", message="Draft not found."
    )


@router.get("", response_model=Page[DraftOut], responses=ERRORS, summary="List drafts")
def list_drafts(
    ctx: WorkspaceDep,
    db: DbDep,
    params: Annotated[PageParams, Depends(page_params)],
    status_: Annotated[
        Literal["draft", "pending_approval", "approved", "rejected", "sent", "discarded"] | None,
        Query(alias="status"),
    ] = None,
    lead_id: Annotated[uuid.UUID | None, Query()] = None,
    conversation_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[DraftOut]:
    stmt = scoped_select(Draft, ctx)
    if status_:
        stmt = stmt.where(Draft.status == status_)
    if lead_id:
        stmt = stmt.where(Draft.lead_id == lead_id)
    if conversation_id:
        stmt = stmt.where(Draft.conversation_id == conversation_id)
    rows, total = paginate(
        db, stmt, params, allowed_sort=_SORT, default_sort="-updated_at", tie_breaker=Draft.id
    )
    return Page[DraftOut](
        items=[draft_out(db, d) for d in rows],
        total=total,
        limit=params.limit,
        offset=params.offset,
    )


@router.post(
    "",
    response_model=DraftOut,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
    summary="Create a draft",
)
def create_draft(
    body: DraftCreate, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> DraftOut:
    require_owner(ctx)
    draft = svc.create_draft(db, ctx, body)
    audit_event(db, ctx, request, settings, "drafts.created", "draft", draft.id)
    db.commit()
    return draft_out(db, draft)


@router.get("/{draft_id}", response_model=DraftOut, responses=ERRORS, summary="Get a draft")
def get_draft(draft_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep) -> DraftOut:
    return draft_out(db, _get(db, ctx, draft_id))


@router.patch(
    "/{draft_id}",
    response_model=DraftOut,
    responses=ERRORS,
    summary="Edit a draft (this withdraws any approval)",
)
def update_draft(
    draft_id: uuid.UUID,
    body: DraftPatch,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
) -> DraftOut:
    require_owner(ctx)
    draft = _get(db, ctx, draft_id)
    fields = svc.update_draft(db, ctx, draft, body)
    audit_event(db, ctx, request, settings, "drafts.updated", "draft", draft.id, fields=fields)
    db.commit()
    return draft_out(db, draft)


@router.post(
    "/{draft_id}/approve",
    response_model=DraftOut,
    responses=ERRORS,
    summary="Approve exactly this text for sending",
)
def approve_draft(
    draft_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> DraftOut:
    require_owner(ctx)
    draft = _get(db, ctx, draft_id)
    svc.approve(db, ctx, draft, utcnow())
    audit_event(
        db, ctx, request, settings, "drafts.approved", "draft", draft.id, version=draft.version
    )
    db.commit()
    return draft_out(db, draft)


@router.post(
    "/{draft_id}/discard", response_model=DraftOut, responses=ERRORS, summary="Discard a draft"
)
def discard_draft(
    draft_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> DraftOut:
    require_owner(ctx)
    draft = _get(db, ctx, draft_id)
    svc.discard(draft)
    audit_event(db, ctx, request, settings, "drafts.discarded", "draft", draft.id)
    db.commit()
    return draft_out(db, draft)


@router.post(
    "/{draft_id}/send",
    response_model=SendOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        **ERRORS,
        200: {
            "model": SendOut,
            "description": "The idempotency key was already used: the earlier outcome.",
        },
        202: {
            "model": SendOut,
            "description": "The provider did not confirm; the outcome is unknown.",
        },
        429: {"description": "A send or provider rate limit applies; see Retry-After."},
    },
    summary="Send an approved draft (requires approval, no suppression, an idempotency key)",
)
def send_draft(
    draft_id: uuid.UUID,
    body: SendIn,
    response: Response,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
    store: CredentialsDep,
    registry: RegistryDep,
    limiter: LimiterDep,
) -> SendOut:
    require_owner(ctx)
    _get(db, ctx, draft_id)  # 404 before any lock for a foreign id
    result = svc.send_draft(
        db,
        ctx,
        draft_id,
        body.idempotency_key,
        now=utcnow(),
        info=audit.request_info(request, settings),
        settings=settings,
        store=store,
        registry=registry,
        limiter=limiter,
    )
    if result.replayed:
        response.status_code = status.HTTP_200_OK
    elif result.unknown:
        response.status_code = status.HTTP_202_ACCEPTED
    db.refresh(result.draft)
    return SendOut(draft=draft_out(db, result.draft, result.message), replayed=result.replayed)


@router.post(
    "/{draft_id}/resolve-send",
    response_model=DraftOut,
    responses=ERRORS,
    summary="Record what happened after an unconfirmed send",
)
def resolve_send(
    draft_id: uuid.UUID,
    body: ResolveIn,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
) -> DraftOut:
    require_owner(ctx)
    _get(db, ctx, draft_id)
    draft, message = svc.resolve_send(
        db, ctx, draft_id, body.outcome, now=utcnow(), info=audit.request_info(request, settings)
    )
    return draft_out(db, draft, message)
