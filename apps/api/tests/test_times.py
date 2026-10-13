from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.times import as_utc, day_bounds, to_utc, zone


class TestZones:
    @pytest.mark.parametrize(
        "name", ["Europe/Berlin", "UTC", "Pacific/Auckland", "America/New_York", None, ""]
    )
    def test_known_zones_resolve(self, name: str | None) -> None:
        assert zone(name) is not None

    @pytest.mark.parametrize(
        "name",
        [
            "Mars/Phobos",
            "../etc/passwd",
            "/etc/localtime",
            "Europe/../Berlin",
            "x" * 65,
            "Europe\\Berlin",
            "UTC\x00",
        ],
    )
    def test_unknown_or_path_like_names_are_rejected(self, name: str) -> None:
        with pytest.raises(ValueError):
            zone(name)


class TestToUtc:
    def test_aware_values_are_converted_not_reinterpreted(self) -> None:
        value = datetime(2026, 6, 1, 9, 0, tzinfo=UTC) + timedelta(hours=0)
        assert to_utc(value, "Asia/Tokyo") == value

    def test_wall_clock_time_means_that_zones_clock(self) -> None:
        # Berlin is UTC+2 in summer and UTC+1 in winter: "9am" is a different instant.
        assert to_utc(datetime(2026, 7, 1, 9, 0), "Europe/Berlin") == datetime(
            2026, 7, 1, 7, 0, tzinfo=UTC
        )
        assert to_utc(datetime(2026, 1, 1, 9, 0), "Europe/Berlin") == datetime(
            2026, 1, 1, 8, 0, tzinfo=UTC
        )

    def test_the_hour_that_clocks_skip_does_not_exist(self) -> None:
        with pytest.raises(ValueError, match="doesn't exist"):
            to_utc(datetime(2026, 3, 29, 2, 30), "Europe/Berlin")
        with pytest.raises(ValueError, match="doesn't exist"):
            to_utc(datetime(2026, 3, 8, 2, 30), "America/New_York")
        assert to_utc(datetime(2026, 3, 29, 3, 0), "Europe/Berlin") == datetime(
            2026, 3, 29, 1, 0, tzinfo=UTC
        )

    def test_the_repeated_hour_resolves_to_its_first_occurrence(self) -> None:
        assert to_utc(datetime(2026, 10, 25, 2, 30), "Europe/Berlin") == datetime(
            2026, 10, 25, 0, 30, tzinfo=UTC
        )

    def test_unknown_zone_is_an_error(self) -> None:
        with pytest.raises(ValueError):
            to_utc(datetime(2026, 1, 1, 9, 0), "Nowhere/Land")


class TestDayBounds:
    def hours(self, now: datetime, tz: str) -> float:
        start, end = day_bounds(now, tz)
        return (end - start).total_seconds() / 3600

    def test_an_ordinary_day_is_24_hours(self) -> None:
        assert self.hours(datetime(2026, 6, 1, 12, tzinfo=UTC), "Europe/Berlin") == 24
        assert self.hours(datetime(2026, 6, 1, 12, tzinfo=UTC), "UTC") == 24

    def test_clock_change_days_are_23_and_25_hours(self) -> None:
        assert self.hours(datetime(2026, 3, 29, 12, tzinfo=UTC), "Europe/Berlin") == 23
        assert self.hours(datetime(2026, 10, 25, 12, tzinfo=UTC), "Europe/Berlin") == 25
        assert self.hours(datetime(2026, 11, 1, 12, tzinfo=UTC), "America/New_York") == 25

    def test_the_same_instant_is_a_different_day_in_different_zones(self) -> None:
        now = datetime(2026, 6, 1, 23, 30, tzinfo=UTC)
        berlin = day_bounds(now, "Europe/Berlin")
        new_york = day_bounds(now, "America/New_York")
        assert berlin == (
            datetime(2026, 6, 1, 22, 0, tzinfo=UTC),
            datetime(2026, 6, 2, 22, 0, tzinfo=UTC),
        )
        assert new_york == (
            datetime(2026, 6, 1, 4, 0, tzinfo=UTC),
            datetime(2026, 6, 2, 4, 0, tzinfo=UTC),
        )

    def test_the_boundary_instant_belongs_to_the_next_day(self) -> None:
        start, end = day_bounds(datetime(2026, 6, 1, 12, tzinfo=UTC), "UTC")
        assert (start, end) == (datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 6, 2, tzinfo=UTC))
        assert day_bounds(end, "UTC")[0] == end


def test_naive_database_values_are_read_as_utc() -> None:
    assert as_utc(datetime(2026, 1, 1, 9, 0)) == datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    assert as_utc(datetime(2026, 1, 1, 9, 0, tzinfo=UTC)).tzinfo == UTC
