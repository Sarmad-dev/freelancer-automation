"""Pagination, sorting, filtering, scoping and error conventions, proven on the tags/stages endpoints."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db.models import AuditEvent
from app.db.models_crm import Lead, LeadTag, Tag
from tests.conftest import make_user


def tags_url(wid: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{wid}/tags{suffix}"


def create(client: TestClient, wid: str, name: str, **extra: str) -> dict:  # type: ignore[type-arg]
    res = client.post(tags_url(wid), json={"name": name, **extra})
    assert res.status_code == 201, res.text
    return res.json()


@pytest.fixture
def other(client: TestClient) -> TestClient:
    return TestClient(client.app, headers=dict(client.headers), base_url="http://localhost:3000")


class TestPagination:
    @pytest.fixture
    def ws(self, client: TestClient) -> str:
        wid = make_user(client)["workspace_id"]
        for i in range(30):
            create(client, wid, f"tag-{i:02d}")
        return wid

    def test_response_shape_and_defaults(self, client: TestClient, ws: str) -> None:
        body = client.get(tags_url(ws)).json()
        assert set(body) == {"items", "total", "limit", "offset"}
        assert (body["total"], body["limit"], body["offset"]) == (30, 25, 0)
        assert len(body["items"]) == 25
        assert set(body["items"][0]) == {"id", "name", "color", "created_at", "updated_at"}

    def test_pages_are_disjoint_complete_and_stable(self, client: TestClient, ws: str) -> None:
        seen: list[str] = []
        for offset in (0, 10, 20, 30):
            page = client.get(tags_url(ws), params={"limit": 10, "offset": offset}).json()
            assert page["total"] == 30
            seen += [t["name"] for t in page["items"]]
        assert seen == [f"tag-{i:02d}" for i in range(30)]  # default sort=name, no gaps or repeats
        assert client.get(tags_url(ws), params={"offset": 1000}).json()["items"] == []

    @pytest.mark.parametrize(
        "params", [{"limit": 0}, {"limit": 101}, {"limit": "x"}, {"offset": -1}, {"offset": 10**9}]
    )
    def test_out_of_range_paging_is_a_validation_error(
        self, client: TestClient, ws: str, params: dict[str, object]
    ) -> None:
        res = client.get(tags_url(ws), params=params)
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "validation_error"
        assert list(params)[0] in res.json()["error"]["fields"]

    def test_sorting_ascending_descending_and_multi_field(
        self, client: TestClient, ws: str
    ) -> None:
        asc = [
            t["name"]
            for t in client.get(tags_url(ws), params={"sort": "name", "limit": 5}).json()["items"]
        ]
        desc = [
            t["name"]
            for t in client.get(tags_url(ws), params={"sort": "-name", "limit": 5}).json()["items"]
        ]
        assert asc == [f"tag-{i:02d}" for i in range(5)]
        assert desc == [f"tag-{i:02d}" for i in (29, 28, 27, 26, 25)]
        newest = client.get(tags_url(ws), params={"sort": "-created_at,name", "limit": 1}).json()[
            "items"
        ][0]
        assert newest["name"] == "tag-29"

    @pytest.mark.parametrize(
        "sort",
        [
            "password",
            "name;DROP TABLE tags",
            "-nope",
            "name,created_at,name,name",
            ",",
            "workspace_id",
        ],
    )
    def test_sorting_is_allow_listed(self, client: TestClient, ws: str, sort: str) -> None:
        res = client.get(tags_url(ws), params={"sort": sort})
        assert res.status_code == 422
        assert "sort" in res.json()["error"]["fields"]

    def test_filter_is_case_insensitive_and_literal(self, client: TestClient, ws: str) -> None:
        create(client, ws, "50% Off_Deal")
        create(client, ws, "500 of deal")
        assert [t["name"] for t in client.get(tags_url(ws), params={"q": "TAG-1"}).json()["items"]][
            :2
        ] == ["tag-10", "tag-11"]
        body = client.get(tags_url(ws), params={"q": "% off_"}).json()
        assert [t["name"] for t in body["items"]] == ["50% Off_Deal"]  # % and _ are not wildcards
        assert client.get(tags_url(ws), params={"q": "nothing-matches"}).json()["total"] == 0
        assert client.get(tags_url(ws), params={"q": "x" * 51}).status_code == 422


class TestCrudAndErrors:
    def test_create_get_patch_delete_flow(self, client: TestClient, db: DbSession) -> None:
        u = make_user(client)
        wid = u["workspace_id"]
        tag = create(client, wid, "  Warm   intro ", color="#a8e66b")
        assert tag["name"] == "Warm intro" and tag["color"] == "#A8E66B"
        assert client.get(tags_url(wid, f"/{tag['id']}")).json()["id"] == tag["id"]

        patched = client.patch(tags_url(wid, f"/{tag['id']}"), json={"color": None}).json()
        assert (
            patched["color"] is None and patched["name"] == "Warm intro"
        )  # PATCH leaves omitted fields alone
        renamed = client.patch(tags_url(wid, f"/{tag['id']}"), json={"name": "Hot lead"}).json()
        assert renamed["name"] == "Hot lead"

        assert client.delete(tags_url(wid, f"/{tag['id']}")).status_code == 204
        gone = client.get(tags_url(wid, f"/{tag['id']}"))
        assert gone.status_code == 404 and gone.json()["error"]["code"] == "tag_not_found"
        assert client.delete(tags_url(wid, f"/{tag['id']}")).status_code == 404
        actions = [
            e.action
            for e in db.scalars(
                select(AuditEvent)
                .where(AuditEvent.workspace_id == uuid.UUID(wid))
                .order_by(AuditEvent.created_at)
            )
        ]
        assert [a for a in actions if a.startswith("crm.")] == [
            "crm.tag_created",
            "crm.tag_updated",
            "crm.tag_updated",
            "crm.tag_deleted",
        ]

    def test_duplicates_are_case_and_space_insensitive_and_use_the_error_envelope(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        first = create(client, wid, "Priority")
        for variant in ("priority", "  PRIORITY  ", "Priority"):
            res = client.post(tags_url(wid), json={"name": variant})
            assert res.status_code == 409
            assert res.json() == {
                "error": {
                    "code": "tag_exists",
                    "message": "A tag with this name already exists.",
                    "fields": {"name": "Already exists."},
                }
            }
        other_tag = create(client, wid, "Other")
        clash = client.patch(tags_url(wid, f"/{other_tag['id']}"), json={"name": "priority"})
        assert clash.status_code == 409
        same = client.patch(
            tags_url(wid, f"/{first['id']}"), json={"name": "PRIORITY"}
        )  # renaming to itself/case is fine
        assert same.status_code == 200

    @pytest.mark.parametrize(
        ("body", "field"),
        [
            ({"name": ""}, "name"),
            ({"name": "x" * 51}, "name"),
            ({"name": "a\x00b"}, "name"),
            ({"name": "ok", "color": "red"}, "color"),
            ({"name": "ok", "color": "#12345"}, "color"),
            ({"name": "ok", "extra": 1}, "extra"),
            ({}, "name"),
        ],
    )
    def test_invalid_bodies(self, client: TestClient, body: dict[str, object], field: str) -> None:
        wid = make_user(client)["workspace_id"]
        res = client.post(tags_url(wid), json=body)
        assert res.status_code == 422 and field in res.json()["error"]["fields"]

    def test_bad_ids_are_validation_errors_and_unknown_ones_are_404(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        assert client.get(tags_url(wid, "/not-a-uuid")).status_code == 422
        assert client.get(tags_url(wid, f"/{uuid.uuid4()}")).status_code == 404

    def test_every_endpoint_requires_authentication(self, client: TestClient) -> None:
        wid, tid = str(uuid.uuid4()), str(uuid.uuid4())
        calls = [
            client.get(tags_url(wid)),
            client.post(tags_url(wid), json={"name": "x"}),
            client.get(tags_url(wid, f"/{tid}")),
            client.patch(tags_url(wid, f"/{tid}"), json={}),
            client.delete(tags_url(wid, f"/{tid}")),
            client.get(f"/api/v1/workspaces/{wid}/pipeline/stages"),
        ]
        assert [c.status_code for c in calls] == [401] * 6

    def test_mutations_are_csrf_protected(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        res = client.post(
            tags_url(wid), json={"name": "x"}, headers={"Origin": "https://evil.example"}
        )
        assert res.status_code == 403

    def test_deleting_a_tag_unlinks_leads_but_keeps_them(
        self, client: TestClient, db: DbSession
    ) -> None:
        wid = make_user(client)["workspace_id"]
        tag = create(client, wid, "Linked")
        lead = Lead(workspace_id=uuid.UUID(wid), title="keep me")
        db.add(lead)
        db.flush()
        db.add(LeadTag(workspace_id=uuid.UUID(wid), lead_id=lead.id, tag_id=uuid.UUID(tag["id"])))
        db.commit()
        assert client.delete(tags_url(wid, f"/{tag['id']}")).status_code == 204
        db.expire_all()
        assert db.get(Lead, lead.id) is not None
        assert db.scalars(select(LeadTag).where(LeadTag.lead_id == lead.id)).all() == []


class TestWorkspaceIsolation:
    def test_another_user_cannot_list_read_change_or_delete_my_tags(
        self, client: TestClient, other: TestClient, db: DbSession
    ) -> None:
        mine = make_user(client)["workspace_id"]
        theirs = make_user(other)["workspace_id"]
        tag = create(client, mine, "Secret strategy")
        create(other, theirs, "Their own")

        attempts = [
            other.get(tags_url(mine)),
            other.get(tags_url(mine, f"/{tag['id']}")),
            other.post(tags_url(mine), json={"name": "injected"}),
            other.patch(tags_url(mine, f"/{tag['id']}"), json={"name": "hijack"}),
            other.delete(tags_url(mine, f"/{tag['id']}")),
        ]
        assert [a.status_code for a in attempts] == [404] * 5
        assert {a.json()["error"]["code"] for a in attempts} == {"workspace_not_found"}

        # Using MY workspace id with THEIR tag id (mixing tenants in one request) also fails.
        their_tag = other.get(tags_url(theirs)).json()["items"][0]
        mixed = client.get(tags_url(mine, f"/{their_tag['id']}"))
        assert mixed.status_code == 404 and mixed.json()["error"]["code"] == "tag_not_found"
        assert (
            client.patch(tags_url(mine, f"/{their_tag['id']}"), json={"name": "x"}).status_code
            == 404
        )
        assert client.delete(tags_url(mine, f"/{their_tag['id']}")).status_code == 404

        assert [t["name"] for t in client.get(tags_url(mine)).json()["items"]] == [
            "Secret strategy"
        ]
        assert [t["name"] for t in other.get(tags_url(theirs)).json()["items"]] == ["Their own"]
        names = {t.name for t in db.scalars(select(Tag))}
        assert (
            {"Secret strategy", "Their own"} <= names
            and "injected" not in names
            and "hijack" not in names
        )

    def test_same_tag_name_may_exist_in_two_workspaces(
        self, client: TestClient, other: TestClient
    ) -> None:
        create(client, make_user(client)["workspace_id"], "Shared")
        create(other, make_user(other)["workspace_id"], "Shared")

    def test_totals_never_count_other_tenants(self, client: TestClient, other: TestClient) -> None:
        a, b = make_user(client)["workspace_id"], make_user(other)["workspace_id"]
        for i in range(3):
            create(client, a, f"a{i}")
        for i in range(7):
            create(other, b, f"b{i}")
        assert client.get(tags_url(a)).json()["total"] == 3
        assert other.get(tags_url(b)).json()["total"] == 7


class TestPipelineStages:
    def test_new_workspaces_get_the_default_stages_in_order(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        body = client.get(f"/api/v1/workspaces/{wid}/pipeline/stages").json()
        assert [s["key"] for s in body["items"]] == [
            "new",
            "contacted",
            "replied",
            "qualified",
            "meeting",
            "proposal",
            "won",
            "lost",
        ]
        assert [s["position"] for s in body["items"]] == list(range(8))
        flags = {s["key"]: (s["is_won"], s["is_lost"]) for s in body["items"]}
        assert (
            flags["won"] == (True, False)
            and flags["lost"] == (False, True)
            and flags["new"] == (False, False)
        )
        assert body["total"] == 8

    def test_stages_are_per_workspace_and_isolated(
        self, client: TestClient, other: TestClient
    ) -> None:
        a, b = make_user(client)["workspace_id"], make_user(other)["workspace_id"]
        ids_a = {
            s["id"] for s in client.get(f"/api/v1/workspaces/{a}/pipeline/stages").json()["items"]
        }
        ids_b = {
            s["id"] for s in other.get(f"/api/v1/workspaces/{b}/pipeline/stages").json()["items"]
        }
        assert ids_a.isdisjoint(ids_b)
        assert other.get(f"/api/v1/workspaces/{a}/pipeline/stages").status_code == 404

    def test_reverse_sort_and_pagination_work_here_too(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        body = client.get(
            f"/api/v1/workspaces/{wid}/pipeline/stages", params={"sort": "-position", "limit": 2}
        ).json()
        assert [s["key"] for s in body["items"]] == ["lost", "won"] and body["total"] == 8


def test_openapi_documents_the_conventions(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    op = spec["paths"]["/api/v1/workspaces/{workspace_id}/tags"]["get"]
    params = {p["name"]: p for p in op["parameters"]}
    assert {"limit", "offset", "sort", "q", "workspace_id"} <= set(params)
    assert params["limit"]["schema"]["maximum"] == 100 and params["limit"]["schema"]["minimum"] == 1
    assert "Page_TagOut_" in spec["components"]["schemas"]
    assert {"401", "404", "422"} <= set(op["responses"])
    assert spec["components"]["schemas"]["ErrorResponse"]["properties"]["error"]
