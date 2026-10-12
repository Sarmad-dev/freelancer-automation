from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session as DbSession

from app.db.models_workflow import Notification
from tests.conftest import add_member, make_user, second_client

NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


def nurl(wid: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{wid}/notifications{suffix}"


def turl(wid: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{wid}/tasks{suffix}"


def freeze(monkeypatch: pytest.MonkeyPatch, now: datetime = NOW) -> None:
    for target in (
        "app.routers.tasks.utcnow",
        "app.services.tasks.utcnow",
        "app.services.notifications.utcnow",
    ):
        monkeypatch.setattr(target, lambda: now)


def task(client: TestClient, wid: str, title: str, **extra: Any) -> dict[str, Any]:
    res = client.post(turl(wid), json={"title": title, **extra})
    assert res.status_code == 201, res.text
    return res.json()


def unread(client: TestClient, wid: str) -> int:
    res = client.get(nurl(wid, "/unread-count"))
    assert res.status_code == 200, res.text
    return res.json()["unread"]


@pytest.fixture
def other(client: TestClient) -> TestClient:
    return second_client(client)


class TestProducing:
    def test_a_task_that_comes_due_notifies_once_however_often_you_look(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wid = make_user(client)["workspace_id"]
        freeze(monkeypatch)
        task(client, wid, "Send quote", due_at="2026-06-01T09:00:00Z", due_timezone="Europe/Berlin")
        assert unread(client, wid) == 1
        assert unread(client, wid) == 1
        items = client.get(nurl(wid)).json()["items"]
        assert unread(client, wid) == 1 and len(items) == 1
        assert items[0]["kind"] == "task_due" and items[0]["title"] == "Due: Send quote"
        assert (
            "2026-06-01 11:00 (Europe/Berlin)" in items[0]["body"]
        )  # shown in the task's own zone
        assert items[0]["link"] == "/tasks" and items[0]["read_at"] is None

    def test_a_reminder_and_the_due_time_are_separate_notifications(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wid = make_user(client)["workspace_id"]
        freeze(monkeypatch)
        task(client, wid, "Call", due_at="2026-06-01T11:00:00Z", remind_at="2026-06-01T10:00:00Z")
        kinds = sorted(n["kind"] for n in client.get(nurl(wid)).json()["items"])
        assert kinds == ["task_due", "task_reminder"]

    def test_only_the_reminder_fires_before_the_task_is_due(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wid = make_user(client)["workspace_id"]
        freeze(monkeypatch)
        task(
            client, wid, "Prepare", due_at="2026-06-01T15:00:00Z", remind_at="2026-06-01T11:00:00Z"
        )
        assert [n["kind"] for n in client.get(nurl(wid)).json()["items"]] == ["task_reminder"]

    def test_future_dated_done_and_dismissed_tasks_do_not_notify(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wid = make_user(client)["workspace_id"]
        freeze(monkeypatch)
        task(client, wid, "future", due_at="2026-06-02T09:00:00Z")
        task(client, wid, "undated")
        done = task(client, wid, "done", due_at="2026-06-01T09:00:00Z")
        gone = task(client, wid, "dismissed", due_at="2026-06-01T09:00:00Z")
        client.post(turl(wid, f"/{done['id']}/complete"))
        client.post(turl(wid, f"/{gone['id']}/dismiss"))
        assert unread(client, wid) == 0

    def test_long_overdue_tasks_do_not_flood_the_first_visit(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wid = make_user(client)["workspace_id"]
        freeze(monkeypatch)
        task(client, wid, "ancient", due_at="2026-01-01T09:00:00Z")
        task(client, wid, "recent", due_at="2026-05-30T09:00:00Z")
        assert [n["title"] for n in client.get(nurl(wid)).json()["items"]] == ["Due: recent"]

    def test_completing_a_task_settles_its_notifications(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wid = make_user(client)["workspace_id"]
        freeze(monkeypatch)
        t = task(client, wid, "Send quote", due_at="2026-06-01T09:00:00Z")
        assert unread(client, wid) == 1
        client.post(turl(wid, f"/{t['id']}/complete"))
        assert unread(client, wid) == 0
        client.post(turl(wid, f"/{t['id']}/reopen"))
        assert unread(client, wid) == 0  # already notified for that time

    def test_rescheduling_settles_the_old_notification_and_gives_the_new_time_its_own(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wid = make_user(client)["workspace_id"]
        freeze(monkeypatch)
        t = task(client, wid, "Send quote", due_at="2026-06-01T09:00:00Z")
        assert unread(client, wid) == 1
        client.post(turl(wid, f"/{t['id']}/reschedule"), json={"due_at": "2026-06-01T11:00:00Z"})
        assert unread(client, wid) == 1  # the new time has also passed: a fresh notification
        client.post(turl(wid, f"/{t['id']}/reschedule"), json={"due_at": "2026-06-03T11:00:00Z"})
        assert unread(client, wid) == 0
        assert len(client.get(nurl(wid)).json()["items"]) == 2  # history is kept, just read

    def test_a_snoozed_reminder_fires_at_its_new_time(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wid = make_user(client)["workspace_id"]
        freeze(monkeypatch)
        t = task(
            client, wid, "Prep", due_at="2026-06-02T09:00:00Z", remind_at="2026-06-01T10:00:00Z"
        )
        assert unread(client, wid) == 1
        client.post(turl(wid, f"/{t['id']}/snooze"), json={"remind_at": "2026-06-01T20:00:00Z"})
        assert unread(client, wid) == 0
        freeze(monkeypatch, NOW + timedelta(hours=9))
        assert unread(client, wid) == 1

    def test_a_burst_is_capped_and_the_most_recently_due_tasks_win(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wid = make_user(client)["workspace_id"]
        freeze(monkeypatch)
        monkeypatch.setattr("app.services.notifications.MAX_PER_SYNC", 3)
        for i in range(5):
            task(client, wid, f"t{i}", due_at=f"2026-06-01T0{i}:00:00Z")
        titles = sorted(n["title"] for n in client.get(nurl(wid)).json()["items"])
        assert titles == ["Due: t2", "Due: t3", "Due: t4"]


class TestReading:
    def make_due(
        self, client: TestClient, wid: str, monkeypatch: pytest.MonkeyPatch, n: int = 2
    ) -> None:
        freeze(monkeypatch)
        for i in range(n):
            task(client, wid, f"Task {i}", due_at=f"2026-06-01T0{i + 1}:00:00Z")

    def test_listing_is_newest_first_filterable_and_paged(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wid = make_user(client)["workspace_id"]
        self.make_due(client, wid, monkeypatch, 3)
        everything = client.get(nurl(wid)).json()
        assert everything["total"] == 3
        first = everything["items"][0]
        client.post(nurl(wid, f"/{first['id']}/read"))
        assert client.get(nurl(wid), params={"unread": "true"}).json()["total"] == 2
        page = client.get(nurl(wid), params={"limit": 2, "offset": 2}).json()
        assert len(page["items"]) == 1 and page["total"] == 3
        assert client.get(nurl(wid), params={"sort": "title"}).status_code == 422

    def test_mark_one_and_mark_all_read(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wid = make_user(client)["workspace_id"]
        self.make_due(client, wid, monkeypatch)
        item = client.get(nurl(wid)).json()["items"][0]
        done = client.post(nurl(wid, f"/{item['id']}/read")).json()
        assert done["read_at"] is not None and unread(client, wid) == 1
        again = client.post(nurl(wid, f"/{item['id']}/read")).json()
        assert again["read_at"].rstrip("Z") == done["read_at"].rstrip("Z")  # idempotent
        assert client.post(nurl(wid, "/read-all")).json() == {"marked": 1}
        assert unread(client, wid) == 0 and client.post(nurl(wid, "/read-all")).json() == {
            "marked": 0
        }

    def test_links_are_only_ever_relative_paths(self, client: TestClient, db: DbSession) -> None:
        user = make_user(client)
        wid = user["workspace_id"]
        for i, link in enumerate(
            ("/tasks", "https://evil.example", "//evil.example", "javascript:alert(1)", None)
        ):
            db.add(
                Notification(
                    workspace_id=uuid.UUID(wid),
                    user_id=uuid.UUID(user["me"]["user"]["id"]),
                    kind="x",
                    title=f"n{i}",
                    link=link,
                )
            )
        db.commit()
        links = {n["title"]: n["link"] for n in client.get(nurl(wid)).json()["items"]}
        assert links == {"n0": "/tasks", "n1": None, "n2": None, "n3": None, "n4": None}


class TestIsolation:
    def test_notifications_are_personal(
        self, client: TestClient, other: TestClient, db: DbSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        owner, member = make_user(client), make_user(other)
        wid = owner["workspace_id"]
        add_member(db, wid, member["me"]["user"]["id"])
        freeze(monkeypatch)
        task(client, wid, "Mine", due_at="2026-06-01T09:00:00Z")
        assert unread(client, wid) == 1
        mine = client.get(nurl(wid)).json()["items"][0]
        # The other member of the same workspace sees none of it and cannot touch it.
        assert unread(other, wid) == 0 and other.get(nurl(wid)).json()["total"] == 0
        assert other.post(nurl(wid, f"/{mine['id']}/read")).status_code == 404
        assert other.post(nurl(wid, "/read-all")).json() == {"marked": 0}
        assert unread(client, wid) == 1

    def test_other_workspaces_are_unreachable(self, client: TestClient, other: TestClient) -> None:
        a, b = make_user(client), make_user(other)
        assert other.get(nurl(a["workspace_id"])).status_code == 404
        assert other.get(nurl(a["workspace_id"], "/unread-count")).status_code == 404
        assert other.post(nurl(a["workspace_id"], "/read-all")).status_code == 404
        assert unread(other, b["workspace_id"]) == 0

    def test_unauthenticated_requests_are_refused(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        client.cookies.clear()
        assert client.get(nurl(wid)).status_code == 401
        assert client.get(nurl(wid, "/unread-count")).status_code == 401
        assert client.post(nurl(wid, "/read-all")).status_code == 401

    def test_unknown_notification_is_a_404(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        assert client.post(nurl(wid, f"/{uuid.uuid4()}/read")).status_code == 404


def test_seeded_style_notifications_are_not_duplicated_by_sync(
    client: TestClient, db: DbSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = make_user(client)
    wid = user["workspace_id"]
    freeze(monkeypatch)
    t = task(client, wid, "x", due_at="2026-06-01T09:00:00Z")
    unread(client, wid)
    key = db.scalar(
        select(Notification.dedupe_key).where(Notification.workspace_id == uuid.UUID(wid))
    )
    assert key is not None and key.startswith(f"task:{t['id']}:due:")
    db.execute(
        update(Notification).where(Notification.workspace_id == uuid.UUID(wid)).values(read_at=None)
    )
    db.commit()
    unread(client, wid)
    assert (
        len(
            db.scalars(
                select(Notification).where(Notification.workspace_id == uuid.UUID(wid))
            ).all()
        )
        == 1
    )
