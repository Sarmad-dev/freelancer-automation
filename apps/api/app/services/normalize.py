"""Normalisation shared by the lead forms, the API and the CSV importer, so every path applies the same rules
(and therefore the same duplicate detection)."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from email_validator import EmailNotValidError, validate_email

from app.schemas.text import clean_public_url, single_line

_PHONE = re.compile(r"^\+?[0-9][0-9 ().\-]{2,24}(?:\s?(?:x|ext\.?)\s?[0-9]{1,6})?$", re.I)


def normalize_email(raw: str) -> str:
    """Lower-cased, validated address. Raises ``ValueError`` with a message fit for a form."""
    value = single_line(raw)
    if not value or len(value) > 254:
        raise ValueError("Enter a valid email address.")
    try:
        result = validate_email(value, check_deliverability=False)
    except EmailNotValidError as exc:
        raise ValueError("Enter a valid email address.") from exc
    return result.normalized.lower()


def normalize_website(raw: str) -> tuple[str, str]:
    """``(website_url, domain)`` for "acme.com", "www.acme.com/about" or "https://acme.com".

    Only public http(s) addresses are accepted. The domain drops a leading ``www.`` so the same company is
    recognised however its address was typed.
    """
    value = single_line(raw)
    if not value:
        raise ValueError("Enter a valid website address.")
    if "://" not in value:
        value = f"https://{value}"
    url = clean_public_url(value)
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    domain = host[4:] if host.startswith("www.") else host
    return url, domain


def normalize_phone(raw: str) -> str:
    value = single_line(raw)
    if not _PHONE.match(value):
        raise ValueError("Use digits, spaces and + ( ) - . only.")
    return value


def key(value: str | None) -> str:
    """Case-insensitive comparison key for names and titles."""
    return single_line(value or "").casefold()
