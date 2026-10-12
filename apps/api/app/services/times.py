"""Time-zone aware helpers for due dates and the Today / Upcoming / Overdue views.

Instants are stored in UTC. A person who says "9am Monday in Berlin" gets 9am in Berlin even across a daylight-saving
change, because the wall-clock time is resolved in the named zone, and "today" is the local day in the zone the
person is looking at, which is 23 or 25 hours long on a clock-change day.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_ZONE = "UTC"


def zone(name: str | None) -> ZoneInfo:
    """The named IANA zone. Raises ``ValueError`` for anything unknown (including path-like names)."""
    candidate = (name or DEFAULT_ZONE).strip()
    if not candidate or len(candidate) > 64 or ".." in candidate or candidate.startswith("/"):
        raise ValueError("Unknown time zone.")
    try:
        return ZoneInfo(candidate)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise ValueError("Unknown time zone.") from exc


def to_utc(value: datetime, tz_name: str | None) -> datetime:
    """UTC instant for ``value``. Aware values are converted; naive ones are wall-clock time in ``tz_name``.

    A wall-clock time that never happens (the hour skipped when clocks go forward) is rejected; one that happens twice
    (clocks go back) resolves to its first occurrence.
    """
    if value.tzinfo is not None:
        return value.astimezone(UTC)
    tz = zone(tz_name)
    local = value.replace(tzinfo=tz, fold=0)
    instant = local.astimezone(UTC)
    if instant.astimezone(tz).replace(tzinfo=None) != value:
        raise ValueError("That time doesn't exist in this time zone (the clocks skip it).")
    return instant


def day_bounds(now: datetime, tz_name: str | None) -> tuple[datetime, datetime]:
    """``[start, end)`` of the local day containing ``now``, as UTC instants."""
    tz = zone(tz_name)
    today: date = now.astimezone(tz).date()
    start = datetime.combine(today, time.min, tzinfo=tz).astimezone(UTC)
    end = datetime.combine(today + timedelta(days=1), time.min, tzinfo=tz).astimezone(UTC)
    return start, end


def as_utc(value: datetime) -> datetime:
    """Treat a naive database value as UTC (SQLite drops the zone) and convert aware values."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
