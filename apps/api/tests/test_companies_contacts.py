from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db.models import AuditEvent
from app.db.models_email import SuppressionEntry
from tests.conftest import add_member, make_user, second_client


def curl(wid: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{wid}/companies{suffix}"


def kurl(wid: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{wid}/contacts{suffix}"


def company(client: TestClient, wid: str, name: str = "Acme Studio", **extra: object) -> dict:  # type: ignore[type-arg]
    res = client.post(curl(wid), json={"name": name, **extra})
    assert res.status_code == 201, res.text
    return res.json()


def contact(client: TestClient, wid: str, name: str = "Ada Byron", **extra: object) -> dict:  # type: ignore[type-arg]
    res = client.post(kurl(wid), json={"full_name": name, **extra})
    assert res.status_code == 201, res.text
    return res.json()


@pytest.fixture
def other(client: TestClient) -> TestClient:
    return second_client(client)


class TestCompanies:
    def test_manual_company_records_provenance_and_derives_the_domain(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        c = company(client, wid, website="WWW.Acme-Studio.example/about", industry="Design")
        assert c["website"] == "https://www.acme-studio.example/about"
        assert c["domain"] == "acme-studio.example"
        assert c["source"] == "manual" and c["source_retrieved_at"] is None
        assert c["is_sample"] is False and c["lead_count"] == 0 and c["contact_count"] == 0

    @pytest.mark.parametrize(
        "website",
        [
            "javascript:alert(1)",
            "ftp://acme.example",
            "http://localhost",
            "http://192.168.1.1",
            "https://user:pw@acme.example",
            "not a url",
            "http://intranet",
        ],
    )
    def test_unsafe_or_private_websites_are_rejected(
        self, client: TestClient, website: str
    ) -> None:
        wid = make_user(client)["workspace_id"]
        res = client.post(curl(wid), json={"name": "X", "website": website})
        assert res.status_code == 422 and "website" in res.json()["error"]["fields"], website

    def test_the_same_website_cannot_be_added_twice(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        company(client, wid, website="https://acme.example")
        for variant in ("acme.example", "https://www.ACME.example/", "http://acme.example/x"):
            res = client.post(curl(wid), json={"name": "Again", "website": variant})
            assert res.status_code == 409 and res.json()["error"]["code"] == "company_exists"

    def test_two_companies_without_a_website_may_share_a_name(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        company(client, wid, "Same Name")
        company(client, wid, "Same Name")

    def test_invalid_size_labels_and_extra_fields_are_rejected(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        for body in (
            {"name": "X", "size_label": "huge"},
            {"name": "X", "is_sample": True},
            {"name": "X", "workspace_id": str(uuid.uuid4())},
            {"name": ""},
            {"name": "x" * 201},
            {"name": "a\x00b"},
        ):
            assert client.post(curl(wid), json=body).status_code == 422, body

    def test_patch_semantics_and_clearing(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        c = company(client, wid, website="https://acme.example", industry="Design", location="Oslo")
        res = client.patch(curl(wid, f"/{c['id']}"), json={"industry": None, "location": ""})
        got = res.json()
        assert res.status_code == 200
        assert got["industry"] is None and got["location"] is None
        assert got["name"] == "Acme Studio" and got["website"] == "https://acme.example"
        assert (
            client.patch(curl(wid, f"/{c['id']}"), json={"name": None}).json()["name"]
            == "Acme Studio"
        )
        cleared = client.patch(curl(wid, f"/{c['id']}"), json={"website": None}).json()
        assert cleared["website"] is None and cleared["domain"] is None

    def test_changing_the_website_to_one_in_use_is_a_conflict(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        company(client, wid, "A", website="https://a.example")
        b = company(client, wid, "B", website="https://b.example")
        res = client.patch(curl(wid, f"/{b['id']}"), json={"website": "a.example"})
        assert res.status_code == 409

    def test_archive_hides_it_from_the_default_list_and_blocks_edits_until_restored(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        c = company(client, wid)
        assert client.post(curl(wid, f"/{c['id']}/archive")).json()["archived_at"]
        assert client.get(curl(wid)).json()["total"] == 0
        assert client.get(curl(wid), params={"archived": "archived"}).json()["total"] == 1
        assert client.get(curl(wid), params={"archived": "all"}).json()["total"] == 1
        blocked = client.patch(curl(wid, f"/{c['id']}"), json={"industry": "x"})
        assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "company_archived"
        # Archiving twice is harmless; restoring brings it back.
        assert client.post(curl(wid, f"/{c['id']}/archive")).status_code == 200
        assert client.post(curl(wid, f"/{c['id']}/restore")).json()["archived_at"] is None
        assert client.get(curl(wid)).json()["total"] == 1

    def test_search_filter_sort_and_pagination(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        for name, industry, size in (
            ("Bravo", "SaaS", "11-50"),
            ("alpha", "Design", "1"),
            ("Charlie", "SaaS", "2-10"),
        ):
            company(client, wid, name, industry=industry, size_label=size)
        names = lambda **p: [c["name"] for c in client.get(curl(wid), params=p).json()["items"]]  # noqa: E731
        assert names(sort="name") == ["alpha", "Bravo", "Charlie"]  # case-insensitive
        assert names(sort="-name") == ["Charlie", "Bravo", "alpha"]
        assert sorted(names(industry="saa")) == ["Bravo", "Charlie"]
        assert names(size_label="1") == ["alpha"]
        assert names(q="CHAR") == ["Charlie"]
        assert names(q="%") == []  # wildcards are literal
        page = client.get(curl(wid), params={"limit": 2, "offset": 2, "sort": "-created_at"}).json()
        assert page["total"] == 3 and len(page["items"]) == 1
        bad = client.get(curl(wid), params={"sort": "password"})
        assert bad.status_code == 422

    def test_counts_only_include_active_records(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        c = company(client, wid)
        a = contact(client, wid, "A", company_id=c["id"], email="a@acme.example")
        contact(client, wid, "B", company_id=c["id"], email="b@acme.example")
        assert client.get(curl(wid, f"/{c['id']}")).json()["contact_count"] == 2
        client.post(kurl(wid, f"/{a['id']}/archive"))
        assert client.get(curl(wid, f"/{c['id']}")).json()["contact_count"] == 1


class TestContacts:
    def test_email_is_normalised_and_unique_per_workspace(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        c = contact(client, wid, email="  Ada@Example.COM ")
        assert c["email"] == "ada@example.com" and c["source"] == "manual"
        dup = client.post(kurl(wid), json={"full_name": "Other", "email": "ADA@example.com"})
        assert dup.status_code == 409 and dup.json()["error"]["code"] == "contact_exists"

    @pytest.mark.parametrize(
        "email", ["nope", "a@b", "a b@example.com", "x@localhost", "@example.com"]
    )
    def test_invalid_emails_are_rejected(self, client: TestClient, email: str) -> None:
        wid = make_user(client)["workspace_id"]
        res = client.post(kurl(wid), json={"full_name": "X", "email": email})
        assert res.status_code == 422 and "email" in res.json()["error"]["fields"], email

    @pytest.mark.parametrize("phone", ["call me", "<script>", "1" * 40, "12"])
    def test_invalid_phone_numbers_are_rejected(self, client: TestClient, phone: str) -> None:
        wid = make_user(client)["workspace_id"]
        res = client.post(kurl(wid), json={"full_name": "X", "phone": phone})
        assert res.status_code == 422 and "phone" in res.json()["error"]["fields"], phone

    @pytest.mark.parametrize(
        "phone", ["+1 (555) 010-0100", "020 7946 0000", "+44 20 7946 0000 x12"]
    )
    def test_ordinary_phone_numbers_are_accepted(self, client: TestClient, phone: str) -> None:
        wid = make_user(client)["workspace_id"]
        assert contact(client, wid, phone=phone)["phone"] == phone

    def test_contacts_can_be_created_without_an_email(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        contact(client, wid, "No Email")
        contact(client, wid, "Also No Email")  # NULL emails never collide

    def test_a_contact_cannot_point_at_another_workspaces_company(
        self, client: TestClient, other: TestClient
    ) -> None:
        a, b = make_user(client), make_user(other)
        foreign = company(other, b["workspace_id"], "Theirs")
        res = client.post(
            kurl(a["workspace_id"]), json={"full_name": "X", "company_id": foreign["id"]}
        )
        assert res.status_code == 422 and "company_id" in res.json()["error"]["fields"]

    def test_company_name_is_resolved_for_display_and_search(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        c = company(client, wid, "Acme Studio")
        made = contact(
            client, wid, "Ada", company_id=c["id"], role_title="CTO", email="ada@acme.example"
        )
        assert made["company_name"] == "Acme Studio"
        found = client.get(kurl(wid), params={"q": "cto"}).json()
        assert [x["id"] for x in found["items"]] == [made["id"]]
        assert client.get(kurl(wid), params={"company_id": c["id"]}).json()["total"] == 1

    def test_do_not_contact_is_derived_from_the_suppression_list(
        self, client: TestClient, db: DbSession
    ) -> None:
        wid = make_user(client)["workspace_id"]
        blocked = contact(client, wid, "Blocked", email="stop@example.com")
        fine = contact(client, wid, "Fine", email="ok@example.com")
        assert blocked["do_not_contact"] is False
        db.add(
            SuppressionEntry(
                workspace_id=uuid.UUID(wid),
                email_normalized="stop@example.com",
                reason="unsubscribe",
            )
        )
        db.commit()
        assert client.get(kurl(wid, f"/{blocked['id']}")).json()["do_not_contact"] is True
        assert client.get(kurl(wid, f"/{fine['id']}")).json()["do_not_contact"] is False

    def test_patch_and_archive(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        c = contact(client, wid, email="ada@example.com", phone="+1 555 0100")
        got = client.patch(
            kurl(wid, f"/{c['id']}"), json={"phone": None, "role_title": "CEO"}
        ).json()
        assert (
            got["phone"] is None
            and got["role_title"] == "CEO"
            and got["email"] == "ada@example.com"
        )
        client.post(kurl(wid, f"/{c['id']}/archive"))
        assert client.get(kurl(wid)).json()["total"] == 0
        assert client.patch(kurl(wid, f"/{c['id']}"), json={"role_title": "x"}).status_code == 409
        assert client.post(kurl(wid, f"/{c['id']}/restore")).json()["archived_at"] is None


class TestIsolationAndPermissions:
    def test_other_workspaces_records_are_invisible_and_untouchable(
        self, client: TestClient, other: TestClient
    ) -> None:
        a, b = make_user(client), make_user(other)
        theirs_c = company(other, b["workspace_id"], "Theirs", website="https://theirs.example")
        theirs_p = contact(other, b["workspace_id"], "Them", email="them@example.com")
        wid = a["workspace_id"]
        for url in (curl(wid, f"/{theirs_c['id']}"), kurl(wid, f"/{theirs_p['id']}")):
            assert client.get(url).status_code == 404
            assert client.patch(url, json={"notes": "x"}).status_code == 404
            assert client.post(f"{url}/archive").status_code == 404
        assert client.get(curl(wid)).json()["total"] == 0
        # ...and the same website/email is free to use in my own workspace.
        company(client, wid, "Mine", website="https://theirs.example")
        contact(client, wid, "Me", email="them@example.com")
        # A member of another workspace cannot reach mine at all.
        assert other.get(curl(wid)).status_code == 404
        assert other.post(kurl(wid), json={"full_name": "x"}).status_code == 404

    def test_members_can_read_but_not_write(
        self, client: TestClient, other: TestClient, db: DbSession
    ) -> None:
        owner, member = make_user(client), make_user(other)
        wid = owner["workspace_id"]
        add_member(db, wid, member["me"]["user"]["id"])
        c = company(client, wid)
        p = contact(client, wid, email="a@example.com")
        assert other.get(curl(wid)).status_code == 200 and other.get(kurl(wid)).status_code == 200
        assert other.get(curl(wid, f"/{c['id']}")).status_code == 200
        writes = [
            ("post", curl(wid), {"name": "x"}),
            ("patch", curl(wid, f"/{c['id']}"), {"notes": "x"}),
            ("post", curl(wid, f"/{c['id']}/archive"), None),
            ("post", kurl(wid), {"full_name": "x"}),
            ("patch", kurl(wid, f"/{p['id']}"), {"notes": "x"}),
            ("post", kurl(wid, f"/{p['id']}/archive"), None),
        ]
        for method, url, body in writes:
            res = getattr(other, method)(url, **({"json": body} if body is not None else {}))
            assert res.status_code == 403, (method, url)

    def test_unauthenticated_requests_are_refused(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        client.cookies.clear()
        assert client.get(curl(wid)).status_code == 401
        assert client.post(kurl(wid), json={"full_name": "x"}).status_code == 401

    def test_changes_are_audited_without_personal_data(
        self, client: TestClient, db: DbSession
    ) -> None:
        wid = make_user(client)["workspace_id"]
        c = company(client, wid, "Secret Co", website="https://secret.example")
        client.patch(curl(wid, f"/{c['id']}"), json={"notes": "private note"})
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.workspace_id == uuid.UUID(wid))
        ).all()
        actions = {e.action for e in events}
        assert {"crm.company_created", "crm.company_updated"} <= actions
        blob = " ".join(str(e.details) for e in events)
        assert "private note" not in blob and "secret.example" not in blob
