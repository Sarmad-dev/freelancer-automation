"""Checks applied to every model reply after it parses. A reply that fails is never used or repaired.

- ``reject_leaks``: the system prompt (or its canary) and secret-looking strings must not appear in output.
- ``claims``: draft text may state only numbers, URLs and addresses that appear in the supplied facts.
"""

from __future__ import annotations

import re
import unicodedata

from app.ai.errors import PolicyViolation

_SECRET = re.compile(
    r"\b(?:sk|pk|rk)[-_][A-Za-z0-9_\-]{16,}\b|\bbearer\s+[A-Za-z0-9_\-\.]{16,}|"
    r"\bAKIA[0-9A-Z]{16}\b|\bapi[_-]?key\s*[:=]\s*\S{8,}|-----BEGIN [A-Z ]*PRIVATE KEY-----",
    re.I,
)
_NUMBER = re.compile(r"(?<![\w])[$€£]?\d[\d,]*(?:\.\d+)?%?")
_URL = re.compile(r"(?:https?://|www\.)[^\s<>\"')]+", re.I)
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
# "15-minute call" is a request, not a claim: scheduling units are the one place a new number is allowed.
_SCHEDULING = re.compile(r"^\W*(?:-|\s)?(?:minutes?|mins?)\b", re.I)
# Familiarity the freelancer cannot have established by a first message.
_FAKE_FAMILIARITY = re.compile(
    r"\b(?:as we discussed|as discussed|following (?:up on )?our (?:call|chat|conversation|meeting)|"
    r"great (?:speaking|talking|meeting) (?:with|to) you|good to (?:speak|talk|meet) (?:with|to) you|"
    r"it was (?:great|good|nice) (?:speaking|talking|meeting)|per our (?:call|conversation)|"
    r"as promised|when we (?:last )?(?:spoke|met|talked))\b",
    re.I,
)


def fold(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).casefold().strip()


def _canon_number(token: str) -> str:
    return token.replace(",", "").lstrip("$€£").rstrip(".").rstrip("%")


def numbers_in(text: str) -> set[str]:
    return {_canon_number(m.group(0)) for m in _NUMBER.finditer(text)} - {""}


def reject_leaks(output_text: str, system_prompt: str, canary: str) -> None:
    """Raise if the reply echoes the system prompt, its canary or anything shaped like a credential."""
    if canary and canary in output_text:
        raise PolicyViolation("system_prompt_leak")
    folded_out = fold(output_text)
    words = fold(system_prompt).split()
    # Any 10-word run of the system prompt appearing in the output is a leak.
    for i in range(0, max(0, len(words) - 9)):
        if " ".join(words[i : i + 10]) in folded_out:
            raise PolicyViolation("system_prompt_leak")
    if _SECRET.search(output_text):
        raise PolicyViolation("secret_in_output")


def unsupported_claims(text: str, allowed_text: str) -> list[str]:
    """Short tags for anything in ``text`` that ``allowed_text`` does not back up. Never returns content."""
    problems: list[str] = []
    allowed_numbers = numbers_in(allowed_text)
    for m in _NUMBER.finditer(text):
        canon = _canon_number(m.group(0))
        if not canon or canon in allowed_numbers:
            continue
        if _SCHEDULING.match(text[m.end() : m.end() + 12]) and "%" not in m.group(0):
            continue
        problems.append("number")
        break
    allowed_folded = fold(allowed_text)
    for m in _URL.finditer(text):
        host = (
            re.sub(r"^(?:https?://|www\.)", "", m.group(0), flags=re.I).rstrip(".,;:!?)").casefold()
        )
        if host not in allowed_folded and host.split("/")[0] not in allowed_folded:
            problems.append("url")
            break
    for m in _EMAIL.finditer(text):
        if m.group(0).casefold() not in allowed_folded:
            problems.append("email_address")
            break
    if _FAKE_FAMILIARITY.search(text):
        problems.append("invented_relationship")
    return problems


def contained_in(quote: str, source: str) -> bool:
    """Whether ``quote`` appears in ``source`` once case, spacing and Unicode forms are ignored."""
    q = fold(quote)
    return bool(q) and q in fold(source)
