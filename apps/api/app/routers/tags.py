"""Tags: the reference implementation of the API conventions (docs/API_CONVENTIONS.md).

Pagination/sorting/filtering, workspace scoping through the URL's authorised context, duplicate protection
(case-insensitive, race-safe), PATCH semantics, audit events and the shared error envelope.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app import audit
from app.api.pagination import Page, PageParams, page_params, paginate
from app.api.scoping import get_scoped_or_404, scoped_select
from app.db.models_crm import Tag
from app.deps import DbDep, SettingsDep, WorkspaceDep, require_owner
from app.errors import AppError, ErrorResponse
from app.schemas.crm import TagCreate, TagOut, TagUpdate
from app.schemas.text import single_line

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/tags", tags=["tags"])

_ERR: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}

_SORT = {"name": Tag.name, "created_at": Tag.created_at}


def _normalize(name: str) -> str:
    return single_line(name).casefold()


def _exists(db: DbDep, ctx: WorkspaceDep, name: str, *, exclude: uuid.UUID | None = None) -> bool:
    stmt = scoped_select(Tag, ctx).where(Tag.name_normalized == _normalize(name))
    if exclude is not None:
        stmt = stmt.where(Tag.id != exclude)
    return db.scalar(stmt) is not None


def _duplicate() -> AppError:
    return AppError(
        409,
        "tag_exists",
        "A tag with this name already exists.",
        fields={"name": "Already exists."},
    )


@router.get("", response_model=Page[TagOut], responses=_ERR, summary="List tags")
def list_tags(
    ctx: WorkspaceDep,
    db: DbDep,
    params: Annotated[PageParams, Depends(page_params)],
    q: Annotated[
        str | None, Query(max_length=50, description="Case-insensitive name contains.")
    ] = None,
) -> Page[TagOut]:
    stmt = scoped_select(Tag, ctx)
    if q:
        # Escape LIKE wildcards so user input is matched literally.
        needle = q.casefold().replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        stmt = stmt.where(func.lower(Tag.name).like(f"%{needle}%", escape="\\"))
    rows, total = paginate(
        db, stmt, params, allowed_sort=_SORT, default_sort="name", tie_breaker=Tag.id
    )
    return Page[TagOut](
        items=[TagOut.model_validate(r) for r in rows],
        total=total,
        limit=params.limit,
        offset=params.offset,
    )


@router.post(
    "",
    response_model=TagOut,
    status_code=status.HTTP_201_CREATED,
    responses=_ERR,
    summary="Create a tag",
)
def create_tag(
    body: TagCreate, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> Tag:
    require_owner(ctx)
    if _exists(db, ctx, body.name):
        raise _duplicate()
    tag = Tag(
        workspace_id=ctx.workspace_id,
        name=body.name,
        name_normalized=_normalize(body.name),
        color=body.color,
    )
    db.add(tag)
    try:
        db.flush()
    except (
        IntegrityError
    ) as exc:  # concurrent request won the race; the DB constraint is the source of truth
        db.rollback()
        raise _duplicate() from exc
    audit.record(
        db,
        "crm.tag_created",
        info=audit.request_info(request, settings),
        actor_user_id=ctx.user.id,
        workspace_id=ctx.workspace_id,
        target_type="tag",
        target_id=str(tag.id),
    )
    db.commit()
    return tag


@router.get("/{tag_id}", response_model=TagOut, responses=_ERR, summary="Get a tag")
def get_tag(tag_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep) -> Tag:
    return get_scoped_or_404(db, Tag, ctx, tag_id, code="tag_not_found", message="Tag not found.")


@router.patch("/{tag_id}", response_model=TagOut, responses=_ERR, summary="Update a tag")
def update_tag(
    tag_id: uuid.UUID,
    body: TagUpdate,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
) -> Tag:
    require_owner(ctx)
    tag = get_scoped_or_404(db, Tag, ctx, tag_id, code="tag_not_found", message="Tag not found.")
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is not None:
        if _exists(db, ctx, changes["name"], exclude=tag.id):
            raise _duplicate()
        tag.name = changes["name"]
        tag.name_normalized = _normalize(changes["name"])
    if "color" in changes:
        tag.color = changes["color"]
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise _duplicate() from exc
    audit.record(
        db,
        "crm.tag_updated",
        info=audit.request_info(request, settings),
        actor_user_id=ctx.user.id,
        workspace_id=ctx.workspace_id,
        target_type="tag",
        target_id=str(tag.id),
    )
    db.commit()
    return tag


@router.delete(
    "/{tag_id}", status_code=status.HTTP_204_NO_CONTENT, responses=_ERR, summary="Delete a tag"
)
def delete_tag(
    tag_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> Response:
    require_owner(ctx)
    tag = get_scoped_or_404(db, Tag, ctx, tag_id, code="tag_not_found", message="Tag not found.")
    audit.record(
        db,
        "crm.tag_deleted",
        info=audit.request_info(request, settings),
        actor_user_id=ctx.user.id,
        workspace_id=ctx.workspace_id,
        target_type="tag",
        target_id=str(tag.id),
    )
    db.delete(tag)  # lead_tags rows cascade
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
