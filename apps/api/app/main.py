from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config import Settings, get_settings
from app.routers import health

logger = logging.getLogger("freelancer_os")
_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")


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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Request-ID"],
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

    app.include_router(health.router)
    return app


def _build() -> FastAPI:
    return create_app()


app = _build()
