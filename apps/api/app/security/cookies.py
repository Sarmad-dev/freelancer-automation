from __future__ import annotations

from datetime import timedelta

from fastapi import Response

from app.config import Settings

SESSION_COOKIE = "fos_session"
# The __Host- prefix (Secure, Path=/, no Domain) stops sibling subdomains from overwriting the cookie.
SECURE_SESSION_COOKIE = "__Host-fos_session"


def cookie_name(settings: Settings) -> str:
    return SECURE_SESSION_COOKIE if settings.secure_cookies else SESSION_COOKIE


def set_session_cookie(
    response: Response, settings: Settings, token: str, max_age: timedelta
) -> None:
    response.set_cookie(
        cookie_name(settings),
        token,
        max_age=max(1, int(max_age.total_seconds())),
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        cookie_name(settings),
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


def clear_cookie_header(settings: Settings) -> dict[str, str]:
    """Raw Set-Cookie header for error responses (where no Response object is available)."""
    r = Response()
    clear_session_cookie(r, settings)
    return {"set-cookie": r.headers["set-cookie"]}
