"""Shared input-cleaning helpers. All user text is trimmed and rejected if it holds control characters."""

from __future__ import annotations

import ipaddress
import re
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AfterValidator

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")  # keeps \t \n \r
_WS = re.compile(r"\s+")


def _check_control(value: str) -> str:
    if _CONTROL.search(value):
        raise ValueError("Contains invalid characters.")
    return value


def single_line(value: str) -> str:
    return _WS.sub(" ", _check_control(value)).strip()


def multi_line(value: str) -> str:
    return _check_control(value).strip()


def bounded(min_len: int, max_len: int, *, multiline: bool = False) -> AfterValidator:
    def _validate(value: str) -> str:
        cleaned = multi_line(value) if multiline else single_line(value)
        if len(cleaned) < min_len:
            raise ValueError("Too short." if min_len > 1 else "This field is required.")
        if len(cleaned) > max_len:
            raise ValueError(f"Use at most {max_len} characters.")
        return cleaned

    return AfterValidator(_validate)


Name = Annotated[str, bounded(1, 120)]


def clean_list(items: list[str], *, max_items: int, min_items: int, item_max: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        item = single_line(raw)
        if not item:
            continue
        if len(item) > item_max:
            raise ValueError(f"Each item must be at most {item_max} characters.")
        if item.casefold() not in seen:
            seen.add(item.casefold())
            out.append(item)
    if len(out) < min_items:
        raise ValueError(
            "Add at least one item." if min_items == 1 else f"Add at least {min_items} items."
        )
    if len(out) > max_items:
        raise ValueError(f"Add at most {max_items} items.")
    return out


_BLOCKED_SUFFIXES = (".local", ".internal", ".localhost", ".lan", ".home.arpa")


def clean_public_url(raw: str) -> str:
    """Accept only plain http(s) URLs to public hosts, without embedded credentials."""
    value = raw.strip()
    if not value or len(value) > 300 or _CONTROL.search(value) or re.search(r"\s", value):
        raise ValueError("Enter a valid URL.")
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Use a full http:// or https:// URL.")
    if parts.username or parts.password:
        raise ValueError("URLs must not contain a username or password.")
    host = parts.hostname.lower()
    if (
        host == "localhost"
        or host.endswith(_BLOCKED_SUFFIXES)
        or "." not in host
        and ":" not in host
    ):
        raise ValueError("Use a public website address.")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not ip.is_global:
            raise ValueError("Use a public website address.")
    try:
        _ = parts.port
    except ValueError as exc:
        raise ValueError("Enter a valid URL.") from exc
    return parts._replace(scheme=parts.scheme, netloc=parts.netloc.lower()).geturl()
