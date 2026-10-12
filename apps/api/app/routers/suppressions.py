"""The do-not-contact list: read for every member, changes owner-only and audited by count/hash, never by address."""

from __future__ import annotations

import hashlib
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.pagination import Page, PageParams, page_params, paginate
from app.api.scoping import get_scoped_or_404, scoped_select
from app.db.models_email import SuppressionEntry
from app.deps import DbDep, SettingsDep, WorkspaceDep, require_owner
from app.routers._common import ERRORS, audit_event
from app.schemas.email import SuppressionCreate, SuppressionOut
from app.services import suppression as svc

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/suppressions", tags=["suppression"])

_SORT = {"created_at": SuppressionEntry.created_at, "email": SuppressionEntry.email_normalized}


def _out(e: SuppressionEntry) -> SuppressionOut:
    return SuppressionOut(
        id=e.id,
        email=e.email_normalized,
        reason=e.reason,
        source=e.source,
        note=e.note,
        created_at=e.created_at,
    )


def _hash(email: str) -> str:
    return hashlib.sha256(email.encode()).hexdigest()[:16]


@router.get(
    "", response_model=Page[SuppressionOut], responses=ERRORS, summary="Do-not-contact list"
)
def list_suppressions(
    ctx: WorkspaceDep, db: DbDep, params: Annotated[PageParams, Depends(page_params)]
) -> Page[SuppressionOut]:
    rows, total = paginate(
        db, scoped_select(SuppressionEntry, ctx), params, allowed_sort=_SORT,
        default_sort="-created_at", tie_breaker=SuppressionEntry.id,
    )  # fmt: skip
    return Page[SuppressionOut](
        items=[_out(r) for r in rows], total=total, limit=params.limit, offset=params.offset
    )


@router.post(
    "",
    response_model=SuppressionOut,
    status_code=status.HTTP_201_CREATED,
    responses={**ERRORS, 200: {"model": SuppressionOut, "description": "Already on the list."}},
    summary="Add an address to the do-not-contact list",
)
def add_suppression(
    body: SuppressionCreate,
    response: Response,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
) -> SuppressionOut:
    require_owner(ctx)
    entry, created = svc.add(
        db,
        ctx.workspace_id,
        body.email,
        body.reason,
        source="manual",
        note=body.note,
        user_id=ctx.user.id,
    )
    if created:
        audit_event(
            db, ctx, request, settings, "suppression.added", "suppression", entry.id,
            email_hash=_hash(entry.email_normalized), reason=body.reason,
        )  # fmt: skip
        db.commit()
    else:
        response.status_code = status.HTTP_200_OK
    return _out(entry)


@router.delete(
    "/{suppression_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=ERRORS,
    summary="Remove an address from the list",
)
def remove_suppression(
    suppression_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> Response:
    require_owner(ctx)
    entry = get_scoped_or_404(
        db,
        SuppressionEntry,
        ctx,
        suppression_id,
        code="suppression_not_found",
        message="Entry not found.",
    )
    audit_event(
        db, ctx, request, settings, "suppression.removed", "suppression", entry.id,
        email_hash=_hash(entry.email_normalized),
    )  # fmt: skip
    db.delete(entry)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
