"""Handling of untrusted text (emails, imports, documents, tool results) before and after a model sees it.

Three jobs:
1. ``minimise`` removes personal data a model does not need (email addresses, phone numbers, long digit runs, URL
   query strings) so it is never sent.
2. ``wrap`` fences text in a per-call random boundary and strips anything that could fake the boundary, so the
   prompt can say "everything inside the fence is data".
3. ``injection_signals`` is a *heuristic detector* used to warn people and to harden validation. It is not the
   defence: the defence is that model output is never trusted, only validated, and never causes an action.
"""

from __future__ import annotations

import re
import secrets
import unicodedata

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁦-⁩﻿]")
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
_PHONE = re.compile(r"(?<![\w.])\+?\(?\d[\d\s().\-]{7,}\d(?![\w])")
_LONG_DIGITS = re.compile(r"\b\d{12,}\b")
_URL = re.compile(r"https?://[^\s<>\"')]+", re.I)
_FENCE = re.compile(r"<<<+|>>>+")

MAX_UNTRUSTED_CHARS = 8_000


def clean(text: str, limit: int = MAX_UNTRUSTED_CHARS) -> str:
    """Normalise to NFC, drop control and bidi-override characters, cap blank lines and length."""
    text = unicodedata.normalize("NFC", text)
    text = _CONTROL.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + " …[truncated]"
    return text


def _strip_url_query(match: re.Match[str]) -> str:
    url = match.group(0)
    return re.split(r"[?#]", url, maxsplit=1)[0]


def minimise(text: str) -> str:
    """Remove personal data that no task needs. Idempotent."""
    text = _EMAIL.sub("[email]", text)
    text = _URL.sub(_strip_url_query, text)
    text = _LONG_DIGITS.sub("[number]", text)
    return _PHONE.sub("[phone]", text)


def new_boundary() -> str:
    return secrets.token_hex(8)


def wrap(label: str, text: str, boundary: str, *, limit: int = MAX_UNTRUSTED_CHARS) -> str:
    """Fence ``text`` so it reads as data. Look-alike fences inside the text are defused."""
    safe = _FENCE.sub("« ", clean(text, limit))
    safe = safe.replace(boundary, "")
    return f"<<<UNTRUSTED {label} {boundary}>>>\n{safe}\n<<<END {boundary}>>>"


# Phrases that mean "an email is trying to talk to the model". Case-insensitive, whitespace-tolerant.
_INJECTION = [
    (
        "override",
        r"ignore (?:all |any |the |your )?(?:previous|prior|above|earlier) (?:instructions|rules|prompts?)",
    ),
    ("override", r"disregard (?:all |any |the |your )?(?:previous|prior|above|earlier|system)"),
    ("override", r"forget (?:everything|all|your) (?:above|previous|instructions|rules)"),
    ("role", r"you are now\b"),
    ("role", r"\bact as (?:an?|the) "),
    ("role", r"new instructions?\s*:"),
    ("role", r"\bsystem (?:prompt|message|override)\b"),
    ("role", r"\bdeveloper mode\b|\bjailbreak\b|\bDAN\b"),
    (
        "exfiltration",
        r"(?:reveal|show|print|repeat|output|leak|send)\b[^.\n]{0,40}\b(?:system prompt|instructions|api[ _-]?key|secret|password|credentials|token)",
    ),
    ("exfiltration", r"\bapi[ _-]?key\b|\bbearer [a-z0-9_\-\.]{12,}"),
    ("action", r"(?:forward|send|email) (?:this|all|the) [^.\n]{0,40}\bto\b [^\s]+@"),
    ("action", r"\b(?:classify|mark|label|rate) (?:this|me|it) as\b"),
    ("action", r"\bdo not (?:tell|inform|alert) (?:the )?(?:user|owner|freelancer)\b"),
]
_INJECTION_RE = [(kind, re.compile(pattern, re.I)) for kind, pattern in _INJECTION]


def injection_signals(text: str) -> list[str]:
    """Distinct kinds of injection-like phrasing found ("override", "role", "exfiltration", "action")."""
    squashed = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text))
    found: list[str] = []
    for kind, regex in _INJECTION_RE:
        if kind not in found and regex.search(squashed):
            found.append(kind)
    return found
