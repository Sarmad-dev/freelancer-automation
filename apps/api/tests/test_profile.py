from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db.models import AuditEvent, FreelancerProfile
from tests.conftest import add_member, make_user, second_client


def profile_url(wid: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{wid}/profile{suffix}"


FULL = {
    "role_title": "Independent web developer",
    "summary": "I build fast, accessible websites.",
    "services": ["Web development", "Performance audits"],
    "skills": ["TypeScript", "React"],
    "industries": ["SaaS"],
    "differentiators": ["Fixed-scope audits"],
    "excluded_customers": ["Gambling operators"],
    "target_clients": "Seed-stage SaaS founders.",
    "portfolio_urls": ["https://example.com/work"],
    "years_experience": 8,
    "experience_summary": "Shipped 40 projects.",
    "pricing_guidance": "Quote after a discovery call; never in a first email.",
    "preferred_cta": "Book a 20-minute call",
    "tone": "friendly",
    "tone_notes": "Plain language.",
}


@pytest.fixture
def other(client: TestClient) -> TestClient:
    return second_client(client)


class TestReadAndUpdate:
    def test_new_profile_is_empty_versioned_and_reports_what_is_missing(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        body = client.get(profile_url(wid)).json()
        assert body["version"] == 1 and body["services"] == [] and body["pricing_guidance"] is None
        assert body["completeness"]["filled"] == 0 and body["completeness"]["total"] == 10
        needed = {
            m["field"] for m in body["completeness"]["missing"] if m["importance"] == "needed"
        }
        assert needed == {"role_title", "services", "target_clients", "tone"}
        assert body["timezone"] == "UTC"

    def test_patch_saves_fields_bumps_version_and_updates_completeness(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        res = client.patch(profile_url(wid), json=FULL)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["version"] == 2
        assert body["services"] == FULL["services"] and body["tone"] == "friendly"
        assert body["completeness"]["filled"] == 10 and body["completeness"]["missing"] == []
        assert client.get(profile_url(wid)).json()["version"] == 2  # persisted

    def test_a_patch_that_changes_nothing_does_not_create_a_version(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        client.patch(profile_url(wid), json={"role_title": "Dev"})
        again = client.patch(profile_url(wid), json={"role_title": "  Dev  ", "services": []})
        assert again.json()["version"] == 2

    def test_omitted_fields_are_untouched_and_null_or_empty_clears(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        client.patch(profile_url(wid), json=FULL)
        after = client.patch(
            profile_url(wid),
            json={"pricing_guidance": "", "years_experience": None, "services": None},
        ).json()
        assert (
            after["pricing_guidance"] is None
            and after["years_experience"] is None
            and after["services"] == []
        )
        assert after["skills"] == FULL["skills"] and after["role_title"] == FULL["role_title"]

    def test_lists_are_cleaned_and_deduplicated(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        res = client.patch(
            profile_url(wid),
            json={
                "skills": [" React ", "react", "", "Vue  3"],
                "portfolio_urls": ["HTTPS://Example.COM/a", "https://example.com/a", " "],
            },
        )
        assert res.json()["skills"] == ["React", "Vue 3"]
        assert res.json()["portfolio_urls"] == ["https://example.com/a"]

    def test_invisible_and_direction_override_characters_are_stripped(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        rlo, zwsp, bom = (
            chr(0x202E),
            chr(0x200B),
            chr(0xFEFF),
        )  # built with chr() so the source stays visible
        res = client.patch(
            profile_url(wid),
            json={"role_title": f"Dev{rlo}eloper{zwsp}", "summary": f"Hello{bom} world"},
        )
        assert res.status_code == 200
        assert res.json()["role_title"] == "Developer"
        assert res.json()["summary"] == "Hello world"
        assert rlo not in res.text and zwsp not in res.text and bom not in res.text


class TestValidation:
    @pytest.mark.parametrize(
        ("body", "field"),
        [
            ({"role_title": "x" * 121}, "role_title"),
            ({"role_title": "a\x00b"}, "role_title"),
            ({"summary": "x" * 501}, "summary"),
            ({"tone": "sarcastic"}, "tone"),
            ({"business_goal": "world domination"}, "business_goal"),
            ({"years_experience": -1}, "years_experience"),
            ({"years_experience": 61}, "years_experience"),
            ({"services": ["x" * 81]}, "services"),
            ({"services": [f"s{i}" for i in range(16)]}, "services"),
            ({"skills": [f"k{i}" for i in range(31)]}, "skills"),
            ({"differentiators": [f"d{i}" for i in range(11)]}, "differentiators"),
            ({"excluded_customers": ["x" * 101]}, "excluded_customers"),
            ({"pricing_guidance": "x" * 1001}, "pricing_guidance"),
            ({"preferred_cta": "x" * 201}, "preferred_cta"),
            ({"expected_version": 0}, "expected_version"),
            ({"unknown_field": 1}, "unknown_field"),
            ({"workspace_id": str(uuid.uuid4())}, "workspace_id"),
            ({"version": 99}, "version"),
        ],
    )
    def test_invalid_input_is_rejected_with_a_field_error(
        self, client: TestClient, body: dict[str, object], field: str
    ) -> None:
        wid = make_user(client)["workspace_id"]
        res = client.patch(profile_url(wid), json=body)
        assert res.status_code == 422, res.text
        assert field in res.json()["error"]["fields"]
        assert client.get(profile_url(wid)).json()["version"] == 1  # nothing saved

    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "data:text/html,<script>1</script>",
            "file:///etc/passwd",
            "ftp://example.com/x",
            "https://user:pass@example.com/",
            "http://localhost/admin",
            "http://127.0.0.1/",
            "http://169.254.169.254/latest/meta-data/",
            "http://[::1]/",
            "https://printer.local/",
            "https://exa mple.com",
            "example.com/no-scheme",
            "//example.com",
        ],
    )
    def test_portfolio_urls_reject_unsafe_addresses(self, client: TestClient, url: str) -> None:
        wid = make_user(client)["workspace_id"]
        res = client.patch(
            profile_url(wid), json={"portfolio_urls": ["https://ok.example.com", url]}
        )
        assert res.status_code == 422 and "portfolio_urls" in res.json()["error"]["fields"], url

    def test_too_many_links(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        urls = [f"https://site{i}.example.com" for i in range(11)]
        assert client.patch(profile_url(wid), json={"portfolio_urls": urls}).status_code == 422

    def test_markup_is_stored_as_inert_text(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        payload = "<img src=x onerror=alert(1)> {{7*7}} '; DROP TABLE users;--"
        res = client.patch(profile_url(wid), json={"summary": payload[:500]})
        assert res.status_code == 200 and res.json()["summary"] == payload[:500]


class TestConcurrency:
    def test_stale_expected_version_is_a_conflict_and_changes_nothing(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        client.patch(profile_url(wid), json={"role_title": "First"})  # now v2
        stale = client.patch(profile_url(wid), json={"role_title": "Second", "expected_version": 1})
        assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_version"
        assert client.get(profile_url(wid)).json()["role_title"] == "First"
        ok = client.patch(profile_url(wid), json={"role_title": "Third", "expected_version": 2})
        assert ok.status_code == 200 and ok.json()["version"] == 3

    def test_two_editors_from_the_same_version_cannot_both_win(
        self, client: TestClient, other: TestClient, db: DbSession
    ) -> None:
        # Same user in two tabs.
        u = make_user(client)
        other.post("/api/v1/auth/sign-in", json={"email": u["email"], "password": u["password"]})
        wid = u["workspace_id"]
        assert (
            client.patch(
                profile_url(wid), json={"tone": "direct", "expected_version": 1}
            ).status_code
            == 200
        )
        losing = other.patch(profile_url(wid), json={"tone": "formal", "expected_version": 1})
        assert losing.status_code == 409
        db.expire_all()
        assert (
            db.scalar(
                select(FreelancerProfile.tone).where(
                    FreelancerProfile.workspace_id == uuid.UUID(wid)
                )
            )
            == "direct"
        )


class TestSummaryPreview:
    def test_an_empty_profile_yields_an_empty_summary_and_a_to_do_list_not_filler(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        s = client.get(profile_url(wid, "/summary")).json()
        assert (
            s["headline"] is None
            and s["intro"] is None
            and s["sections"] == []
            and s["links"] == []
        )
        assert {"role_title", "services", "target_clients", "tone"} <= {
            o["field"] for o in s["omitted"]
        }

    def test_summary_contains_only_what_was_entered(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        client.patch(profile_url(wid), json=FULL)
        s = client.get(profile_url(wid, "/summary")).json()
        assert s["headline"] == FULL["role_title"] and s["intro"] == FULL["summary"]
        sections = {x["title"]: x["items"] for x in s["sections"]}
        assert sections["Services"] == FULL["services"] and sections["Skills"] == FULL["skills"]
        assert sections["Experience"] == ["8 years of experience", FULL["experience_summary"]]
        assert sections["Get in touch"] == [FULL["preferred_cta"]]
        assert s["links"] == FULL["portfolio_urls"] and s["omitted"] == []
        # Every string in the summary is either a user-entered value or a fixed section title.
        entered = json.dumps(FULL)
        allowed_extra = {"8 years of experience"}
        for items in sections.values():
            for item in items:
                assert item in entered or item in allowed_extra

    def test_private_fields_never_appear_in_the_public_summary(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        client.patch(
            profile_url(wid),
            json=FULL | {"business_goal": "find_new_clients", "business_goal_notes": "SECRET-GOAL"},
        )
        raw = client.get(profile_url(wid, "/summary")).text
        for secret in (
            FULL["pricing_guidance"],
            "Gambling operators",
            FULL["tone_notes"],
            "SECRET-GOAL",
        ):
            assert secret not in raw
        assert "private_fields_excluded" in raw

    def test_missing_optional_parts_are_omitted_not_invented(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        client.patch(profile_url(wid), json={"role_title": "Designer", "services": ["Branding"]})
        s = client.get(profile_url(wid, "/summary")).json()
        assert [x["title"] for x in s["sections"]] == ["Services"]
        rendered = json.dumps(
            {
                "headline": s["headline"],
                "intro": s["intro"],
                "sections": s["sections"],
                "links": s["links"],
            }
        )
        assert "Experience" not in rendered and "years" not in rendered
        assert {"skills", "years_experience"} <= {o["field"] for o in s["omitted"]}


class TestAccessAndAudit:
    def test_other_users_cannot_read_or_change_my_profile(
        self, client: TestClient, other: TestClient
    ) -> None:
        mine = make_user(client)["workspace_id"]
        make_user(other)
        client.patch(profile_url(mine), json={"role_title": "Mine"})
        for resp in (
            other.get(profile_url(mine)),
            other.patch(profile_url(mine), json={"role_title": "Hijacked"}),
            other.get(profile_url(mine, "/summary")),
            other.get(f"/api/v1/workspaces/{mine}/ai-context"),
        ):
            assert resp.status_code == 404 and resp.json()["error"]["code"] == "workspace_not_found"
        assert client.get(profile_url(mine)).json()["role_title"] == "Mine"

    def test_authentication_and_csrf_are_required(self, client: TestClient) -> None:
        wid = str(uuid.uuid4())
        assert [
            client.get(profile_url(wid)).status_code,
            client.patch(profile_url(wid), json={}).status_code,
            client.get(profile_url(wid, "/summary")).status_code,
            client.get(f"/api/v1/workspaces/{wid}/ai-context").status_code,
        ] == [401] * 4
        mine = make_user(client)["workspace_id"]
        forged = client.patch(
            profile_url(mine), json={"role_title": "x"}, headers={"Origin": "https://evil.example"}
        )
        assert forged.status_code == 403

    def test_members_can_read_but_only_owners_can_write(
        self, client: TestClient, other: TestClient, db: DbSession
    ) -> None:
        owner = make_user(client)
        member = make_user(other)
        add_member(db, owner["workspace_id"], member["me"]["user"]["id"])
        client.patch(profile_url(owner["workspace_id"]), json={"role_title": "Owner's"})
        assert other.get(profile_url(owner["workspace_id"])).json()["role_title"] == "Owner's"
        denied = other.patch(profile_url(owner["workspace_id"]), json={"role_title": "Nope"})
        assert denied.status_code == 403 and denied.json()["error"]["code"] == "forbidden"
        assert client.get(profile_url(owner["workspace_id"])).json()["role_title"] == "Owner's"

    def test_updates_are_audited_with_field_names_but_never_values(
        self, client: TestClient, db: DbSession
    ) -> None:
        wid = make_user(client)["workspace_id"]
        client.patch(
            profile_url(wid), json={"pricing_guidance": "TOP-SECRET-RATES", "role_title": "Dev"}
        )
        client.patch(profile_url(wid), json={"role_title": "Dev"})  # no change => no event
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.workspace_id == uuid.UUID(wid), AuditEvent.action == "profile.updated"
            )
        ).all()
        assert len(events) == 1
        assert events[0].details == {"fields": ["pricing_guidance", "role_title"], "version": 2}
        assert "TOP-SECRET" not in str(events[0].details)
