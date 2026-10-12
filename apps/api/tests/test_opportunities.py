from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db.models import AuditEvent
from app.db.models_crm import Activity, Opportunity
from tests.conftest import add_member, make_user, second_client


def ourl(wid: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{wid}/opportunities{suffix}"


def stages(client: TestClient, wid: str) -> dict[str, str]:
    items = client.get(f"/api/v1/workspaces/{wid}/pipeline/stages").json()["items"]
    return {s["key"]: s["id"] for s in items}


def make_lead(
    client: TestClient, wid: str, title: str = "Website rebuild", **extra: Any
) -> dict[str, Any]:
    res = client.post(f"/api/v1/workspaces/{wid}/leads", json={"title": title, **extra})
    assert res.status_code == 201, res.text
    return res.json()


def make_opp(client: TestClient, wid: str, lead_id: str, **extra: Any) -> dict[str, Any]:
    res = client.post(ourl(wid), json={"lead_id": lead_id, **extra})
    assert res.status_code == 201, res.text
    return res.json()


@pytest.fixture
def other(client: TestClient) -> TestClient:
    return second_client(client)


class TestCreate:
    def test_a_deal_inherits_the_leads_title_and_stage(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        lead = make_lead(client, wid, status="qualified")
        opp = make_opp(client, wid, lead["id"])
        assert opp["title"] == "Website rebuild" and opp["status"] == "open"
        assert opp["stage"]["key"] == "qualified" and opp["currency"] == "USD"
        assert (
            opp["value_amount"] is None
            and opp["probability"] is None
            and opp["weighted_value"] is None
        )
        assert (
            opp["lead"]["id"] == lead["id"] and opp["open_tasks"] == 0 and opp["is_sample"] is False
        )

    def test_a_won_or_lost_lead_starts_its_deal_in_the_first_open_stage(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        lost = make_lead(client, wid, status="lost")
        assert make_opp(client, wid, lost["id"])["stage"]["key"] == "new"

    def test_values_are_exact_decimals_and_currency_is_normalised(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        lead = make_lead(client, wid)
        opp = make_opp(
            client, wid, lead["id"], value_amount="12345.60", currency="eur", probability=40
        )
        assert opp["value_amount"] == "12345.60" and opp["currency"] == "EUR"
        assert opp["weighted_value"] == "4938.24"

    @pytest.mark.parametrize(
        ("body", "field"),
        [
            ({"value_amount": "12.345"}, "value_amount"),
            ({"value_amount": "-1"}, "value_amount"),
            ({"value_amount": "1" + "0" * 13}, "value_amount"),
            ({"value_amount": "abc"}, "value_amount"),
            ({"currency": "DOLLARS"}, "currency"),
            ({"currency": "U$"}, "currency"),
            ({"probability": 101}, "probability"),
            ({"probability": -1}, "probability"),
            ({"expected_close_date": "next week"}, "expected_close_date"),
            ({"title": ""}, "title"),
            ({"title": "x" * 201}, "title"),
            ({"next_action": "x" * 301}, "next_action"),
            ({"status": "won"}, "status"),
            ({"stage_id": "not-a-uuid"}, "stage_id"),
            ({"workspace_id": str(uuid.uuid4())}, "workspace_id"),
            ({"is_sample": True}, "is_sample"),
        ],
    )
    def test_invalid_input_is_rejected(
        self, client: TestClient, body: dict[str, Any], field: str
    ) -> None:
        wid = make_user(client)["workspace_id"]
        lead = make_lead(client, wid)
        res = client.post(ourl(wid), json={"lead_id": lead["id"], **body})
        assert res.status_code == 422 and field in res.json()["error"]["fields"], res.text
        assert client.get(ourl(wid)).json()["total"] == 0

    def test_a_new_deal_cannot_start_closed_or_in_an_unknown_stage(
        self, client: TestClient, other: TestClient
    ) -> None:
        a, b = make_user(client), make_user(other)
        wid = a["workspace_id"]
        lead = make_lead(client, wid)
        keys = stages(client, wid)
        foreign = stages(other, b["workspace_id"])["new"]
        for stage_id in (keys["won"], keys["lost"], foreign, str(uuid.uuid4())):
            res = client.post(ourl(wid), json={"lead_id": lead["id"], "stage_id": stage_id})
            assert res.status_code == 422 and "stage_id" in res.json()["error"]["fields"], stage_id

    def test_the_lead_must_exist_in_this_workspace_and_not_be_archived(
        self, client: TestClient, other: TestClient
    ) -> None:
        a, b = make_user(client), make_user(other)
        theirs = make_lead(other, b["workspace_id"])
        res = client.post(ourl(a["workspace_id"]), json={"lead_id": theirs["id"]})
        assert res.status_code == 422 and "lead_id" in res.json()["error"]["fields"]
        mine = make_lead(client, a["workspace_id"])
        client.post(f"/api/v1/workspaces/{a['workspace_id']}/leads/{mine['id']}/archive")
        blocked = client.post(ourl(a["workspace_id"]), json={"lead_id": mine["id"]})
        assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "lead_archived"

    def test_creation_is_written_to_the_leads_timeline(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        lead = make_lead(client, wid)
        opp = make_opp(client, wid, lead["id"], title="Big project")
        timeline = client.get(f"/api/v1/workspaces/{wid}/leads/{lead['id']}/activities").json()[
            "items"
        ]
        assert "Opportunity created: Big project" in [a["summary"] for a in timeline]
        deal = client.get(ourl(wid, f"/{opp['id']}/activities")).json()["items"]
        assert [a["summary"] for a in deal] == ["Opportunity created: Big project"]


class TestEdit:
    def test_patch_semantics(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        opp = make_opp(
            client, wid, make_lead(client, wid)["id"], value_amount="100.00", probability=50,
            expected_close_date="2030-01-01", next_action="Call",
        )  # fmt: skip
        url = ourl(wid, f"/{opp['id']}")
        got = client.patch(
            url, json={"value_amount": None, "next_action": "", "title": None, "currency": None}
        ).json()
        assert (
            got["value_amount"] is None
            and got["next_action"] is None
            and got["weighted_value"] is None
        )
        assert got["title"] == "Website rebuild" and got["currency"] == "USD"
        assert got["probability"] == 50 and got["expected_close_date"] == "2030-01-01"

    @pytest.mark.parametrize(
        "body",
        [
            {"status": "won"},
            {"stage_id": str(uuid.uuid4())},
            {"lead_id": str(uuid.uuid4())},
            {"closed_at": None},
        ],
    )
    def test_stage_and_status_only_change_through_the_move_action(
        self, client: TestClient, body: dict[str, Any]
    ) -> None:
        wid = make_user(client)["workspace_id"]
        opp = make_opp(client, wid, make_lead(client, wid)["id"])
        assert client.patch(ourl(wid, f"/{opp['id']}"), json=body).status_code == 422

    def test_only_lost_deals_have_a_loss_reason(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        opp = make_opp(client, wid, make_lead(client, wid)["id"])
        res = client.patch(ourl(wid, f"/{opp['id']}"), json={"loss_reason": "x"})
        assert res.status_code == 422 and "loss_reason" in res.json()["error"]["fields"]
        keys = stages(client, wid)
        client.post(ourl(wid, f"/{opp['id']}/move"), json={"stage_id": keys["lost"]})
        assert (
            client.patch(ourl(wid, f"/{opp['id']}"), json={"loss_reason": "Budget"}).json()[
                "loss_reason"
            ]
            == "Budget"
        )


class TestMoves:
    def test_moving_changes_the_stage_and_writes_both_timelines(
        self, client: TestClient, db: DbSession
    ) -> None:
        wid = make_user(client)["workspace_id"]
        lead = make_lead(client, wid)
        opp = make_opp(client, wid, lead["id"])
        keys = stages(client, wid)
        res = client.post(
            ourl(wid, f"/{opp['id']}/move"),
            json={"stage_id": keys["proposal"], "expected_stage_id": keys["new"]},
        )
        assert (
            res.status_code == 200
            and res.json()["stage"]["key"] == "proposal"
            and res.json()["status"] == "open"
        )
        deal = client.get(ourl(wid, f"/{opp['id']}/activities")).json()["items"]
        change = next(a for a in deal if a["kind"] == "stage_change")
        assert change["details"]["from"] == "new" and change["details"]["to"] == "proposal"
        on_lead = client.get(f"/api/v1/workspaces/{wid}/leads/{lead['id']}/activities").json()[
            "items"
        ]
        assert any(
            a["kind"] == "stage_change" and a["summary"] == "Deal moved to Proposal"
            for a in on_lead
        )

    def test_moving_to_the_same_stage_is_a_harmless_no_op(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        opp = make_opp(client, wid, make_lead(client, wid)["id"])
        keys = stages(client, wid)
        res = client.post(ourl(wid, f"/{opp['id']}/move"), json={"stage_id": keys["new"]})
        assert res.status_code == 200
        assert len(client.get(ourl(wid, f"/{opp['id']}/activities")).json()["items"]) == 1

    def test_unknown_foreign_and_malformed_stages_are_rejected(
        self, client: TestClient, other: TestClient
    ) -> None:
        a, b = make_user(client), make_user(other)
        wid = a["workspace_id"]
        opp = make_opp(client, wid, make_lead(client, wid)["id"])
        for stage_id in (str(uuid.uuid4()), stages(other, b["workspace_id"])["qualified"]):
            res = client.post(ourl(wid, f"/{opp['id']}/move"), json={"stage_id": stage_id})
            assert res.status_code == 422 and "stage_id" in res.json()["error"]["fields"], stage_id
        assert (
            client.post(ourl(wid, f"/{opp['id']}/move"), json={"stage_id": "nope"}).status_code
            == 422
        )
        assert client.get(ourl(wid, f"/{opp['id']}")).json()["stage"]["key"] == "new"

    def test_a_stale_board_cannot_overwrite_a_newer_move(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        opp = make_opp(client, wid, make_lead(client, wid)["id"])
        keys = stages(client, wid)
        client.post(ourl(wid, f"/{opp['id']}/move"), json={"stage_id": keys["contacted"]})
        # A second browser still thinks the deal is in "new".
        stale = client.post(
            ourl(wid, f"/{opp['id']}/move"),
            json={"stage_id": keys["qualified"], "expected_stage_id": keys["new"]},
        )
        assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_stage"
        assert client.get(ourl(wid, f"/{opp['id']}")).json()["stage"]["key"] == "contacted"

    def test_winning_closes_the_deal(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        opp = make_opp(
            client, wid, make_lead(client, wid)["id"], value_amount="500.00", probability=70
        )
        keys = stages(client, wid)
        won = client.post(ourl(wid, f"/{opp['id']}/move"), json={"stage_id": keys["won"]}).json()
        assert won["status"] == "won" and won["closed_at"] and won["loss_reason"] is None
        assert won["weighted_value"] is None  # closed deals aren't pipeline

    def test_losing_records_the_reason_and_only_lost_stages_accept_one(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        opp = make_opp(client, wid, make_lead(client, wid)["id"])
        keys = stages(client, wid)
        bad = client.post(
            ourl(wid, f"/{opp['id']}/move"),
            json={"stage_id": keys["qualified"], "loss_reason": "x"},
        )
        assert bad.status_code == 422 and "loss_reason" in bad.json()["error"]["fields"]
        lost = client.post(
            ourl(wid, f"/{opp['id']}/move"),
            json={"stage_id": keys["lost"], "loss_reason": "  Went with someone cheaper "},
        ).json()
        assert (
            lost["status"] == "lost"
            and lost["loss_reason"] == "Went with someone cheaper"
            and lost["closed_at"]
        )

    def test_closed_deals_stay_put_until_reopened(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        opp = make_opp(client, wid, make_lead(client, wid)["id"])
        keys = stages(client, wid)
        client.post(ourl(wid, f"/{opp['id']}/move"), json={"stage_id": keys["won"]})
        res = client.post(ourl(wid, f"/{opp['id']}/move"), json={"stage_id": keys["qualified"]})
        assert res.status_code == 409 and res.json()["error"]["code"] == "opportunity_closed"
        # Moving from won to lost is also a decision that should be explicit.
        assert (
            client.post(
                ourl(wid, f"/{opp['id']}/move"), json={"stage_id": keys["lost"]}
            ).status_code
            == 409
        )

    def test_reopening(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        opp = make_opp(client, wid, make_lead(client, wid)["id"])
        keys = stages(client, wid)
        assert (
            client.post(
                ourl(wid, f"/{opp['id']}/reopen"), json={"stage_id": keys["new"]}
            ).status_code
            == 409
        )
        client.post(
            ourl(wid, f"/{opp['id']}/move"),
            json={"stage_id": keys["lost"], "loss_reason": "Budget"},
        )
        assert (
            client.post(
                ourl(wid, f"/{opp['id']}/reopen"), json={"stage_id": keys["won"]}
            ).status_code
            == 422
        )
        back = client.post(
            ourl(wid, f"/{opp['id']}/reopen"), json={"stage_id": keys["contacted"]}
        ).json()
        assert back["status"] == "open" and back["stage"]["key"] == "contacted"
        assert back["closed_at"] is None and back["loss_reason"] is None

    def test_moves_are_audited_by_stage_key_only(self, client: TestClient, db: DbSession) -> None:
        wid = make_user(client)["workspace_id"]
        opp = make_opp(
            client,
            wid,
            make_lead(client, wid, "Secret client")["id"],
            title="Secret deal",
            value_amount="999.00",
        )
        client.post(
            ourl(wid, f"/{opp['id']}/move"), json={"stage_id": stages(client, wid)["meeting"]}
        )
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.workspace_id == uuid.UUID(wid))
        ).all()
        moved = next(e for e in events if e.action == "pipeline.opportunity_moved")
        assert moved.details == {"to": "meeting"}
        assert "Secret" not in " ".join(str(e.details) for e in events) and "999" not in str(
            [e.details for e in events]
        )


class TestListing:
    @pytest.fixture
    def pipeline(self, client: TestClient) -> str:
        wid = make_user(client)["workspace_id"]
        keys = stages(client, wid)
        data = [
            ("Alpha deal", "Acme Co", "5000.00", "USD", 50, "2030-01-10", "qualified"),
            ("bravo deal", "Bolt Ltd", "300.00", "EUR", None, "2030-03-01", "new"),
            ("Charlie deal", None, None, "USD", 10, None, "proposal"),
        ]
        for title, company, value, currency, prob, close, stage in data:
            lead = make_lead(
                client, wid, f"{title} lead", **({"company_name": company} if company else {})
            )
            opp = make_opp(
                client, wid, lead["id"], title=title, stage_id=keys[stage], currency=currency,
                **({"value_amount": value} if value else {}),
                **({"probability": prob} if prob is not None else {}),
                **({"expected_close_date": close} if close else {}),
            )  # fmt: skip
            assert opp["stage"]["key"] == stage
        return wid

    def titles(self, client: TestClient, wid: str, **params: Any) -> list[str]:
        res = client.get(ourl(wid), params=params)
        assert res.status_code == 200, res.text
        return [o["title"] for o in res.json()["items"]]

    def test_filters(self, client: TestClient, pipeline: str) -> None:
        keys = stages(client, pipeline)
        assert self.titles(client, pipeline, stage_id=keys["proposal"]) == ["Charlie deal"]
        assert self.titles(client, pipeline, q="acme") == ["Alpha deal"]  # via the lead's company
        assert self.titles(client, pipeline, q="BRAVO") == ["bravo deal"]
        assert self.titles(client, pipeline, q="%") == []
        assert sorted(self.titles(client, pipeline, status="open")) == [
            "Alpha deal",
            "Charlie deal",
            "bravo deal",
        ]
        assert self.titles(client, pipeline, status="won") == []
        assert self.titles(client, pipeline, close_before="2030-02-01") == ["Alpha deal"]
        assert self.titles(client, pipeline, close_after="2030-02-01") == ["bravo deal"]
        assert client.get(ourl(pipeline), params={"status": "maybe"}).status_code == 422

    def test_sorting_is_case_insensitive_with_empty_values_last(
        self, client: TestClient, pipeline: str
    ) -> None:
        assert self.titles(client, pipeline, sort="title") == [
            "Alpha deal",
            "bravo deal",
            "Charlie deal",
        ]
        assert self.titles(client, pipeline, sort="-value_amount") == [
            "Alpha deal",
            "bravo deal",
            "Charlie deal",
        ]
        assert self.titles(client, pipeline, sort="expected_close_date")[-1] == "Charlie deal"
        assert client.get(ourl(pipeline), params={"sort": "lead_id"}).status_code == 422

    def test_pagination(self, client: TestClient, pipeline: str) -> None:
        page = client.get(ourl(pipeline), params={"limit": 2, "offset": 2, "sort": "title"}).json()
        assert page["total"] == 3 and [o["title"] for o in page["items"]] == ["Charlie deal"]

    def test_deals_report_their_open_tasks(self, client: TestClient, pipeline: str) -> None:
        opp = client.get(ourl(pipeline), params={"q": "alpha"}).json()["items"][0]
        for title in ("one", "two"):
            client.post(
                f"/api/v1/workspaces/{pipeline}/tasks",
                json={"title": title, "opportunity_id": opp["id"]},
            )
        done = client.post(
            f"/api/v1/workspaces/{pipeline}/tasks",
            json={"title": "three", "opportunity_id": opp["id"]},
        ).json()
        client.post(f"/api/v1/workspaces/{pipeline}/tasks/{done['id']}/complete")
        assert client.get(ourl(pipeline, f"/{opp['id']}")).json()["open_tasks"] == 2


class TestBoard:
    def board(self, client: TestClient, wid: str) -> dict[str, Any]:
        res = client.get(f"/api/v1/workspaces/{wid}/pipeline/board")
        assert res.status_code == 200, res.text
        return res.json()

    def test_every_stage_is_a_column_in_order_with_counts(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        keys = stages(client, wid)
        make_opp(client, wid, make_lead(client, wid)["id"], stage_id=keys["meeting"])
        board = self.board(client, wid)
        assert [c["stage"]["key"] for c in board["columns"]] == [
            "new", "contacted", "replied", "qualified", "meeting", "proposal", "won", "lost",
        ]  # fmt: skip
        by_key = {c["stage"]["key"]: c for c in board["columns"]}
        assert by_key["meeting"]["count"] == 1 and by_key["new"]["count"] == 0
        assert by_key["meeting"]["items"][0]["lead"]["title"] == "Website rebuild"

    def test_totals_never_mix_currencies_and_weight_only_what_has_a_probability(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        keys = stages(client, wid)
        for value, currency, prob in (
            ("1000.00", "USD", 50),
            ("500.00", "USD", None),
            ("200.00", "EUR", 25),
            (None, "USD", 90),
        ):
            make_opp(
                client, wid, make_lead(client, wid)["id"], stage_id=keys["qualified"], currency=currency,
                **({"value_amount": value} if value else {}), **({"probability": prob} if prob is not None else {}),
            )  # fmt: skip
        col = next(
            c for c in self.board(client, wid)["columns"] if c["stage"]["key"] == "qualified"
        )
        assert col["count"] == 4 and col["unvalued"] == 1
        totals = {t["currency"]: t for t in col["totals"]}
        assert set(totals) == {"USD", "EUR"}
        assert totals["USD"]["amount"] == "1500.00" and totals["USD"]["weighted"] == "500.00"
        assert totals["EUR"]["amount"] == "200.00" and totals["EUR"]["weighted"] == "50.00"

    def test_a_column_with_no_probabilities_has_no_weighted_figure(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        keys = stages(client, wid)
        make_opp(
            client,
            wid,
            make_lead(client, wid)["id"],
            stage_id=keys["contacted"],
            value_amount="400.00",
        )
        col = next(
            c for c in self.board(client, wid)["columns"] if c["stage"]["key"] == "contacted"
        )
        assert col["totals"] == [{"currency": "USD", "amount": "400.00", "weighted": None}]

    def test_closed_columns_have_no_weighted_value(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        keys = stages(client, wid)
        opp = make_opp(
            client, wid, make_lead(client, wid)["id"], value_amount="100.00", probability=80
        )
        client.post(ourl(wid, f"/{opp['id']}/move"), json={"stage_id": keys["won"]})
        won = next(c for c in self.board(client, wid)["columns"] if c["stage"]["key"] == "won")
        assert won["totals"][0]["amount"] == "100.00" and won["totals"][0]["weighted"] is None

    def test_a_column_lists_its_newest_deals_up_to_the_limit_but_counts_all(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wid = make_user(client)["workspace_id"]
        monkeypatch.setattr("app.services.opportunities.BOARD_COLUMN_LIMIT", 2)
        for i in range(3):
            make_opp(client, wid, make_lead(client, wid, f"L{i}")["id"], title=f"D{i}")
        board = self.board(client, wid)
        col = board["columns"][0]
        assert col["count"] == 3 and len(col["items"]) == 2 and board["per_column_limit"] == 2

    def test_the_board_is_workspace_scoped(self, client: TestClient, other: TestClient) -> None:
        a, b = make_user(client), make_user(other)
        make_opp(
            other,
            b["workspace_id"],
            make_lead(other, b["workspace_id"])["id"],
            value_amount="777.00",
        )
        board = self.board(client, a["workspace_id"])
        assert all(c["count"] == 0 and c["totals"] == [] for c in board["columns"])
        assert (
            other.get(f"/api/v1/workspaces/{a['workspace_id']}/pipeline/board").status_code == 404
        )


class TestTimeline:
    def test_notes_on_a_deal_also_appear_on_the_lead(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        lead = make_lead(client, wid)
        opp = make_opp(client, wid, lead["id"])
        res = client.post(
            ourl(wid, f"/{opp['id']}/activities"),
            json={"kind": "meeting", "summary": "Scope call", "body": "<b>x</b>"},
        )
        assert res.status_code == 201 and res.json()["body"] == "<b>x</b>"
        assert (
            client.get(ourl(wid, f"/{opp['id']}/activities")).json()["items"][0]["summary"]
            == "Scope call"
        )
        on_lead = client.get(f"/api/v1/workspaces/{wid}/leads/{lead['id']}/activities").json()[
            "items"
        ]
        assert "Scope call" in [a["summary"] for a in on_lead]

    @pytest.mark.parametrize(
        "body",
        [
            {"kind": "system", "summary": "forged"},
            {"kind": "stage_change", "summary": "forged"},
            {"kind": "note", "summary": ""},
        ],
    )
    def test_system_entries_cannot_be_forged(
        self, client: TestClient, body: dict[str, Any]
    ) -> None:
        wid = make_user(client)["workspace_id"]
        opp = make_opp(client, wid, make_lead(client, wid)["id"])
        assert client.post(ourl(wid, f"/{opp['id']}/activities"), json=body).status_code == 422

    def test_the_deal_timeline_only_shows_that_deal(
        self, client: TestClient, db: DbSession
    ) -> None:
        wid = make_user(client)["workspace_id"]
        lead = make_lead(client, wid)
        one, two = (
            make_opp(client, wid, lead["id"], title="One"),
            make_opp(client, wid, lead["id"], title="Two"),
        )
        client.post(ourl(wid, f"/{one['id']}/activities"), json={"summary": "only on one"})
        assert "only on one" not in [
            a["summary"] for a in client.get(ourl(wid, f"/{two['id']}/activities")).json()["items"]
        ]
        row = db.scalar(select(Activity).where(Activity.summary == "only on one"))
        assert (
            row is not None
            and row.lead_id == uuid.UUID(lead["id"])
            and row.opportunity_id == uuid.UUID(one["id"])
        )


class TestPermissionsAndIsolation:
    def test_other_workspaces_deals_are_invisible_and_untouchable(
        self, client: TestClient, other: TestClient
    ) -> None:
        a, b = make_user(client), make_user(other)
        theirs = make_opp(other, b["workspace_id"], make_lead(other, b["workspace_id"])["id"])
        wid = a["workspace_id"]
        url = ourl(wid, f"/{theirs['id']}")
        assert client.get(url).status_code == 404
        mine_stage = stages(client, wid)["qualified"]
        for method, suffix, body in (
            ("patch", "", {"title": "x"}),
            ("post", "/move", {"stage_id": mine_stage}),
            ("post", "/reopen", {"stage_id": mine_stage}),
            ("get", "/activities", None),
            ("post", "/activities", {"summary": "x"}),
        ):
            kwargs = {"json": body} if body is not None else {}
            assert getattr(client, method)(url + suffix, **kwargs).status_code == 404, suffix
        assert client.get(ourl(wid)).json()["total"] == 0
        assert other.get(ourl(wid)).status_code == 404

    def test_members_read_but_cannot_change(
        self, client: TestClient, other: TestClient, db: DbSession
    ) -> None:
        owner, member = make_user(client), make_user(other)
        wid = owner["workspace_id"]
        add_member(db, wid, member["me"]["user"]["id"])
        lead = make_lead(client, wid)
        opp = make_opp(client, wid, lead["id"])
        keys = stages(client, wid)
        assert other.get(ourl(wid)).status_code == 200
        assert other.get(f"/api/v1/workspaces/{wid}/pipeline/board").status_code == 200
        base = ourl(wid, f"/{opp['id']}")
        for method, url, body in (
            ("post", ourl(wid), {"lead_id": lead["id"]}),
            ("patch", base, {"title": "x"}),
            ("post", f"{base}/move", {"stage_id": keys["qualified"]}),
            ("post", f"{base}/reopen", {"stage_id": keys["qualified"]}),
            ("post", f"{base}/activities", {"summary": "x"}),
        ):
            assert getattr(other, method)(url, json=body).status_code == 403, (method, url)
        assert client.get(base).json()["stage"]["key"] == "new"

    def test_unauthenticated_requests_are_refused(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        client.cookies.clear()
        assert client.get(ourl(wid)).status_code == 401
        assert client.get(f"/api/v1/workspaces/{wid}/pipeline/board").status_code == 401
        assert client.post(ourl(wid), json={"lead_id": str(uuid.uuid4())}).status_code == 401


def test_the_database_refuses_a_deal_in_another_workspaces_stage(
    client: TestClient, other: TestClient, db: DbSession
) -> None:
    from sqlalchemy.exc import IntegrityError

    a, b = make_user(client), make_user(other)
    lead = make_lead(client, a["workspace_id"])
    foreign_stage = stages(other, b["workspace_id"])["new"]
    db.add(
        Opportunity(
            workspace_id=uuid.UUID(a["workspace_id"]),
            lead_id=uuid.UUID(lead["id"]),
            stage_id=uuid.UUID(foreign_stage),
            title="cross-tenant",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
