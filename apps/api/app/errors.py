"""Consistent API error format.

Every error response is ``{"error": {"code", "message", "fields"?}}``. ``code`` is a stable machine
identifier clients can branch on; ``message`` is safe to show to users and never contains internals.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorBody(BaseModel):
    code: str
    message: str
    fields: dict[str, str] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        fields: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.fields = fields
        self.headers = headers or {}


def _payload(code: str, message: str, fields: dict[str, str] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message}
    if fields:
        body["fields"] = fields
    return {"error": body}


def _field_name(loc: tuple[Any, ...]) -> str:
    # Use the innermost named field: ("body", "email") -> "email"; ("body", "urls", 0) -> "urls".
    # Tagged unions add the tag to the location (("body", "services", "services")), so the last
    # string segment is also the right key there.
    names = [str(p) for p in loc if isinstance(p, str) and p not in ("body", "query", "path")]
    return names[-1] if names else "body"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            _payload(exc.code, exc.message, exc.fields),
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields: dict[str, str] = {}
        for err in exc.errors():
            fields.setdefault(
                _field_name(tuple(err["loc"])), str(err["msg"]).removeprefix("Value error, ")
            )
        return JSONResponse(
            _payload("validation_error", "Some fields are invalid.", fields), status_code=422
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        message = "Not found." if exc.status_code == 404 else "Request could not be processed."
        return JSONResponse(
            _payload(code, message), status_code=exc.status_code, headers=exc.headers or None
        )
