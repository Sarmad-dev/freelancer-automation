"""Building and reading RFC 5322 messages, defensively.

Outgoing: headers are built through the standard library, which refuses CR/LF in a header value, and every
address is validated first, so a subject or name cannot smuggle in a ``Bcc:`` header.
Incoming: addresses and dates are parsed leniently and anything unusable is reported, not guessed.
"""

from __future__ import annotations

import base64
import html as html_lib
import re
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

from email_validator import EmailNotValidError, validate_email

from app.mailbox.types import OutgoingMessage

_TAG = re.compile(r"<[^>]*>")
_BLOCK = re.compile(r"</?(?:p|div|br|li|tr|h[1-6])\b[^>]*>", re.I)
_DROP = re.compile(r"<(script|style|head)\b.*?</\1>", re.I | re.S)


def normalize_address(raw: str) -> str | None:
    """Lower-cased bare address, or None when it is not a deliverable-looking single address."""
    _, addr = parseaddr(raw.strip())
    if not addr or any(ch in addr for ch in "\r\n,;<>"):
        return None
    try:
        return validate_email(addr, check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        return None


def addresses(header_value: str | None) -> tuple[str, ...]:
    if not header_value:
        return ()
    found: list[str] = []
    for _, addr in getaddresses([header_value]):
        norm = normalize_address(addr) if addr else None
        if norm and norm not in found:
            found.append(norm)
    return tuple(found)


def parse_date(header_value: str | None) -> datetime | None:
    if not header_value:
        return None
    try:
        parsed = parsedate_to_datetime(header_value)
    except (TypeError, ValueError, IndexError):
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def clean_header(value: str | None, limit: int) -> str | None:
    """Single-line, trimmed, length-capped text from an untrusted header."""
    if value is None:
        return None
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", value).strip()
    return text[:limit] or None


def html_to_text(html: str) -> str:
    text = _DROP.sub(" ", html)
    text = _BLOCK.sub("\n", text)
    text = html_lib.unescape(_TAG.sub("", text))
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def build_rfc822(message: OutgoingMessage) -> bytes:
    """Serialise an approved message. Raises ``ValueError`` for anything that could alter the headers."""
    sender = normalize_address(message.from_address)
    recipient = normalize_address(message.to_address)
    if sender is None or recipient is None:
        raise ValueError("invalid address")
    if re.search(r"[\r\n]", message.subject):
        raise ValueError("invalid subject")
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = message.subject
    if message.in_reply_to:
        if re.search(r"[\r\n\s]", message.in_reply_to):
            raise ValueError("invalid reply id")
        msg["In-Reply-To"] = message.in_reply_to
        msg["References"] = message.in_reply_to
    msg.set_content(message.body_text)
    return msg.as_bytes()


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
