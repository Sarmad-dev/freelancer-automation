from __future__ import annotations

from typing import Annotated, Literal

import redis
from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import __version__
from app.config import Settings, get_settings
from app.db.session import get_session

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str
    environment: str


class DependencyCheck(BaseModel):
    status: Literal["ok", "error"]
    detail: str | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, DependencyCheck]


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    """Process is up. Does not touch dependencies."""
    return HealthResponse(
        status="ok",
        service="freelancer-os-api",
        version=__version__,
        environment=settings.app_env,
    )


def _check_database(session: Session) -> DependencyCheck:
    try:
        session.execute(text("SELECT 1"))
        return DependencyCheck(status="ok")
    except Exception as exc:  # noqa: BLE001 - report any failure as not ready
        return DependencyCheck(status="error", detail=type(exc).__name__)


def _check_redis(url: str) -> DependencyCheck:
    try:
        client = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        client.ping()
        return DependencyCheck(status="ok")
    except Exception as exc:  # noqa: BLE001
        return DependencyCheck(status="error", detail=type(exc).__name__)


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    responses={503: {"model": ReadinessResponse}},
)
def ready(
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ReadinessResponse:
    """Dependencies (PostgreSQL, Redis) are reachable. Error details never include URLs."""
    checks = {
        "database": _check_database(session),
        "redis": _check_redis(settings.redis_url),
    }
    ok = all(c.status == "ok" for c in checks.values())
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ready" if ok else "not_ready", checks=checks)
