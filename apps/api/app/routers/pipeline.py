from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.pagination import Page, PageParams, page_params, paginate
from app.api.scoping import scoped_select
from app.db.models_crm import PipelineStage
from app.deps import DbDep, WorkspaceDep
from app.errors import ErrorResponse
from app.schemas.crm import PipelineStageOut
from app.schemas.pipeline import PipelineBoard
from app.services import opportunities as opportunity_svc

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/pipeline", tags=["pipeline"])

_ERR: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
}


@router.get(
    "/stages",
    response_model=Page[PipelineStageOut],
    responses=_ERR,
    summary="List pipeline stages in order",
)
def list_stages(
    ctx: WorkspaceDep, db: DbDep, params: Annotated[PageParams, Depends(page_params)]
) -> Page[PipelineStageOut]:
    rows, total = paginate(
        db,
        scoped_select(PipelineStage, ctx),
        params,
        allowed_sort={"position": PipelineStage.position, "name": PipelineStage.name},
        default_sort="position",
        tie_breaker=PipelineStage.id,
    )
    return Page[PipelineStageOut](
        items=[PipelineStageOut.model_validate(r) for r in rows],
        total=total,
        limit=params.limit,
        offset=params.offset,
    )


@router.get(
    "/board",
    response_model=PipelineBoard,
    responses=_ERR,
    summary="Every stage with its deals (newest first, up to 50 per column), counts and per-currency totals",
)
def pipeline_board(ctx: WorkspaceDep, db: DbDep) -> PipelineBoard:
    return opportunity_svc.board(db, ctx)
