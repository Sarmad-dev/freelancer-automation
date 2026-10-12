from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db.models import AuditEvent
from app.db.models_crm import Activity, Lead
from app.db.models_email import SuppressionEntry
from tests.conftest import add_member, make_user, second_client


def lurl(wid: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{wid}/leads{suffix}"


def lead(client: TestClient, wid: str, title: str = "Website rebuild", **extra: object) -> dict:  # type: ignore[type-arg]
    res = client.post(lurl(wid), json={"title": title, **extra})
    assert res.status_code == 201, res.text
    return res.json()


def tag(client: TestClient, wid: str, name: str) -> str:
    res = client.post(f"/api/v1/workspaces/{wid}/tags", json={"name": name})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def titles(client: TestClient, wid: str, **params: object) -> list[str]:
    res = client.get(lurl(wid), params=params)  # type: ignore[arg-type]
    assert res.status_code == 200, res.text
    return [x["title"] for x in res.json()["items"]]


def profile(client: TestClient, wid: str, **fields: object) -> None:
    res = client.patch(f"/api/v1/workspaces/{wid}/profile", json=fields)
    assert res.status_code == 200, res.text


@pytest.fixture
def other(client: TestClient) -> TestClient:
    return second_client(client)


class TestCreate:
    def test_manual_entry_needs_nothing_but_a_title(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        made = lead(client, wid)
        assert made["status"] == "new" and made["stage"]["key"] == "new"
        assert made["source"] == "manual" and made["source_retrieved_at"] is None
        assert made["company"] is None and made["contact"] is None and made["tags"] == []
        assert made["is_sample"] is False and made["archived_at"] is None
        # Almost nothing is known, so there is no number rather than a made-up one.
        assert made["fit_score"] is None and made["fit_band"] == "insufficient"
        assert made["fit_explanation"]["method"] == "rules"
        timeline = client.get(lurl(wid, f"/{made['id']}/activities")).json()
        assert [a["summary"] for a in timeline["items"]] == ["Lead created"]

    def test_company_and_contact_can_be_described_inline_and_are_reused(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        first = lead(
            client,
            wid,
            company_name="Acme Studio",
            company_website="acme.example",
            contact_name="Ada Byron",
            contact_email="Ada@Acme.example",
        )
        assert first["company"]["name"] == "Acme Studio"
        assert first["contact"] == {
            "id": first["contact"]["id"],
            "full_name": "Ada Byron",
            "email": "ada@acme.example",
        }
        second = lead(
            client,
            wid,
            "Second project",
            company_name="Something Else",
            company_website="https://www.acme.example/",
            contact_email="ada@acme.example",
        )
        assert second["company"]["id"] == first["company"]["id"]  # matched by website
        assert second["contact"]["id"] == first["contact"]["id"]  # matched by email
        companies = client.get(f"/api/v1/workspaces/{wid}/companies").json()
        contacts = client.get(f"/api/v1/workspaces/{wid}/contacts").json()
        assert companies["total"] == 1 and contacts["total"] == 1
        assert companies["items"][0]["lead_count"] == 2

    def test_a_lead_inherits_the_company_of_its_contact(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        c = client.post(f"/api/v1/workspaces/{wid}/companies", json={"name": "Acme"}).json()
        p = client.post(
            f"/api/v1/workspaces/{wid}/contacts",
            json={"full_name": "Ada", "company_id": c["id"]},
        ).json()
        made = lead(client, wid, contact_id=p["id"])
        assert made["company"]["id"] == c["id"]

    def test_company_name_alone_matches_an_existing_company_case_insensitively(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        a = lead(client, wid, "A", company_name="Acme Studio")
        b = lead(client, wid, "B", company_name="  ACME   studio ")
        assert a["company"]["id"] == b["company"]["id"]

    def test_a_new_contact_needs_a_name(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        res = client.post(lurl(wid), json={"title": "x", "contact_email": "new@example.com"})
        assert res.status_code == 422 and "contact_name" in res.json()["error"]["fields"]

    def test_existing_ids_and_new_descriptions_are_mutually_exclusive(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        c = client.post(f"/api/v1/workspaces/{wid}/companies", json={"name": "A"}).json()
        res = client.post(
            lurl(wid), json={"title": "x", "company_id": c["id"], "company_name": "B"}
        )
        assert res.status_code == 422

    @pytest.mark.parametrize(
        "body",
        [
            {"title": ""},
            {"title": "x" * 201},
            {"title": "a\x00b"},
            {"title": "x", "status": "maybe"},
            {"title": "x", "budget_signal": "huge"},
            {"title": "x", "fit_score": 100},
            {"title": "x", "stage_id": str(uuid.uuid4())},
            {"title": "x", "workspace_id": str(uuid.uuid4())},
            {"title": "x", "is_sample": True},
            {"title": "x", "company_website": "javascript:alert(1)"},
            {"title": "x", "contact_email": "nope", "contact_name": "n"},
            {"title": "x", "tag_ids": [str(uuid.uuid4())]},
            {"title": "x", "company_id": str(uuid.uuid4())},
            {"title": "x", "contact_id": str(uuid.uuid4())},
            {"title": "x", "notes": "x" * 4001},
        ],
    )
    def test_invalid_input_is_rejected_and_nothing_is_saved(
        self, client: TestClient, body: dict[str, object]
    ) -> None:
        wid = make_user(client)["workspace_id"]
        res = client.post(lurl(wid), json=body)
        assert res.status_code == 422, (body, res.text)
        assert client.get(lurl(wid)).json()["total"] == 0
        assert client.get(f"/api/v1/workspaces/{wid}/companies").json()["total"] == 0

    def test_markup_is_stored_as_inert_text(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        evil = "<img src=x onerror=alert(1)> {{7*7}}"
        made = lead(client, wid, evil, notes=evil)
        assert made["title"] == evil and made["notes"] == evil

    def test_naive_due_dates_are_read_as_utc(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        made = lead(client, wid, next_action="Call", next_action_at="2030-01-02T09:00:00")
        assert made["next_action_at"].startswith("2030-01-02T09:00:00")

    def test_tags_can_be_attached_at_creation(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        t1, t2 = tag(client, wid, "Warm"), tag(client, wid, "SaaS")
        made = lead(client, wid, tag_ids=[t1, t2, t1])
        assert sorted(t["name"] for t in made["tags"]) == ["SaaS", "Warm"]

    def test_creation_is_audited_without_content(self, client: TestClient, db: DbSession) -> None:
        wid = make_user(client)["workspace_id"]
        lead(client, wid, "Very Secret Title", notes="secret notes")
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.workspace_id == uuid.UUID(wid))
        ).all()
        assert "leads.created" in {e.action for e in events}
        assert "Secret" not in " ".join(str(e.details) for e in events)


class TestUpdate:
    def test_status_changes_move_the_stage_and_write_the_timeline(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        made = lead(client, wid)
        res = client.patch(lurl(wid, f"/{made['id']}"), json={"status": "contacted"})
        got = res.json()
        assert res.status_code == 200 and got["status"] == "contacted"
        assert got["stage"]["key"] == "contacted" and got["last_activity_at"]
        timeline = client.get(lurl(wid, f"/{made['id']}/activities")).json()["items"]
        change = timeline[0]
        assert change["kind"] == "stage_change" and change["details"] == {
            "from": "new",
            "to": "contacted",
        }

    def test_choosing_a_stage_drives_the_status_when_names_line_up(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        stages = {
            s["key"]: s["id"]
            for s in client.get(f"/api/v1/workspaces/{wid}/pipeline/stages").json()["items"]
        }
        made = lead(client, wid)
        won = client.patch(lurl(wid, f"/{made['id']}"), json={"stage_id": stages["won"]}).json()
        assert won["status"] == "won" and won["stage"]["key"] == "won"
        # "meeting" has no matching status: the stage moves, the status is left alone.
        meeting = client.patch(
            lurl(wid, f"/{made['id']}"), json={"stage_id": stages["meeting"]}
        ).json()
        assert meeting["stage"]["key"] == "meeting" and meeting["status"] == "won"
        clash = client.patch(
            lurl(wid, f"/{made['id']}"),
            json={"stage_id": stages["lost"], "status": "qualified"},
        )
        assert clash.status_code == 422 and "status" in clash.json()["error"]["fields"]

    def test_unknown_or_foreign_stage_is_rejected(
        self, client: TestClient, other: TestClient
    ) -> None:
        a, b = make_user(client), make_user(other)
        foreign = other.get(f"/api/v1/workspaces/{b['workspace_id']}/pipeline/stages").json()[
            "items"
        ][0]
        made = lead(client, a["workspace_id"])
        res = client.patch(
            lurl(a["workspace_id"], f"/{made['id']}"), json={"stage_id": foreign["id"]}
        )
        assert res.status_code == 422 and "stage_id" in res.json()["error"]["fields"]

    def test_scoring_inputs_trigger_a_new_score_and_other_edits_do_not(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        profile(client, wid, services=["Web development"], industries=["SaaS"])
        made = lead(client, wid, "Plain title")
        url = lurl(wid, f"/{made['id']}")
        scored_at = made["fit_scored_at"].rstrip("Z")  # SQLite drops the zone, PostgreSQL keeps it
        client.patch(url, json={"next_action": "Call them"})
        assert client.get(url).json()["fit_scored_at"].rstrip("Z") == scored_at
        better = client.patch(
            url,
            json={
                "notes": "Needs web development help",
                "industry": "SaaS",
                "budget_signal": "high",
            },
        ).json()
        assert better["fit_scored_at"].rstrip("Z") != scored_at
        assert better["fit_band"] == "strong" and better["fit_score"] >= 70

    def test_patch_semantics_blank_clears_but_required_fields_stay(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        made = lead(client, wid, notes="n", industry="SaaS", next_action="Call")
        got = client.patch(
            lurl(wid, f"/{made['id']}"),
            json={"notes": "", "industry": None, "title": None, "status": None},
        ).json()
        assert got["notes"] is None and got["industry"] is None
        assert got["title"] == "Website rebuild" and got["status"] == "new"
        assert got["next_action"] == "Call"

    def test_linking_and_unlinking_companies(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        c = client.post(f"/api/v1/workspaces/{wid}/companies", json={"name": "Acme"}).json()
        made = lead(client, wid)
        url = lurl(wid, f"/{made['id']}")
        assert client.patch(url, json={"company_id": c["id"]}).json()["company"]["id"] == c["id"]
        assert client.patch(url, json={"company_id": None}).json()["company"] is None
        res = client.patch(url, json={"company_id": str(uuid.uuid4())})
        assert res.status_code == 422

    def test_archived_leads_are_read_only_until_restored(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        made = lead(client, wid)
        url = lurl(wid, f"/{made['id']}")
        assert client.post(f"{url}/archive").json()["archived_at"]
        blocked = client.patch(url, json={"notes": "x"})
        assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "lead_archived"
        assert client.post(f"{url}/restore").json()["archived_at"] is None
        assert client.patch(url, json={"notes": "x"}).status_code == 200
        kinds = [a["summary"] for a in client.get(f"{url}/activities").json()["items"]]
        assert "Lead archived" in kinds and "Lead restored" in kinds

    def test_extra_or_server_owned_fields_are_rejected(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        made = lead(client, wid)
        for body in (
            {"fit_score": 99},
            {"is_sample": True},
            {"archived_at": None},
            {"workspace_id": wid},
        ):
            assert client.patch(lurl(wid, f"/{made['id']}"), json=body).status_code == 422


class TestListing:
    @pytest.fixture
    def board(self, client: TestClient) -> str:
        wid = make_user(client)["workspace_id"]
        profile(client, wid, services=["Web development"], industries=["SaaS"])
        warm, saas = tag(client, wid, "Warm"), tag(client, wid, "SaaS")
        now = datetime.now(UTC)
        lead(
            client, wid, "Alpha rebuild", company_name="Acme Studio", contact_name="Ada Byron",
            contact_email="ada@acme.example", status="qualified", industry="SaaS", budget_signal="high",
            notes="web development for a SaaS product", tag_ids=[warm, saas], source="Referral",
            next_action="Send proposal", next_action_at=(now - timedelta(days=2)).isoformat(),
        )  # fmt: skip
        lead(client, wid, "Bravo audit", company_name="Bolt Co", status="new", industry="Retail", budget_signal="low", tag_ids=[saas])  # fmt: skip
        lead(client, wid, "charlie inquiry", status="lost", next_action="Archive it", next_action_at=(now - timedelta(days=1)).isoformat())  # fmt: skip
        lead(client, wid, "Delta project", company_name="Dune Ltd", status="contacted", next_action_at=(now + timedelta(days=5)).isoformat(), next_action="Follow up")  # fmt: skip
        return wid

    def test_default_list_is_newest_first_and_paginates(
        self, client: TestClient, board: str
    ) -> None:
        assert titles(client, board) == [
            "Delta project", "charlie inquiry", "Bravo audit", "Alpha rebuild",
        ]  # fmt: skip
        page = client.get(lurl(board), params={"limit": 3, "offset": 3}).json()
        assert page["total"] == 4 and len(page["items"]) == 1 and page["limit"] == 3

    def test_search_covers_title_notes_company_and_contact(
        self, client: TestClient, board: str
    ) -> None:
        assert titles(client, board, q="alpha") == ["Alpha rebuild"]
        assert titles(client, board, q="SAAS product") == ["Alpha rebuild"]  # case-insensitive
        assert titles(client, board, q="product saas") == []  # a phrase, not separate words
        assert titles(client, board, q="saas product") == ["Alpha rebuild"]
        assert titles(client, board, q="bolt") == ["Bravo audit"]
        assert titles(client, board, q="byron") == ["Alpha rebuild"]
        assert titles(client, board, q="ada@acme") == ["Alpha rebuild"]
        assert titles(client, board, q="%") == [] and titles(client, board, q="_") == []

    def test_status_filter_accepts_several_values(self, client: TestClient, board: str) -> None:
        assert sorted(titles(client, board, status=["new", "lost"])) == [
            "Bravo audit",
            "charlie inquiry",
        ]
        assert client.get(lurl(board), params={"status": "maybe"}).status_code == 422

    def test_tag_company_source_and_industry_filters(self, client: TestClient, board: str) -> None:
        tags = {
            t["name"]: t["id"]
            for t in client.get(f"/api/v1/workspaces/{board}/tags").json()["items"]
        }
        assert sorted(titles(client, board, tag_id=tags["SaaS"])) == [
            "Alpha rebuild",
            "Bravo audit",
        ]
        assert titles(client, board, tag_id=tags["Warm"]) == ["Alpha rebuild"]
        companies = {
            c["name"]: c["id"]
            for c in client.get(f"/api/v1/workspaces/{board}/companies").json()["items"]
        }
        assert titles(client, board, company_id=companies["Bolt Co"]) == ["Bravo audit"]
        assert titles(client, board, source="referral") == ["Alpha rebuild"]
        assert titles(client, board, industry="ret") == ["Bravo audit"]

    def test_fit_bands_and_unscored(self, client: TestClient, board: str) -> None:
        assert titles(client, board, fit="strong") == ["Alpha rebuild"]
        weak = titles(client, board, fit="weak")
        assert "Alpha rebuild" not in weak
        assert set(titles(client, board, fit="unscored")) | set(weak) | {"Alpha rebuild"} >= set(
            titles(client, board)
        )

    def test_overdue_and_next_action_filters(self, client: TestClient, board: str) -> None:
        # "charlie inquiry" is lost, so its past-due action does not count as overdue.
        assert titles(client, board, overdue="true") == ["Alpha rebuild"]
        assert sorted(titles(client, board, has_next_action="false")) == ["Bravo audit"]

    def test_sorting_is_case_insensitive_and_nulls_always_last(
        self, client: TestClient, board: str
    ) -> None:
        assert titles(client, board, sort="title") == [
            "Alpha rebuild", "Bravo audit", "charlie inquiry", "Delta project",
        ]  # fmt: skip
        by_fit = [
            x["fit_score"]
            for x in client.get(lurl(board), params={"sort": "-fit_score"}).json()["items"]
        ]
        scored = [s for s in by_fit if s is not None]
        assert by_fit[: len(scored)] == sorted(scored, reverse=True)
        assert all(s is None for s in by_fit[len(scored) :])
        asc = [
            x["fit_score"]
            for x in client.get(lurl(board), params={"sort": "fit_score"}).json()["items"]
        ]
        assert all(s is None for s in asc[len([s for s in asc if s is not None]) :])
        for bad in ("password", "title,status,fit_score,created_at", "-"):
            assert client.get(lurl(board), params={"sort": bad}).status_code == 422, bad

    def test_archived_and_sample_visibility(
        self, client: TestClient, board: str, db: DbSession
    ) -> None:
        first = client.get(lurl(board), params={"q": "alpha"}).json()["items"][0]
        client.post(lurl(board, f"/{first['id']}/archive"))
        assert "Alpha rebuild" not in titles(client, board)
        assert titles(client, board, archived="archived") == ["Alpha rebuild"]
        assert len(titles(client, board, archived="all")) == 4
        row = db.get(Lead, uuid.UUID(first["id"]))
        row.is_sample = True  # type: ignore[union-attr]
        db.commit()
        assert titles(client, board, archived="all", sample="only") == ["Alpha rebuild"]
        assert "Alpha rebuild" not in titles(client, board, archived="all", sample="exclude")

    def test_each_row_carries_what_the_table_needs(self, client: TestClient, board: str) -> None:
        row = client.get(lurl(board), params={"q": "alpha"}).json()["items"][0]
        assert (
            row["company"]["name"] == "Acme Studio"
            and row["contact"]["email"] == "ada@acme.example"
        )
        assert sorted(t["name"] for t in row["tags"]) == ["SaaS", "Warm"]
        assert row["stage"]["key"] == "qualified" and row["fit_band"] == "strong"
        assert "fit_explanation" not in row  # the list stays light; detail has the breakdown


class TestTagsAndBulkTagging:
    def test_replace_tags(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        a, b = tag(client, wid, "A"), tag(client, wid, "B")
        made = lead(client, wid, tag_ids=[a])
        got = client.put(lurl(wid, f"/{made['id']}/tags"), json={"tag_ids": [b]}).json()
        assert [t["name"] for t in got["tags"]] == ["B"]
        assert (
            client.put(lurl(wid, f"/{made['id']}/tags"), json={"tag_ids": []}).json()["tags"] == []
        )
        bad = client.put(lurl(wid, f"/{made['id']}/tags"), json={"tag_ids": [str(uuid.uuid4())]})
        assert bad.status_code == 422

    def test_bulk_add_and_remove_report_what_changed(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        a, b = tag(client, wid, "A"), tag(client, wid, "B")
        ids = [lead(client, wid, f"L{i}", tag_ids=[a] if i == 0 else [])["id"] for i in range(3)]
        res = client.post(lurl(wid, "/bulk-tags"), json={"lead_ids": ids, "add_tag_ids": [a, b]})
        assert res.json() == {"leads": 3, "tags_added": 5, "tags_removed": 0}  # L0 already had A
        again = client.post(lurl(wid, "/bulk-tags"), json={"lead_ids": ids, "add_tag_ids": [a]})
        assert again.json()["tags_added"] == 0  # idempotent
        gone = client.post(lurl(wid, "/bulk-tags"), json={"lead_ids": ids, "remove_tag_ids": [a]})
        assert gone.json() == {"leads": 3, "tags_added": 0, "tags_removed": 3}
        left = {t["name"] for x in client.get(lurl(wid)).json()["items"] for t in x["tags"]}
        assert left == {"B"}

    def test_bulk_tagging_is_all_or_nothing_and_workspace_scoped(
        self, client: TestClient, other: TestClient
    ) -> None:
        a, b = make_user(client), make_user(other)
        mine = lead(client, a["workspace_id"])
        theirs = lead(other, b["workspace_id"], "Theirs")
        mine_tag, their_tag = (
            tag(client, a["workspace_id"], "Mine"),
            tag(other, b["workspace_id"], "Theirs"),
        )
        res = client.post(
            lurl(a["workspace_id"], "/bulk-tags"),
            json={"lead_ids": [mine["id"], theirs["id"]], "add_tag_ids": [mine_tag]},
        )
        assert res.status_code == 404
        assert client.get(lurl(a["workspace_id"], f"/{mine['id']}")).json()["tags"] == []
        foreign_tag = client.post(
            lurl(a["workspace_id"], "/bulk-tags"),
            json={"lead_ids": [mine["id"]], "add_tag_ids": [their_tag]},
        )
        assert foreign_tag.status_code == 422

    @pytest.mark.parametrize(
        "body",
        [
            {"lead_ids": [], "add_tag_ids": ["x"]},
            {"lead_ids": [str(uuid.uuid4())]},
            {"lead_ids": [str(uuid.uuid4())], "add_tag_ids": []},
            {"lead_ids": [str(uuid.uuid4())] * 201, "add_tag_ids": [str(uuid.uuid4())]},
        ],
    )
    def test_malformed_bulk_requests_are_rejected(
        self, client: TestClient, body: dict[str, object]
    ) -> None:
        wid = make_user(client)["workspace_id"]
        assert client.post(lurl(wid, "/bulk-tags"), json=body).status_code == 422

    def test_tag_and_untag_on_the_same_request_is_rejected(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        t = tag(client, wid, "A")
        made = lead(client, wid)
        res = client.post(
            lurl(wid, "/bulk-tags"),
            json={"lead_ids": [made["id"]], "add_tag_ids": [t], "remove_tag_ids": [t]},
        )
        assert res.status_code == 422


class TestTimeline:
    def test_notes_calls_and_meetings_are_logged_newest_first(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        made = lead(client, wid)
        url = lurl(wid, f"/{made['id']}/activities")
        for kind, summary in (
            ("note", "Intro email"),
            ("call", "Discovery call"),
            ("meeting", "Demo"),
        ):
            res = client.post(url, json={"kind": kind, "summary": summary, "body": "details"})
            assert res.status_code == 201 and res.json()["kind"] == kind
        items = client.get(url).json()["items"]
        assert [i["summary"] for i in items[:3]] == ["Demo", "Discovery call", "Intro email"]
        assert items[0]["actor_user_id"] and items[-1]["summary"] == "Lead created"
        assert client.get(lurl(wid, f"/{made['id']}")).json()["last_activity_at"]
        assert client.get(url, params={"limit": 2}).json()["total"] == 4

    @pytest.mark.parametrize(
        "body",
        [
            {"kind": "system", "summary": "forged"},
            {"kind": "stage_change", "summary": "forged"},
            {"kind": "note", "summary": ""},
            {"kind": "note", "summary": "x", "details": {"a": 1}},
            {"kind": "note", "summary": "x", "occurred_at": "2020-01-01T00:00:00Z"},
        ],
    )
    def test_system_entries_cannot_be_forged(
        self, client: TestClient, body: dict[str, object]
    ) -> None:
        wid = make_user(client)["workspace_id"]
        made = lead(client, wid)
        assert client.post(lurl(wid, f"/{made['id']}/activities"), json=body).status_code == 422

    def test_markup_in_notes_stays_text(self, client: TestClient, db: DbSession) -> None:
        wid = make_user(client)["workspace_id"]
        made = lead(client, wid)
        res = client.post(
            lurl(wid, f"/{made['id']}/activities"),
            json={"summary": "<b>x</b>", "body": "<script>alert(1)</script>"},
        )
        assert res.json()["summary"] == "<b>x</b>" and "<script>" in res.json()["body"]
        row = db.scalar(select(Activity).where(Activity.id == uuid.UUID(res.json()["id"])))
        assert row is not None and row.kind == "note"


class TestFitScoreOnTheLead:
    def test_profile_changes_make_scores_stale_until_recomputed(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        profile(client, wid, services=["Web development"], industries=["SaaS"])
        made = lead(
            client, wid, "Web development project", notes="web development", industry="SaaS"
        )
        url = lurl(wid, f"/{made['id']}")
        assert client.get(url).json()["fit_stale"] is False
        profile(client, wid, services=["Illustration"])
        stale = client.get(url).json()
        assert (
            stale["fit_stale"] is True and stale["fit_band"] == "strong"
        )  # old score still shown, flagged
        fresh = client.post(f"{url}/score").json()
        assert fresh["fit_stale"] is False
        assert fresh["fit_explanation"]["criteria"][0]["outcome"] == "miss"

    def test_a_score_always_explains_itself(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        profile(client, wid, services=["Web development"], industries=["SaaS"])
        made = lead(client, wid, "Web development", industry="SaaS", budget_signal="medium")
        e = made["fit_explanation"]
        assert e["method"] == "rules" and e["version"] == 1
        assert {c["key"] for c in e["criteria"]} == {
            "service_match",
            "industry",
            "geography",
            "company_size",
            "budget",
        }
        for c in e["criteria"]:
            assert c["outcome"] in ("match", "partial", "miss", "unknown") and c["reason"]
            if c["outcome"] in ("match", "partial"):
                assert c["evidence"], c
        assert made["fit_score"] % 5 == 0


class TestDoNotContact:
    def test_suppressed_contacts_are_flagged_on_their_leads(
        self, client: TestClient, db: DbSession
    ) -> None:
        wid = make_user(client)["workspace_id"]
        made = lead(client, wid, contact_name="Stop", contact_email="stop@example.com")
        assert made["do_not_contact"] is False
        db.add(
            SuppressionEntry(
                workspace_id=uuid.UUID(wid),
                email_normalized="stop@example.com",
                reason="unsubscribe",
            )
        )
        db.commit()
        assert client.get(lurl(wid, f"/{made['id']}")).json()["do_not_contact"] is True
        assert client.get(lurl(wid)).json()["items"][0]["do_not_contact"] is True


class TestExport:
    def rows(self, res) -> list[list[str]]:  # type: ignore[no-untyped-def]
        assert res.status_code == 200, res.text
        return list(csv.reader(io.StringIO(res.text.lstrip("﻿"))))

    def test_owner_exports_the_filtered_leads_as_a_download(
        self, client: TestClient, db: DbSession
    ) -> None:
        wid = make_user(client)["workspace_id"]
        lead(
            client,
            wid,
            "Keep me",
            company_name="Acme",
            contact_name="Ada",
            contact_email="ada@acme.example",
        )
        lead(client, wid, "Other", status="lost")
        res = client.get(lurl(wid, "/export"), params={"status": "new"})
        assert res.headers["content-type"].startswith("text/csv")
        assert (
            "attachment" in res.headers["content-disposition"]
            and ".csv" in res.headers["content-disposition"]
        )
        assert (
            res.headers["cache-control"] == "no-store"
            and res.headers["x-content-type-options"] == "nosniff"
        )
        rows = self.rows(res)
        assert rows[0][:3] == ["title", "status", "stage"]
        assert [r[0] for r in rows[1:]] == ["Keep me"]
        assert rows[1][rows[0].index("email")] == "ada@acme.example"
        event = db.scalars(
            select(AuditEvent).where(
                AuditEvent.action == "leads.exported", AuditEvent.workspace_id == uuid.UUID(wid)
            )
        ).one()
        assert event.details == {"count": 1}

    def test_awkward_values_survive_a_round_trip(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        notes = 'He said "hello", then\nleft;\ttab, and 日本語 ✓'
        lead(client, wid, 'Comma, "quote" title', notes=notes)
        rows = self.rows(client.get(lurl(wid, "/export")))
        assert rows[1][0] == 'Comma, "quote" title' and rows[1][rows[0].index("notes")] == notes

    @pytest.mark.parametrize(
        "payload", ['=HYPERLINK("http://evil.example","x")', "+SUM(1+1)", "-2+3", "@cmd", "\t=1+1"]
    )
    def test_spreadsheet_formulas_are_neutralised(self, client: TestClient, payload: str) -> None:
        wid = make_user(client)["workspace_id"]
        lead(client, wid, payload, notes=payload)
        rows = self.rows(client.get(lurl(wid, "/export")))
        assert rows[1][0].startswith("'") and rows[1][rows[0].index("notes")].startswith("'")

    def test_members_cannot_export(
        self, client: TestClient, other: TestClient, db: DbSession
    ) -> None:
        owner, member = make_user(client), make_user(other)
        add_member(db, owner["workspace_id"], member["me"]["user"]["id"])
        lead(client, owner["workspace_id"])
        res = other.get(lurl(owner["workspace_id"], "/export"))
        assert res.status_code == 403
        assert other.get(lurl(owner["workspace_id"])).status_code == 200  # reading is still allowed

    def test_unauthenticated_and_foreign_requests_get_nothing(
        self, client: TestClient, other: TestClient
    ) -> None:
        a, b = make_user(client), make_user(other)
        lead(client, a["workspace_id"], "Mine")
        assert other.get(lurl(a["workspace_id"], "/export")).status_code == 404
        client.cookies.clear()
        assert client.get(lurl(a["workspace_id"], "/export")).status_code == 401
        lead(other, b["workspace_id"], "Theirs")
        rows = self.rows(other.get(lurl(b["workspace_id"], "/export")))
        assert [r[0] for r in rows[1:]] == ["Theirs"]

    def test_archived_leads_are_excluded_unless_asked_for(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        gone = lead(client, wid, "Gone")
        lead(client, wid, "Here")
        client.post(lurl(wid, f"/{gone['id']}/archive"))
        assert [r[0] for r in self.rows(client.get(lurl(wid, "/export")))[1:]] == ["Here"]
        both = self.rows(client.get(lurl(wid, "/export"), params={"archived": "all"}))
        assert sorted(r[0] for r in both[1:]) == ["Gone", "Here"]

    def test_oversized_exports_are_refused_rather_than_truncated(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wid = make_user(client)["workspace_id"]
        for i in range(3):
            lead(client, wid, f"L{i}")
        monkeypatch.setattr("app.routers.leads.MAX_EXPORT_ROWS", 2)
        res = client.get(lurl(wid, "/export"))
        assert res.status_code == 422 and res.json()["error"]["code"] == "export_too_large"


class TestPermissionsAndIsolation:
    def test_other_workspaces_leads_are_invisible_and_untouchable(
        self, client: TestClient, other: TestClient
    ) -> None:
        a, b = make_user(client), make_user(other)
        theirs = lead(other, b["workspace_id"], "Theirs", company_name="Hidden Co")
        wid = a["workspace_id"]
        url = lurl(wid, f"/{theirs['id']}")
        assert client.get(url).status_code == 404
        for method, suffix, body in (
            ("patch", "", {"notes": "x"}),
            ("post", "/archive", None),
            ("post", "/restore", None),
            ("post", "/score", None),
            ("put", "/tags", {"tag_ids": []}),
            ("get", "/activities", None),
            ("post", "/activities", {"summary": "x"}),
        ):
            kwargs = {"json": body} if body is not None else {}
            assert getattr(client, method)(url + suffix, **kwargs).status_code == 404, suffix
        assert titles(client, wid) == [] and titles(client, wid, q="hidden") == []
        # Referencing their company/contact/stage/tag from my workspace never works.
        their_company = other.get(f"/api/v1/workspaces/{b['workspace_id']}/companies").json()[
            "items"
        ][0]
        res = client.post(lurl(wid), json={"title": "x", "company_id": their_company["id"]})
        assert res.status_code == 422
        assert other.get(lurl(wid)).status_code == 404

    def test_members_can_read_everything_but_change_nothing(
        self, client: TestClient, other: TestClient, db: DbSession
    ) -> None:
        owner, member = make_user(client), make_user(other)
        wid = owner["workspace_id"]
        add_member(db, wid, member["me"]["user"]["id"])
        made = lead(client, wid)
        t = tag(client, wid, "T")
        assert other.get(lurl(wid)).status_code == 200
        assert other.get(lurl(wid, f"/{made['id']}")).status_code == 200
        assert other.get(lurl(wid, f"/{made['id']}/activities")).status_code == 200
        base = lurl(wid, f"/{made['id']}")
        for method, url, body in (
            ("post", lurl(wid), {"title": "x"}),
            ("patch", base, {"notes": "x"}),
            ("post", f"{base}/archive", None),
            ("post", f"{base}/restore", None),
            ("post", f"{base}/score", None),
            ("put", f"{base}/tags", {"tag_ids": [t]}),
            ("post", f"{base}/activities", {"summary": "x"}),
            ("post", lurl(wid, "/bulk-tags"), {"lead_ids": [made["id"]], "add_tag_ids": [t]}),
        ):
            kwargs = {"json": body} if body is not None else {}
            assert getattr(other, method)(url, **kwargs).status_code == 403, (method, url)

    def test_unauthenticated_requests_are_refused(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        client.cookies.clear()
        assert client.get(lurl(wid)).status_code == 401
        assert client.post(lurl(wid), json={"title": "x"}).status_code == 401

    def test_writes_without_the_csrf_defences_are_refused(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        res = client.post(
            lurl(wid), json={"title": "x"}, headers={"Origin": "https://evil.example"}
        )
        assert res.status_code in (400, 403)
        assert client.get(lurl(wid)).json()["total"] == 0
