from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db.models import AuditEvent, FreelancerProfile
from app.schemas.onboarding import REQUIRED_STEPS, STEP_IDS
from tests.conftest import make_user

VALID: dict[str, dict[str, Any]] = {
    "role": {
        "step": "role",
        "role_title": "Independent web developer",
        "summary": "I build fast sites.",
    },
    "services": {"step": "services", "services": ["Web development", "Performance audits"]},
    "skills": {"step": "skills", "skills": ["TypeScript", "React", "PostgreSQL"]},
    "target_clients": {
        "step": "target_clients",
        "description": "Seed-stage SaaS founders in Europe.",
    },
    "industries": {"step": "industries", "industries": ["SaaS", "Fintech"]},
    "portfolio": {
        "step": "portfolio",
        "urls": ["https://example.com/work", "https://github.com/example"],
    },
    "experience": {"step": "experience", "years": 8, "summary": "Shipped 40+ projects."},
    "tone": {"step": "tone", "tone": "friendly", "notes": "Plain language, no jargon."},
    "timezone": {"step": "timezone", "timezone": "Europe/Berlin"},
    "goal": {"step": "goal", "goal": "find_new_clients", "notes": ""},
}


def base(wid: str) -> str:
    return f"/api/v1/workspaces/{wid}"


def save(client: TestClient, wid: str, step: str, body: dict[str, Any] | None = None) -> Any:
    return client.put(f"{base(wid)}/onboarding/step", json=body or VALID[step])


def fill_required(client: TestClient, wid: str) -> None:
    for step in STEP_IDS:
        if step in REQUIRED_STEPS:
            assert save(client, wid, step).status_code == 200, step


def test_every_endpoint_requires_authentication(client: TestClient) -> None:
    wid = str(uuid.uuid4())
    calls = [
        client.get(f"{base(wid)}/onboarding"),
        client.put(f"{base(wid)}/onboarding/step", json=VALID["role"]),
        client.post(f"{base(wid)}/onboarding/skip"),
        client.post(f"{base(wid)}/onboarding/complete"),
        client.put(f"{base(wid)}/demo-mode", json={"enabled": True}),
    ]
    assert [c.status_code for c in calls] == [401] * 5
    assert {c.json()["error"]["code"] for c in calls} == {"not_authenticated"}


