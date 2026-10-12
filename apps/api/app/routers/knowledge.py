"""Knowledge items: workspace-scoped CRUD with provenance, review lifecycle and version history."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func, or_

from app import audit
from app.api.pagination import Page, PageParams, page_params, paginate
from app.api.scoping import get_scoped_or_404, scoped_select
from app.db.models_crm import KnowledgeItem, KnowledgeItemVersion
from app.deps import DbDep, SettingsDep, WorkspaceDep, require_owner
from app.errors import ErrorResponse
from app.schemas.knowledge import (
    KnowledgeApprove,
    KnowledgeCreate,
    KnowledgeImport,
    KnowledgeImportResult,
    KnowledgeOut,
    KnowledgePatch,
    KnowledgeVersionOut,
)
from app.services import knowledge as svc

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/knowledge", tags=["knowledge"])

_ERR: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}
_SORT = {
    "updated_at": KnowledgeItem.updated_at,
    "created_at": KnowledgeItem.created_at,
    "title": KnowledgeItem.title,
    "status": KnowledgeItem.status,
    "kind": KnowledgeItem.kind,
}
_NOT_FOUND = {"code": "knowledge_not_found", "message": "Knowledge item not found."}


def _get(db: DbDep, ctx: WorkspaceDep, item_id: uuid.UUID) -> KnowledgeItem:
    return get_scoped_or_404(db, KnowledgeItem, ctx, item_id, **_NOT_FOUND)


def _audit(
    db: DbDep,
    ctx: WorkspaceDep,
    request: Request,
    settings: SettingsDep,
    action: str,
    item: KnowledgeItem | None,
    **details: Any,
) -> None:
    audit.record(
        db,
        action,
        info=audit.request_info(request, settings),
        actor_user_id=ctx.user.id,
        workspace_id=ctx.workspace_id,
        target_type="knowledge_item",
        target_id=str(item.id) if item else None,
        details=details,
    )


@router.get("", response_model=Page[KnowledgeOut], responses=_ERR, summary="List knowledge items")
def list_items(
    ctx: WorkspaceDep,
    db: DbDep,
    params: Annotated[PageParams, Depends(page_params)],
    status_filter: Annotated[
        Literal["draft", "pending_review", "approved", "rejected"] | None,
        Query(alias="status", description="Review status."),
    ] = None,
    kind: Annotated[
        Literal["fact", "service", "case_study", "portfolio", "pricing", "other"] | None, Query()
    ] = None,
    source_type: Annotated[Literal["manual", "upload", "extracted"] | None, Query()] = None,
    is_enabled: Annotated[bool | None, Query(description="On/off switch.")] = None,
    q: Annotated[
        str | None, Query(max_length=100, description="Title or content contains.")
    ] = None,
) -> Page[KnowledgeOut]:
    stmt = scoped_select(KnowledgeItem, ctx)
    if status_filter:
        stmt = stmt.where(KnowledgeItem.status == status_filter)
    if kind:
        stmt = stmt.where(KnowledgeItem.kind == kind)
    if source_type:
        stmt = stmt.where(KnowledgeItem.source_type == source_type)
    if is_enabled is not None:
        stmt = stmt.where(KnowledgeItem.is_enabled.is_(is_enabled))
    if q:
        needle = q.casefold().replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        like = f"%{needle}%"
        stmt = stmt.where(
            or_(
                func.lower(KnowledgeItem.title).like(like, escape="\\"),
                func.lower(KnowledgeItem.content).like(like, escape="\\"),
            )
        )
    rows, total = paginate(
        db,
        stmt,
        params,
        allowed_sort=_SORT,
        default_sort="-updated_at",
        tie_breaker=KnowledgeItem.id,
    )
    return Page[KnowledgeOut](
        items=[KnowledgeOut.model_validate(r) for r in rows],
        total=total,
        limit=params.limit,
        offset=params.offset,
    )


@router.get(
    "/stats",
    response_model=dict[str, int],
    responses=_ERR,
    summary="Counts by review status, plus how many approved items are in use or switched off",
)
def stats(ctx: WorkspaceDep, db: DbDep) -> dict[str, int]:
    return svc.status_counts(db, ctx)


@router.post(
    "/import-text",
    response_model=KnowledgeImportResult,
    status_code=status.HTTP_201_CREATED,
    responses=_ERR,
    summary="Paste reference material: split it (no AI) into candidate facts that need review",
)
def import_text(
    body: KnowledgeImport, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> KnowledgeImportResult:
    require_owner(ctx)
    items, skipped, truncated = svc.import_text(
        db, ctx, source_label=body.source_label, text=body.text, kind=body.kind
    )
    _audit(db, ctx, request, settings, "knowledge.imported", None, count=len(items), kind=body.kind)
    db.commit()
    return KnowledgeImportResult(
        created=len(items),
        skipped_duplicates=skipped,
        truncated=truncated,
        items=[KnowledgeOut.model_validate(i) for i in items],
    )


@router.post(
    "",
    response_model=KnowledgeOut,
    status_code=status.HTTP_201_CREATED,
    responses=_ERR,
    summary="Add a knowledge item",
)
def create_item(
    body: KnowledgeCreate, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> KnowledgeItem:
    require_owner(ctx)
    item = svc.create_item(db, ctx, body)
    _audit(
        db, ctx, request, settings, "knowledge.created", item, kind=item.kind, status=item.status
    )
    db.commit()
    return item


@router.get(
    "/{item_id}", response_model=KnowledgeOut, responses=_ERR, summary="Get a knowledge item"
)
def get_item(item_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep) -> KnowledgeItem:
    return _get(db, ctx, item_id)


@router.get(
    "/{item_id}/versions",
    response_model=list[KnowledgeVersionOut],
    responses=_ERR,
    summary="Content history (newest first)",
)
def versions(item_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep) -> list[KnowledgeItemVersion]:
    item = _get(db, ctx, item_id)
    return list(
        db.scalars(
            scoped_select(KnowledgeItemVersion, ctx)
            .where(KnowledgeItemVersion.item_id == item.id)
            .order_by(KnowledgeItemVersion.version.desc())
        )
    )


@router.patch(
    "/{item_id}",
    response_model=KnowledgeOut,
    responses=_ERR,
    summary="Edit an item. Editing approved content sends it back to review; is_enabled only flips the switch",
)
def update_item(
    item_id: uuid.UUID,
    body: KnowledgePatch,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
) -> KnowledgeItem:
    require_owner(ctx)
    item, changed = svc.update_item(db, ctx, _get(db, ctx, item_id), body)
    if changed:
        _audit(
            db,
            ctx,
            request,
            settings,
            "knowledge.updated",
            item,
            fields=changed,
            version=item.version,
        )
    db.commit()
    db.refresh(item)
    return item


@router.post(
    "/{item_id}/approve",
    response_model=KnowledgeOut,
    responses=_ERR,
    summary="Approve exactly the version you reviewed (409 if it changed since)",
)
def approve(
    item_id: uuid.UUID,
    body: KnowledgeApprove,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
) -> KnowledgeItem:
    require_owner(ctx)
    item = svc.approve_item(db, ctx, _get(db, ctx, item_id), body.version)
    _audit(db, ctx, request, settings, "knowledge.approved", item, version=item.version)
    db.commit()
    db.refresh(item)
    return item


@router.post(
    "/{item_id}/reject",
    response_model=KnowledgeOut,
    responses=_ERR,
    summary="Reject an item (kept, never used by AI)",
)
def reject(
    item_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> KnowledgeItem:
    require_owner(ctx)
    item = svc.reject_item(db, ctx, _get(db, ctx, item_id))
    _audit(db, ctx, request, settings, "knowledge.rejected", item, version=item.version)
    db.commit()
    return item


@router.delete(
    "/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_ERR,
    summary="Delete an item and its history",
)
def delete_item(
    item_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> Response:
    require_owner(ctx)
    item = _get(db, ctx, item_id)
    _audit(db, ctx, request, settings, "knowledge.deleted", item, kind=item.kind)
    db.delete(item)  # version history cascades
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
