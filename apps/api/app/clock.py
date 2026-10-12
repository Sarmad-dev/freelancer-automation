from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """Treat naive datetimes (SQLite) as UTC so comparisons behave the same on every backend."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