class TestProgressAndResume:
    def test_initial_state(self, client: TestClient) -> None:
        u = make_user(client)
        state = client.get(f"{base(u['workspace_id'])}/onboarding").json()
        assert state["status"] == "not_started"
        assert state["current_step"] == "role"
        assert state["completed_count"] == 0 and state["total_count"] == 10
        assert [s["id"] for s in state["steps"]] == list(STEP_IDS)
        required = {s["id"] for s in state["steps"] if s["required"]}
        assert required == set(REQUIRED_STEPS)
        assert state["profile"]["timezone"] == "UTC" and state["demo_mode"] is False

    def test_saving_steps_persists_and_advances(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        state = save(client, wid, "role").json()
        assert state["status"] == "in_progress"
        assert state["current_step"] == "services"
        assert state["profile"]["role_title"] == "Independent web developer"
        state = save(client, wid, "services").json()
        assert state["current_step"] == "skills" and state["completed_count"] == 2

    def test_resume_after_signing_out_and_in(self, client: TestClient) -> None:
        u = make_user(client)
        wid = u["workspace_id"]
        save(client, wid, "role")
        save(client, wid, "services")
        client.post("/api/v1/auth/sign-out")
        client.post("/api/v1/auth/sign-in", json={"email": u["email"], "password": u["password"]})
        me = client.get("/api/v1/auth/me").json()
        assert me["workspaces"][0]["onboarding_status"] == "in_progress"
        state = client.get(f"{base(wid)}/onboarding").json()
        assert state["current_step"] == "skills"
        assert state["profile"]["services"] == ["Web development", "Performance audits"]

    def test_saving_a_step_twice_is_idempotent_and_editable(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        save(client, wid, "skills")
        state = save(client, wid, "skills", {"step": "skills", "skills": ["Rust"]}).json()
        assert state["profile"]["skills"] == ["Rust"]
        assert state["completed_count"] == 1

    def test_skip_keeps_progress_and_resuming_reactivates(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        save(client, wid, "role")
        skipped = client.post(f"{base(wid)}/onboarding/skip").json()
        assert skipped["status"] == "skipped" and skipped["completed_count"] == 1
        assert (
            client.get("/api/v1/auth/me").json()["workspaces"][0]["onboarding_status"] == "skipped"
        )
        resumed = save(client, wid, "services").json()
        assert resumed["status"] == "in_progress" and resumed["completed_count"] == 2

    def test_skip_without_any_progress_is_allowed(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        assert client.post(f"{base(wid)}/onboarding/skip").json()["status"] == "skipped"

    def test_complete_requires_all_required_steps(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        save(client, wid, "role")
        res = client.post(f"{base(wid)}/onboarding/complete")
        assert res.status_code == 409
        err = res.json()["error"]
        assert err["code"] == "onboarding_incomplete"
        assert set(err["fields"]) == REQUIRED_STEPS - {"role"}

    def test_complete_with_optional_steps_missing_then_edit_after(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        fill_required(client, wid)
        done = client.post(f"{base(wid)}/onboarding/complete").json()
        assert done["status"] == "completed"
        # Re-saving a step after completion does not reopen onboarding or lose completion.
        again = save(client, wid, "industries").json()
        assert again["status"] == "completed"
        assert client.post(f"{base(wid)}/onboarding/skip").json()["status"] == "completed"

    def test_timezone_step_updates_workspace(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        save(client, wid, "timezone")
        assert client.get("/api/v1/auth/me").json()["workspaces"][0]["timezone"] == "Europe/Berlin"

    def test_demo_mode_toggle(self, client: TestClient, db: DbSession) -> None:
        wid = make_user(client)["workspace_id"]
        res = client.put(f"{base(wid)}/demo-mode", json={"enabled": True})
        assert res.status_code == 200 and res.json()["demo_mode"] is True
        assert client.get(f"{base(wid)}/onboarding").json()["demo_mode"] is True
        assert client.put(f"{base(wid)}/demo-mode", json={"enabled": "maybe"}).status_code == 422
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.action == "workspace.demo_mode_changed")
        ).all()
        assert events and events[-1].details == {"demo_mode": True}


class TestValidation:
    @pytest.mark.parametrize(
        ("body", "field"),
        [
            ({"step": "role", "role_title": "x"}, "role_title"),
            ({"step": "role", "role_title": "Dev", "summary": "x" * 501}, "summary"),
            ({"step": "role", "role_title": "De\x00v"}, "role_title"),
            ({"step": "services", "services": []}, "services"),
            ({"step": "services", "services": ["  ", ""]}, "services"),
            ({"step": "services", "services": [f"s{i}" * 2 for i in range(16)]}, "services"),
            ({"step": "services", "services": ["x" * 81]}, "services"),
            ({"step": "skills", "skills": []}, "skills"),
            ({"step": "target_clients", "description": "short"}, "description"),
            ({"step": "industries", "industries": ["a" * 61]}, "industries"),
            ({"step": "experience", "years": -1}, "years"),
            ({"step": "experience", "years": 61}, "years"),
            ({"step": "experience", "years": "lots"}, "years"),
            ({"step": "tone", "tone": "sarcastic"}, "tone"),
            ({"step": "timezone", "timezone": "Mars/Olympus"}, "timezone"),
            ({"step": "timezone", "timezone": "posix/UTC"}, "timezone"),
            ({"step": "goal", "goal": "world domination"}, "goal"),
        ],
    )
    def test_invalid_step_payloads_are_rejected_with_field_errors(
        self, client: TestClient, body: dict[str, Any], field: str
    ) -> None:
        wid = make_user(client)["workspace_id"]
        res = save(client, wid, body["step"], body)
        assert res.status_code == 422, res.text
        assert res.json()["error"]["code"] == "validation_error"
        assert field in res.json()["error"]["fields"]
        state = client.get(f"{base(wid)}/onboarding").json()
        assert state["completed_count"] == 0  # nothing saved on failure

    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "ftp://example.com/file",
            "file:///etc/passwd",
            "https://user:pass@example.com/",
            "https://localhost/admin",
            "http://127.0.0.1:8000/",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.5/",
            "http://[::1]/",
            "https://intranet/",
            "https://printer.local/",
            "https://exa mple.com/",
            "https://example.com/\x00",
            "example.com/no-scheme",
            "https://" + "a" * 300 + ".com",
        ],
    )
    def test_portfolio_rejects_unsafe_urls(self, client: TestClient, url: str) -> None:
        wid = make_user(client)["workspace_id"]
        res = save(client, wid, "portfolio", {"step": "portfolio", "urls": [url]})
        assert res.status_code == 422, url
        assert "urls" in res.json()["error"]["fields"]

    def test_portfolio_normalises_and_dedupes(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        res = save(
            client,
            wid,
            "portfolio",
            {
                "step": "portfolio",
                "urls": ["HTTPS://Example.COM/Work", "https://example.com/Work", "  "],
            },
        )
        assert res.status_code == 200
        assert res.json()["profile"]["portfolio_urls"] == ["https://example.com/Work"]

    def test_lists_are_cleaned_and_deduplicated_case_insensitively(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        res = save(
            client,
            wid,
            "skills",
            {"step": "skills", "skills": [" React ", "react", "REACT", "Vue  3"]},
        )
        assert res.json()["profile"]["skills"] == ["React", "Vue 3"]

    def test_unknown_step_extra_fields_and_workspace_id_in_body_are_rejected(
        self, client: TestClient
    ) -> None:
        wid = make_user(client)["workspace_id"]
        assert save(client, wid, "x", {"step": "hack", "x": 1}).status_code == 422
        evil = {**VALID["role"], "workspace_id": str(uuid.uuid4())}
        assert save(client, wid, "role", evil).status_code == 422
        assert save(client, wid, "role", {**VALID["role"], "is_admin": True}).status_code == 422

    def test_whitespace_is_collapsed_in_single_line_fields(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        res = save(client, wid, "role", {"step": "role", "role_title": "  Senior   web\tdev  "})
        assert res.json()["profile"]["role_title"] == "Senior web dev"

    def test_stored_text_is_not_interpreted(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        payload = "<img src=x onerror=alert(1)> {{7*7}} '; DROP TABLE users;--"
        res = save(
            client, wid, "target_clients", {"step": "target_clients", "description": payload}
        )
        assert res.status_code == 200
        assert (
            res.json()["profile"]["target_clients"] == payload
        )  # stored verbatim, rendered as text by the UI
        assert client.get("/api/v1/auth/me").status_code == 200


class TestWorkspaceIsolation:
    def _two_users(
        self, client: TestClient, other: TestClient
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        a = make_user(client, name="Alice")
        b = make_user(other, name="Bob")
        return a, b

    @pytest.fixture
    def other(self, client: TestClient) -> TestClient:
        # A second browser: separate cookie jar, same app.
        c = TestClient(client.app, headers=dict(client.headers), base_url="http://localhost:3000")
        return c

    def test_user_cannot_read_or_modify_another_workspace(
        self, client: TestClient, other: TestClient
    ) -> None:
        a, b = self._two_users(client, other)
        save(client, a["workspace_id"], "role")
        victim = base(a["workspace_id"])

        # Bob targets Alice's workspace id with every verb.
        attempts = [
            other.get(f"{victim}/onboarding"),
            other.put(f"{victim}/onboarding/step", json=VALID["goal"]),
            other.post(f"{victim}/onboarding/skip"),
            other.post(f"{victim}/onboarding/complete"),
            other.put(f"{victim}/demo-mode", json={"enabled": True}),
        ]
        assert [r.status_code for r in attempts] == [404] * 5
        assert {r.json()["error"]["code"] for r in attempts} == {"workspace_not_found"}

        # Alice's data is untouched.
        state = client.get(f"{victim}/onboarding").json()
        assert state["completed_count"] == 1 and state["profile"]["business_goal"] is None
        assert state["status"] == "in_progress" and state["demo_mode"] is False

        # And Bob's own workspace is untouched by Alice's role save.
        assert other.get(f"{base(b['workspace_id'])}/onboarding").json()["completed_count"] == 0

    def test_foreign_and_nonexistent_workspaces_are_indistinguishable(
        self, client: TestClient, other: TestClient
    ) -> None:
        a, _ = self._two_users(client, other)
        foreign = other.get(f"{base(a['workspace_id'])}/onboarding")
        missing = other.get(f"{base(str(uuid.uuid4()))}/onboarding")
        assert foreign.status_code == missing.status_code == 404
        assert foreign.json() == missing.json()
        assert other.get(f"{base('not-a-uuid')}/onboarding").status_code == 422

    def test_me_only_lists_own_workspaces(self, client: TestClient, other: TestClient) -> None:
        a, b = self._two_users(client, other)
        ids = lambda c: {w["id"] for w in c.get("/api/v1/auth/me").json()["workspaces"]}  # noqa: E731
        assert ids(client) == {a["workspace_id"]}
        assert ids(other) == {b["workspace_id"]}

    def test_profiles_are_stored_per_workspace(
        self, client: TestClient, other: TestClient, db: DbSession
    ) -> None:
        a, b = self._two_users(client, other)
        save(client, a["workspace_id"], "skills", {"step": "skills", "skills": ["Alice-skill"]})
        save(other, b["workspace_id"], "skills", {"step": "skills", "skills": ["Bob-skill"]})
        rows = {
            str(p.workspace_id): p.skills
            for p in db.scalars(
                select(FreelancerProfile).where(
                    FreelancerProfile.workspace_id.in_(
                        [uuid.UUID(a["workspace_id"]), uuid.UUID(b["workspace_id"])]
                    )
                )
            )
        }
        assert rows == {a["workspace_id"]: ["Alice-skill"], b["workspace_id"]: ["Bob-skill"]}

    def test_session_of_one_user_never_authorises_another_users_workspace_after_signout(
        self, client: TestClient, other: TestClient
    ) -> None:
        a, _ = self._two_users(client, other)
        client.post("/api/v1/auth/sign-out")
        assert client.get(f"{base(a['workspace_id'])}/onboarding").status_code == 401


def test_onboarding_actions_are_audited_without_profile_contents(
    client: TestClient, db: DbSession
) -> None:
    u = make_user(client)
    wid = u["workspace_id"]
    save(
        client,
        wid,
        "target_clients",
        {"step": "target_clients", "description": "Highly confidential client list"},
    )
    client.post(f"{base(wid)}/onboarding/skip")
    events = db.scalars(select(AuditEvent).where(AuditEvent.workspace_id == uuid.UUID(wid))).all()
    actions = [e.action for e in events]
    assert "onboarding.step_saved" in actions and "onboarding.skipped" in actions
    assert "confidential" not in str([(e.details, e.target_id) for e in events])
