from __future__ import annotations

import hashlib
import secrets


def new_token() -> str:
    """256-bit URL-safe random token. Only its hash is ever stored."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    # Tokens are high-entropy random values, so an unsalted SHA-256 is sufficient (and indexable).
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def short_hash(value: str) -> str:
    """Non-reversible short identifier for correlating events without storing the raw value."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
