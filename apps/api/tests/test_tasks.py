from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session as DbSession

from app.db.models import AuditEvent, Workspace
from app.db.models_crm import Task
from tests.conftest import add_member, make_user, second_client

T0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


def turl(wid: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{wid}/tasks{suffix}"


def freeze(monkeypatch: pytest.MonkeyPatch, now: datetime) -> None:
    monkeypatch.setattr("app.routers.tasks.utcnow", lambda: now)
    monkeypatch.setattr("app.services.tasks.utcnow", lambda: now)
    monkeypatch.setattr("app.services.notifications.utcnow", lambda: now)


def task(client: TestClient, wid: str, title: str = "Follow up", **extra: Any) -> dict[str, Any]:
    res = client.post(turl(wid), json={"title": title, **extra})
    assert res.status_code in (200, 201), res.text
    return res.json()


def lead(client: TestClient, wid: str, title: str = "Website rebuild") -> dict[str, Any]:
    return client.post(f"/api/v1/workspaces/{wid}/leads", json={"title": title}).json()


def deal(client: TestClient, wid: str, lead_id: str) -> dict[str, Any]:
    return client.post(f"/api/v1/workspaces/{wid}/opportunities", json={"lead_id": lead_id}).json()


def titles(client: TestClient, wid: str, **params: Any) -> list[str]:
    res = client.get(turl(wid), params=params)
    assert res.status_code == 200, res.text
    return [t["title"] for t in res.json()["items"]]


@pytest.fixture
def other(client: TestClient) -> TestClient:
    return second_client(client)


class TestCreate:
    def test_a_task_needs_only_a_title(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        t = task(client, wid)
        assert t["status"] == "open" and t["priority"] == "normal" and t["created_by"] == "user"
        assert t["due_at"] is None and t["due_timezone"] is None and t["is_overdue"] is False
        assert t["lead"] is None and t["opportunity"] is None and t["assignee_user_id"]

    def test_wall_clock_times_are_resolved_in_the_chosen_zone(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        summer = task(client, wid, due_at="2026-07-01T09:00:00", due_timezone="Europe/Berlin")
        winter = task(client, wid, due_at="2026-01-01T09:00:00", due_timezone="Europe/Berlin")
        assert (
            summer["due_at"].startswith("2026-07-01T07:00:00")
            and summer["due_timezone"] == "Europe/Berlin"
        )
        assert winter["due_at"].startswith("2026-01-01T08:00:00")

    def test_an_exact_instant_is_kept_and_the_zone_is_only_for_display(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        t = task(client, wid, due_at="2026-07-01T09:00:00+09:00", due_timezone="Asia/Tokyo")
        assert t["due_at"].startswith("2026-07-01T00:00:00") and t["due_timezone"] == "Asia/Tokyo"

    def test_the_default_zone_is_the_workspaces(self, client: TestClient, db: DbSession) -> None:
        wid = make_user(client)["workspace_id"]
        db.execute(
            update(Workspace)
            .where(Workspace.id == uuid.UUID(wid))
            .values(timezone="Pacific/Auckland")
        )
        db.commit()
        t = task(client, wid, due_at="2026-07-01T09:00:00")
        assert t["due_timezone"] == "Pacific/Auckland" and t["due_at"].startswith(
            "2026-06-30T21:00:00"
        )

    def test_a_time_that_clocks_skip_is_rejected_not_silently_moved(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        res = client.post(
            turl(wid),
            json={"title": "x", "due_at": "2026-03-29T02:30:00", "due_timezone": "Europe/Berlin"},
        )
        assert res.status_code == 422 and "due_at" in res.json()["error"]["fields"]
        assert "exist" in res.json()["error"]["fields"]["due_at"]
        ok = task(
            client, wid, due_at="2026-10-25T02:30:00", due_timezone="Europe/Berlin"
        )  # repeated hour: first one
        assert ok["due_at"].startswith("2026-10-25T00:30:00")

    @pytest.mark.parametrize(
        ("body", "field"),
        [
            ({"due_timezone": "Mars/Base"}, "due_timezone"),
            ({"due_timezone": "../etc/passwd"}, "due_timezone"),
            ({"title": ""}, "title"),
            ({"title": "x" * 301}, "title"),
            ({"title": "a\x00b"}, "title"),
            ({"priority": "urgent"}, "priority"),
            ({"due_at": "tomorrow"}, "due_at"),
            ({"description": "x" * 4001}, "description"),
            ({"idempotency_key": "short"}, "idempotency_key"),
            ({"idempotency_key": "has spaces in it!"}, "idempotency_key"),
            ({"status": "done"}, "status"),
            ({"created_by": "ai"}, "created_by"),
            ({"assignee_user_id": str(uuid.uuid4())}, "assignee_user_id"),
            ({"workspace_id": str(uuid.uuid4())}, "workspace_id"),
            ({"remind_at": "2026-07-02T09:00:00", "due_at": "2026-07-01T09:00:00"}, "remind_at"),
        ],
    )
    def test_invalid_input_is_rejected_and_nothing_is_saved(
        self, client: TestClient, body: dict[str, Any], field: str
    ) -> None:
        wid = make_user(client)["workspace_id"]
        res = client.post(turl(wid), json={"title": "x", **body})
        assert res.status_code == 422 and field in res.json()["error"]["fields"], res.text
        assert client.get(turl(wid)).json()["total"] == 0

    def test_markup_is_stored_as_inert_text(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        t = task(
            client,
            wid,
            "<script>alert(1)</script>",
            description="{{7*7}} <img src=x onerror=alert(1)>",
        )
        assert t["title"] == "<script>alert(1)</script>" and "{{7*7}}" in t["description"]


class TestLinks:
    def test_links_are_validated_and_fill_in_the_lead(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        ld = lead(client, wid)
        opp = deal(client, wid, ld["id"])
        t = task(client, wid, opportunity_id=opp["id"])
        assert t["opportunity"]["id"] == opp["id"] and t["lead"]["id"] == ld["id"]
        both = task(client, wid, lead_id=ld["id"], opportunity_id=opp["id"])
        assert both["lead"]["id"] == ld["id"]

    def test_a_deal_and_a_different_lead_cannot_be_combined(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        one, two = lead(client, wid, "One"), lead(client, wid, "Two")
        opp = deal(client, wid, one["id"])
        res = client.post(
            turl(wid), json={"title": "x", "lead_id": two["id"], "opportunity_id": opp["id"]}
        )
        assert res.status_code == 422 and "lead_id" in res.json()["error"]["fields"]

    def test_foreign_and_unknown_records_are_rejected(
        self, client: TestClient, other: TestClient
    ) -> None:
        a, b = make_user(client), make_user(other)
        theirs = lead(other, b["workspace_id"])
        their_deal = deal(other, b["workspace_id"], theirs["id"])
        for field, value in (
            ("lead_id", theirs["id"]),
            ("opportunity_id", their_deal["id"]),
            ("conversation_id", str(uuid.uuid4())),
            ("lead_id", str(uuid.uuid4())),
        ):
            res = client.post(turl(a["workspace_id"]), json={"title": "x", field: value})
            assert res.status_code == 422 and field in res.json()["error"]["fields"], field

    def test_tasks_filter_by_what_they_are_linked_to(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        ld = lead(client, wid)
        opp = deal(client, wid, ld["id"])
        task(client, wid, "on lead", lead_id=ld["id"])
        task(client, wid, "on deal", opportunity_id=opp["id"])
        task(client, wid, "loose")
        assert sorted(titles(client, wid, lead_id=ld["id"])) == ["on deal", "on lead"]
        assert titles(client, wid, opportunity_id=opp["id"]) == ["on deal"]

    def test_creating_and_completing_are_written_to_the_leads_timeline(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        ld = lead(client, wid)
        t = task(client, wid, "Send quote", lead_id=ld["id"])
        client.post(turl(wid, f"/{t['id']}/complete"))
        client.post(turl(wid, f"/{t['id']}/complete"))  # a repeat must not log twice
        timeline = client.get(f"/api/v1/workspaces/{wid}/leads/{ld['id']}/activities").json()[
            "items"
        ]
        entries = [a["summary"] for a in timeline if a["kind"] == "task"]
        assert sorted(entries) == ["Task completed: Send quote", "Task created: Send quote"]


class TestDuplicateSubmission:
    def test_the_same_key_returns_the_first_task(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        key = "form-" + uuid.uuid4().hex
        first = client.post(turl(wid), json={"title": "Call", "idempotency_key": key})
        again = client.post(turl(wid), json={"title": "Call", "idempotency_key": key})
        assert first.status_code == 201 and again.status_code == 200
        assert again.json()["id"] == first.json()["id"]
        assert client.get(turl(wid)).json()["total"] == 1

    def test_reusing_a_key_for_a_different_task_is_a_conflict(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        key = "form-" + uuid.uuid4().hex
        client.post(turl(wid), json={"title": "Call", "idempotency_key": key})
        res = client.post(turl(wid), json={"title": "Something else", "idempotency_key": key})
        assert res.status_code == 409 and res.json()["error"]["code"] == "idempotency_conflict"
        assert client.get(turl(wid)).json()["total"] == 1

    def test_keys_are_per_workspace(self, client: TestClient, other: TestClient) -> None:
        a, b = make_user(client), make_user(other)
        key = "shared-" + uuid.uuid4().hex
        one = client.post(turl(a["workspace_id"]), json={"title": "x", "idempotency_key": key})
        two = other.post(turl(b["workspace_id"]), json={"title": "x", "idempotency_key": key})
        assert one.status_code == two.status_code == 201 and one.json()["id"] != two.json()["id"]

    def test_tasks_without_a_key_are_never_merged(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        task(client, wid, "same")
        task(client, wid, "same")
        assert client.get(turl(wid)).json()["total"] == 2

    def test_two_requests_that_race_still_make_one_task(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both requests pass the 'already exists?' check; the database's unique key decides the winner."""
        wid = make_user(client)["workspace_id"]
        key = "race-" + uuid.uuid4().hex
        first = client.post(turl(wid), json={"title": "Call", "idempotency_key": key}).json()
        real = __import__("app.services.tasks", fromlist=["_existing_by_key"])._existing_by_key
        calls = {"n": 0}

        def blind_first_time(db: Any, ctx: Any, k: str) -> Any:
            calls["n"] += 1
            return None if calls["n"] == 1 else real(db, ctx, k)

        monkeypatch.setattr("app.services.tasks._existing_by_key", blind_first_time)
        again = client.post(turl(wid), json={"title": "Call", "idempotency_key": key})
        assert again.status_code == 200 and again.json()["id"] == first["id"]
        assert client.get(turl(wid)).json()["total"] == 1


class TestViews:
    """Fixed clock: 2026-06-01 12:00 UTC."""

    def make(self, client: TestClient, wid: str, title: str, due: str | None, **extra: Any) -> None:
        task(client, wid, title, **({"due_at": due} if due else {}), **extra)

    def test_buckets_are_disjoint_and_boundaries_are_exact_in_utc(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wid = make_user(client)["workspace_id"]
        freeze(monkeypatch, T0)
        for title, due in (
            ("a: a second ago", "2026-06-01T11:59:59Z"),
            ("b: exactly now", "2026-06-01T12:00:00Z"),
            ("c: last second of today", "2026-06-01T23:59:59Z"),
            ("d: midnight", "2026-06-02T00:00:00Z"),
            ("e: next week", "2026-06-08T09:00:00Z"),
            ("f: no date", None),
        ):
            self.make(client, wid, title, due)
        views = {
            v: titles(client, wid, view=v, tz="UTC")
            for v in ("overdue", "today", "upcoming", "undated", "open")
        }
        assert views["overdue"] == ["a: a second ago"]
        assert views["today"] == ["b: exactly now", "c: last second of today"]
        assert views["upcoming"] == ["d: midnight", "e: next week"]
        assert views["undated"] == ["f: no date"]
        assert len(views["open"]) == 6
        listed = [t for v in ("overdue", "today", "upcoming", "undated") for t in views[v]]
        assert sorted(listed) == sorted(views["open"])  # nothing in two buckets, nothing in none

    def test_today_depends_on_the_zone_you_are_in(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wid = make_user(client)["workspace_id"]
        freeze(monkeypatch, T0)
        self.make(client, wid, "23:00 UTC", "2026-06-01T23:00:00Z")
        self.make(client, wid, "05:00 UTC tomorrow", "2026-06-02T05:00:00Z")
        # Berlin's day ends at 22:00 UTC, New York's at 04:00 UTC the next day.
        assert titles(client, wid, view="today", tz="UTC") == ["23:00 UTC"]
        assert titles(client, wid, view="upcoming", tz="Europe/Berlin") == [
            "23:00 UTC",
            "05:00 UTC tomorrow",
        ]
        assert titles(client, wid, view="today", tz="America/New_York") == ["23:00 UTC"]
        assert titles(client, wid, view="upcoming", tz="America/New_York") == ["05:00 UTC tomorrow"]

    def test_a_clock_change_day_is_23_hours_long(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wid = make_user(client)["workspace_id"]
        freeze(monkeypatch, datetime(2026, 3, 29, 12, 0, tzinfo=UTC))
        self.make(client, wid, "last minute of the day", "2026-03-29T21:59:00Z")
        self.make(
            client, wid, "first minute of tomorrow", "2026-03-29T22:00:00Z"
        )  # Berlin midnight (UTC+2)
        assert titles(client, wid, view="today", tz="Europe/Berlin") == ["last minute of the day"]
        assert titles(client, wid, view="upcoming", tz="Europe/Berlin") == [
            "first minute of tomorrow"
        ]

    def test_the_workspace_zone_is_the_default(
        self, client: TestClient, db: DbSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wid = make_user(client)["workspace_id"]
        freeze(monkeypatch, T0)
        self.make(client, wid, "23:00 UTC", "2026-06-01T23:00:00Z")
        assert titles(client, wid, view="today") == ["23:00 UTC"]
        db.execute(
            update(Workspace).where(Workspace.id == uuid.UUID(wid)).values(timezone="Europe/Berlin")
        )
        db.commit()
        assert titles(client, wid, view="today") == [] and titles(client, wid, view="upcoming") == [
            "23:00 UTC"
        ]

    def test_summary_counts_match_the_lists(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wid = make_user(client)["workspace_id"]
        freeze(monkeypatch, T0)
        for title, due in (
            ("a", "2026-05-30T09:00:00Z"),
            ("b", "2026-06-01T15:00:00Z"),
            ("c", "2026-06-05T09:00:00Z"),
            ("d", None),
        ):
            self.make(client, wid, title, due)
        done = task(client, wid, "done one")
        client.post(turl(wid, f"/{done['id']}/complete"))
        summary = client.get(turl(wid, "/summary"), params={"tz": "UTC"}).json()
        assert summary == {
            "timezone": "UTC",
            "overdue": 1,
            "today": 1,
            "upcoming": 1,
            "undated": 1,
            "done": 1,
        }

    def test_done_and_dismissed_views(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        a, b, c = (task(client, wid, n) for n in ("first", "second", "third"))
        client.post(turl(wid, f"/{a['id']}/complete"))
        client.post(turl(wid, f"/{b['id']}/complete"))
        client.post(turl(wid, f"/{c['id']}/dismiss"))
        assert titles(client, wid, view="done") == [
            "second",
            "first",
        ]  # most recently completed first
        assert titles(client, wid, view="dismissed") == ["third"]
        assert titles(client, wid, view="open") == [] and len(titles(client, wid, view="all")) == 3

    def test_overdue_tasks_say_so(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wid = make_user(client)["workspace_id"]
        freeze(monkeypatch, T0)
        late = task(client, wid, "late", due_at="2026-05-31T09:00:00Z")
        done = task(client, wid, "late but done", due_at="2026-05-31T09:00:00Z")
        client.post(turl(wid, f"/{done['id']}/complete"))
        assert late["is_overdue"] is True
        assert client.get(turl(wid, f"/{done['id']}")).json()["is_overdue"] is False

    @pytest.mark.parametrize(
        "params",
        [{"view": "someday"}, {"tz": "Mars/Base"}, {"sort": "password"}, {"priority": "urgent"}],
    )
    def test_bad_query_parameters_are_rejected(
        self, client: TestClient, params: dict[str, str]
    ) -> None:
        wid = make_user(client)["workspace_id"]
        assert client.get(turl(wid), params=params).status_code == 422

    def test_search_filters_and_paging(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        task(client, wid, "Send proposal", priority="high")
        task(client, wid, "Call Ada", description="about the PROPOSAL")
        task(client, wid, "Water plants")
        assert sorted(titles(client, wid, q="proposal")) == ["Call Ada", "Send proposal"]
        assert titles(client, wid, priority="high") == ["Send proposal"]
        assert titles(client, wid, q="%") == []
        page = client.get(turl(wid), params={"limit": 2, "offset": 2, "sort": "title"}).json()
        assert page["total"] == 3 and [t["title"] for t in page["items"]] == ["Water plants"]


class TestActions:
    def test_complete_is_idempotent_and_reopen_undoes_it(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        t = task(client, wid)
        first = client.post(turl(wid, f"/{t['id']}/complete")).json()
        again = client.post(turl(wid, f"/{t['id']}/complete")).json()
        assert first["status"] == "done"
        assert first["completed_at"].rstrip("Z") == again["completed_at"].rstrip(
            "Z"
        )  # SQLite drops the zone
        back = client.post(turl(wid, f"/{t['id']}/reopen")).json()
        assert back["status"] == "open" and back["completed_at"] is None
        assert client.post(turl(wid, f"/{t['id']}/reopen")).status_code == 200

    def test_dismiss(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        t = task(client, wid)
        d = client.post(turl(wid, f"/{t['id']}/dismiss")).json()
        assert d["status"] == "dismissed" and d["completed_at"] is None
        assert client.post(turl(wid, f"/{t['id']}/dismiss")).status_code == 200

    def test_reschedule_moves_the_reminder_with_the_due_time(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        t = task(
            client,
            wid,
            due_at="2026-07-01T10:00:00",
            due_timezone="Europe/Berlin",
            remind_at="2026-07-01T09:00:00",
        )
        moved = client.post(
            turl(wid, f"/{t['id']}/reschedule"),
            json={"due_at": "2026-07-08T14:00:00", "due_timezone": "Europe/Berlin"},
        ).json()
        assert moved["due_at"].startswith("2026-07-08T12:00:00") and moved["remind_at"].startswith(
            "2026-07-08T11:00:00"
        )

    def test_rescheduling_a_finished_task_brings_it_back(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        t = task(client, wid)
        client.post(turl(wid, f"/{t['id']}/complete"))
        back = client.post(
            turl(wid, f"/{t['id']}/reschedule"), json={"due_at": "2030-01-01T09:00:00Z"}
        ).json()
        assert back["status"] == "open" and back["completed_at"] is None

    def test_reschedule_validates_zone_and_the_skipped_hour(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        t = task(client, wid)
        gap = client.post(
            turl(wid, f"/{t['id']}/reschedule"),
            json={"due_at": "2026-03-29T02:30:00", "due_timezone": "Europe/Berlin"},
        )
        assert gap.status_code == 422 and "due_at" in gap.json()["error"]["fields"]
        assert (
            client.post(
                turl(wid, f"/{t['id']}/reschedule"),
                json={"due_at": "2030-01-01T09:00:00Z", "due_timezone": "Nope/Zone"},
            ).status_code
            == 422
        )
        assert client.post(turl(wid, f"/{t['id']}/reschedule"), json={}).status_code == 422

    def test_snooze_sets_a_new_reminder_but_never_after_the_due_time(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        t = task(client, wid, due_at="2030-01-01T10:00:00Z")
        ok = client.post(
            turl(wid, f"/{t['id']}/snooze"), json={"remind_at": "2030-01-01T09:00:00Z"}
        ).json()
        assert ok["remind_at"].startswith("2030-01-01T09:00:00")
        late = client.post(
            turl(wid, f"/{t['id']}/snooze"), json={"remind_at": "2030-01-01T11:00:00Z"}
        )
        assert late.status_code == 422 and "remind_at" in late.json()["error"]["fields"]

    def test_patch_semantics(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        t = task(
            client,
            wid,
            due_at="2030-01-01T10:00:00Z",
            remind_at="2030-01-01T09:00:00Z",
            description="d",
            priority="high",
        )
        url = turl(wid, f"/{t['id']}")
        cleared = client.patch(
            url, json={"due_at": None, "remind_at": None, "description": "", "title": None}
        ).json()
        assert (
            cleared["due_at"] is None
            and cleared["remind_at"] is None
            and cleared["description"] is None
        )
        assert (
            cleared["title"] == "Follow up"
            and cleared["priority"] == "high"
            and cleared["due_timezone"] is None
        )
        later = client.patch(
            url, json={"due_at": "2030-02-01T09:00:00", "due_timezone": "Asia/Tokyo"}
        ).json()
        assert later["due_at"].startswith("2030-02-01T00:00:00")

    @pytest.mark.parametrize(
        "body",
        [
            {"status": "done"},
            {"completed_at": None},
            {"lead_id": str(uuid.uuid4())},
            {"created_by": "ai"},
        ],
    )
    def test_state_and_links_cannot_be_patched(
        self, client: TestClient, body: dict[str, Any]
    ) -> None:
        wid = make_user(client)["workspace_id"]
        t = task(client, wid)
        assert client.patch(turl(wid, f"/{t['id']}"), json=body).status_code == 422

    def test_a_reminder_after_the_due_time_is_rejected_on_edit(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        t = task(client, wid, due_at="2030-01-01T10:00:00Z")
        res = client.patch(turl(wid, f"/{t['id']}"), json={"remind_at": "2030-01-02T10:00:00Z"})
        assert res.status_code == 422 and "remind_at" in res.json()["error"]["fields"]

    def test_actions_are_audited_without_content(self, client: TestClient, db: DbSession) -> None:
        wid = make_user(client)["workspace_id"]
        t = task(client, wid, "Very private title", description="secret details")
        client.post(turl(wid, f"/{t['id']}/complete"))
        client.post(turl(wid, f"/{t['id']}/reopen"))
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.workspace_id == uuid.UUID(wid))
        ).all()
        assert {"tasks.created", "tasks.completed", "tasks.reopened"} <= {e.action for e in events}
        assert "private" not in str([e.details for e in events]) and "secret" not in str(
            [e.details for e in events]
        )


class TestPermissionsAndIsolation:
    def test_other_workspaces_tasks_are_invisible_and_untouchable(
        self, client: TestClient, other: TestClient
    ) -> None:
        a, b = make_user(client), make_user(other)
        theirs = task(other, b["workspace_id"], "Theirs")
        wid = a["workspace_id"]
        url = turl(wid, f"/{theirs['id']}")
        assert client.get(url).status_code == 404
        for method, suffix, body in (
            ("patch", "", {"title": "x"}),
            ("post", "/complete", None),
            ("post", "/dismiss", None),
            ("post", "/reopen", None),
            ("post", "/reschedule", {"due_at": "2030-01-01T09:00:00Z"}),
            ("post", "/snooze", {"remind_at": "2030-01-01T09:00:00Z"}),
        ):
            kwargs = {"json": body} if body is not None else {}
            assert getattr(client, method)(url + suffix, **kwargs).status_code == 404, suffix
        assert titles(client, wid, view="all") == []
        assert (
            other.get(turl(wid)).status_code == 404
            and other.get(turl(wid, "/summary")).status_code == 404
        )

    def test_members_read_but_cannot_change(
        self, client: TestClient, other: TestClient, db: DbSession
    ) -> None:
        owner, member = make_user(client), make_user(other)
        wid = owner["workspace_id"]
        add_member(db, wid, member["me"]["user"]["id"])
        t = task(client, wid)
        assert (
            other.get(turl(wid)).status_code == 200
            and other.get(turl(wid, "/summary")).status_code == 200
        )
        base = turl(wid, f"/{t['id']}")
        for method, url, body in (
            ("post", turl(wid), {"title": "x"}),
            ("patch", base, {"title": "x"}),
            ("post", f"{base}/complete", None),
            ("post", f"{base}/dismiss", None),
            ("post", f"{base}/reopen", None),
            ("post", f"{base}/reschedule", {"due_at": "2030-01-01T09:00:00Z"}),
            ("post", f"{base}/snooze", {"remind_at": "2030-01-01T09:00:00Z"}),
        ):
            kwargs = {"json": body} if body is not None else {}
            assert getattr(other, method)(url, **kwargs).status_code == 403, (method, url)

    def test_unauthenticated_requests_are_refused(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        client.cookies.clear()
        assert client.get(turl(wid)).status_code == 401
        assert client.post(turl(wid), json={"title": "x"}).status_code == 401


def test_the_database_refuses_a_task_linked_across_workspaces(
    client: TestClient, other: TestClient, db: DbSession
) -> None:
    from sqlalchemy.exc import IntegrityError

    a, b = make_user(client), make_user(other)
    theirs = lead(other, b["workspace_id"])
    db.add(
        Task(
            workspace_id=uuid.UUID(a["workspace_id"]),
            title="cross",
            lead_id=uuid.UUID(theirs["id"]),
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_a_deleted_lead_takes_its_tasks_with_it(client: TestClient, db: DbSession) -> None:
    from app.db.models_crm import Lead

    wid = make_user(client)["workspace_id"]
    ld = lead(client, wid)
    task(client, wid, "linked", lead_id=ld["id"])
    task(client, wid, "loose")
    db.delete(db.get(Lead, uuid.UUID(ld["id"])))
    db.commit()
    assert titles(client, wid, view="all") == ["loose"]
