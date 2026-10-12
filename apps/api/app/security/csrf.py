"""CSRF defence for cookie-authenticated requests.

Session cookies are SameSite=Lax (not sent on cross-site POSTs). As defence in depth, every
state-changing request must either carry an ``Origin`` that is on the allow-list, or (when browsers omit
Origin, e.g. server-side calls) the custom ``X-Requested-With`` header, which cross-site forms cannot set.
"""

from __future__ import annotations

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "x-requested-with"
CSRF_HEADER_VALUE = "freelancer-os"


def is_request_allowed(
    method: str, origin: str | None, csrf_header: str | None, allowed: list[str]
) -> bool:
    if method.upper() in SAFE_METHODS:
        return True
    if origin is not None:
        return origin in allowed
    return csrf_header == CSRF_HEADER_VALUE
