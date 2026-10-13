"""CSV import wizard backend (MVP Prompt 6): preview, import, history and the downloadable error report."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.pagination import Page, PageParams, page_params, paginate
from app.api.scoping import get_scoped_or_404, scoped_select
from app.db.models_crm import ImportJob
from app.deps import DbDep, SettingsDep, WorkspaceDep, require_owner
from app.errors import AppError
from app.routers._common import ERRORS, audit_event
from app.schemas.imports import (
    ImportCounts,
    ImportErrorOut,
    ImportJobOut,
    ImportMapping,
    ImportPreview,
    ImportPreviewRequest,
    ImportRequest,
    ImportRowPreview,
)
from app.services import lead_import
from app.services.csvio import CsvProblem, ParsedCsv, parse, to_csv
from app.services.fit_scoring import Scorer

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/imports", tags=["imports"])

PREVIEW_ROWS = 25
PREVIEW_ERRORS = 100
_CSV_RESPONSE: dict[int | str, dict[str, Any]] = {
    200: {"content": {"text/csv": {"schema": {"type": "string"}}}, "description": "CSV file"}
}


def _parse(content: str) -> ParsedCsv:
    try:
        return parse(content)
    except CsvProblem as exc:
        raise AppError(422, "invalid_csv", str(exc), fields={"content": str(exc)}) from exc


def _job_out(job: ImportJob, suppressed: int | None = None) -> ImportJobOut:
    return ImportJobOut(
        id=job.id,
        filename=job.filename,
        status=job.status,
        duplicate_strategy=job.duplicate_strategy,
        total_rows=job.total_rows,
        created_count=job.created_count,
        updated_count=job.updated_count,
        skipped_count=job.skipped_count,
        error_count=job.error_count,
        errors_truncated=job.errors_truncated,
        suppressed=suppressed,
        created_at=job.created_at,
    )


@router.post(
    "/preview",
    response_model=ImportPreview,
    responses=ERRORS,
    summary="Check a CSV and show what an import would do. Nothing is saved.",
)
def preview(body: ImportPreviewRequest, ctx: WorkspaceDep, db: DbDep) -> ImportPreview:
    require_owner(ctx)
    parsed = _parse(body.content)
    suggested = ImportMapping.model_validate(lead_import.suggest_mapping(parsed.headers))
    mapping = body.mapping or suggested
    resolved, problem = lead_import.resolve_mapping(mapping.model_dump(), parsed.headers)
    empty = ImportCounts(create=0, update=0, skip_duplicate=0, error=0)
    if problem:
        return ImportPreview(
            delimiter=parsed.delimiter,
            headers=[h for h in parsed.headers if h],
            suggested_mapping=suggested,
            mapping=mapping,
            mapping_problem=problem,
            total_rows=len(parsed.rows),
            counts=empty,
            suppressed=0,
            rows=[],
            errors=[],
            errors_truncated=False,
        )
    try:
        result = lead_import.run_import(
            db,
            ctx,
            parsed,
            resolved,
            strategy=body.duplicate_strategy,
            filename="preview",
            scorer=Scorer.load(db, ctx),
            job=None,
        )
    finally:
        db.rollback()  # a preview never changes anything
    return ImportPreview(
        delimiter=parsed.delimiter,
        headers=[h for h in parsed.headers if h],
        suggested_mapping=suggested,
        mapping=mapping,
        mapping_problem=None,
        total_rows=len(parsed.rows),
        counts=ImportCounts(
            create=result.created,
            update=result.updated,
            skip_duplicate=result.skipped,
            error=result.failed,
        ),
        suppressed=result.suppressed,
        rows=[
            ImportRowPreview(
                row=o.number,
                action=o.action,
                values={
                    k: (", ".join(v) if isinstance(v, list) else str(v))[:80]
                    for k, v in o.values.items()
                },
                issues=o.issues,
                warnings=o.warnings,
                note=o.note,
            )
            for o in result.outcomes[:PREVIEW_ROWS]
        ],
        errors=[ImportErrorOut(**e) for e in result.errors[:PREVIEW_ERRORS]],
        errors_truncated=result.errors_truncated or len(result.errors) > PREVIEW_ERRORS,
    )


@router.post(
    "",
    response_model=ImportJobOut,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
    summary="Import the CSV. Valid rows are saved; problem rows are skipped and listed in the error report.",
)
def run_import(
    body: ImportRequest, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> ImportJobOut:
    require_owner(ctx)
    parsed = _parse(body.content)
    mapping = body.mapping.model_dump()
    resolved, problem = lead_import.resolve_mapping(mapping, parsed.headers)
    if problem:
        raise AppError(422, "invalid_mapping", problem, fields={"mapping": problem})
    job = ImportJob(
        workspace_id=ctx.workspace_id,
        filename=body.filename,
        duplicate_strategy=body.duplicate_strategy,
        mapping={k: v for k, v in mapping.items() if v},
        total_rows=len(parsed.rows),
        created_by_user_id=ctx.user.id,
    )
    db.add(job)
    db.flush()
    result = lead_import.run_import(
        db,
        ctx,
        parsed,
        resolved,
        strategy=body.duplicate_strategy,
        filename=body.filename,
        scorer=Scorer.load(db, ctx),
        job=job,
    )
    job.created_count, job.updated_count = result.created, result.updated
    job.skipped_count, job.error_count = result.skipped, result.failed
    job.errors, job.errors_truncated = result.errors, result.errors_truncated
    audit_event(
        db,
        ctx,
        request,
        settings,
        "leads.imported",
        "import_job",
        job.id,
        created=result.created,
        updated=result.updated,
        skipped=result.skipped,
        errors=result.failed,
        strategy=body.duplicate_strategy,
    )
    db.commit()
    return _job_out(job, result.suppressed)


@router.get("", response_model=Page[ImportJobOut], responses=ERRORS, summary="Import history")
def list_imports(
    ctx: WorkspaceDep, db: DbDep, params: Annotated[PageParams, Depends(page_params)]
) -> Page[ImportJobOut]:
    rows, total = paginate(
        db,
        scoped_select(ImportJob, ctx),
        params,
        allowed_sort={"created_at": ImportJob.created_at},
        default_sort="-created_at",
        tie_breaker=ImportJob.id,
    )
    return Page[ImportJobOut](
        items=[_job_out(j) for j in rows], total=total, limit=params.limit, offset=params.offset
    )


def _get(db: DbDep, ctx: WorkspaceDep, job_id: uuid.UUID) -> ImportJob:
    return get_scoped_or_404(
        db, ImportJob, ctx, job_id, code="import_not_found", message="Import not found."
    )


@router.get("/{job_id}", response_model=ImportJobOut, responses=ERRORS, summary="Get an import")
def get_import(job_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep) -> ImportJobOut:
    return _job_out(_get(db, ctx, job_id))


@router.get(
    "/{job_id}/errors.csv",
    response_class=Response,
    responses={**ERRORS, **_CSV_RESPONSE},
    summary="Download the error report (rows that failed validation or were skipped as duplicates)",
)
def error_report(job_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep) -> Response:
    require_owner(ctx)
    job = _get(db, ctx, job_id)
    rows: list[list[object]] = [
        [e["row"], e["kind"], e["column"], e["message"], e["value"]] for e in job.errors
    ]
    body = to_csv(["row", "type", "column", "problem", "value"], rows)
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="import-{str(job.id)[:8]}-errors.csv"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
