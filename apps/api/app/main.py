from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.ai.factory import build_provider
from app.config import Settings, get_settings
from app.errors import install_error_handlers
from app.mailbox.registry import build_registry
from app.mailer import ConsoleMailer, DisabledMailer, Mailer
from app.ratelimit import MemoryRateLimiter, RateLimiter, RedisRateLimiter
from app.routers import (
    ai,
    auth,
    companies,
    contacts,
    drafts,
    email,
    email_oauth,
    fit_scoring,
    health,
    imports,
    knowledge,
    leads,
    notifications,
    opportunities,
    pipeline,
    profile,
    suppressions,
    tags,
    tasks,
    workspaces,
)
from app.security.credentials import build_store
from app.security.csrf import CSRF_HEADER, is_request_allowed

logger = logging.getLogger("freelancer_os")


class RedactOAuthQuery(logging.Filter):
    """The OAuth redirect carries a one-time ``code`` and ``state`` in its query string. Access logs must not keep them."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            target = args[2]
            if "/email/oauth/callback" in target and "?" in target:
                record.args = (*args[:2], target.split("?", 1)[0] + "?[redacted]", *args[3:])
        return True


def _install_log_redaction() -> None:
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactOAuthQuery) for f in access.filters):
        access.addFilter(RedactOAuthQuery())


_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")


def _install_stable_openapi(app: FastAPI) -> None:
    """Make the OpenAPI document independent of the Python version.

    FastAPI takes response descriptions from ``http.HTTPStatus``, and Python 3.13 renamed 422 from
    "Unprocessable Entity" to "Unprocessable Content". Without this, ``pnpm contracts:check`` would
    fail whenever the generating interpreter differs from the committed output.
    """
    original = app.openapi

    def stable_openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = original()
            for path in schema.get("paths", {}).values():
                for operation in path.values():
                    response = operation.get("responses", {}).get("422")
                    if response is not None:
                        response["description"] = "Unprocessable Content"
        return app.openapi_schema or original()

    app.openapi = stable_openapi  # type: ignore[method-assign]


def create_app(settings: Settings | None = None) -> FastAPI:
    # Fails fast with an actionable ConfigError when the environment is invalid.
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    app = FastAPI(
        title="Freelancer OS API",
        version=__version__,
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url=None,
    )
    limiter: RateLimiter = (
        RedisRateLimiter(settings.redis_url)
        if settings.effective_rate_limit_backend == "redis"
        else MemoryRateLimiter()
    )
    mailer: Mailer = (
        ConsoleMailer() if settings.effective_mail_backend == "console" else DisabledMailer()
    )
    app.state.rate_limiter = limiter
    app.state.mailer = mailer
    app.state.ai_provider = build_provider(settings)
    app.state.mailbox = build_registry(settings)
    app.state.credentials = build_store(settings.credential_encryption_keys)
    install_error_handlers(app)
    _install_log_redaction()

    @app.middleware("http")
    async def csrf_guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not is_request_allowed(
            request.method,
            request.headers.get("origin"),
            request.headers.get(CSRF_HEADER),
            settings.cors_origins,
        ):
            return JSONResponse(
                {"error": {"code": "csrf_rejected", "message": "Request origin not allowed."}},
                status_code=403,
            )
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Request-ID", "X-Requested-With"],
    )

    @app.middleware("http")
    async def request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("X-Request-ID", "")
        if not _REQUEST_ID_RE.fullmatch(rid):
            rid = uuid.uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    _install_stable_openapi(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(workspaces.router)
    app.include_router(tags.router)
    app.include_router(pipeline.router)
    app.include_router(profile.router)
    app.include_router(knowledge.router)
    app.include_router(companies.router)
    app.include_router(contacts.router)
    app.include_router(leads.router)
    app.include_router(fit_scoring.router)
    app.include_router(imports.router)
    app.include_router(opportunities.router)
    app.include_router(tasks.router)
    app.include_router(notifications.router)
    app.include_router(ai.router)
    app.include_router(email.router)
    app.include_router(email_oauth.router)
    app.include_router(drafts.router)
    app.include_router(suppressions.router)
    return app


def _build() -> FastAPI:
    return create_app()


app = _build()
