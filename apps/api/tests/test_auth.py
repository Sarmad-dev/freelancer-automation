from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.clock import utcnow
from app.config import get_settings
from app.db.models import AuditEvent, Membership, OnboardingProgress, User, Workspace
from app.db.models import Session as LoginSession
from app.security.tokens import hash_token
from tests.conftest import PASSWORD, make_user

SIGN_UP = "/api/v1/auth/sign-up"
SIGN_IN = "/api/v1/auth/sign-in"
ME = "/api/v1/auth/me"


def _email() -> str:
    return f"user-{uuid.uuid4().hex[:10]}@example.com"


def _fresh(client: TestClient) -> TestClient:
    client.cookies.clear()
    return client


class TestSignUp:
    def test_creates_user_personal_workspace_owner_membership_and_session(
        self, client: TestClient, db: DbSession
    ) -> None:
        u = make_user(client)
        me = u["me"]
        assert me["user"]["email"] == u["email"]
        assert me["user"]["email_verified"] is False
        assert len(me["workspaces"]) == 1
        ws = me["workspaces"][0]
        assert (ws["kind"], ws["role"], ws["onboarding_status"]) == (
            "personal",
            "owner",
            "not_started",
        )
        assert ws["name"] == "Ada Lovelace's workspace"

        user = db.scalar(select(User).where(User.email_normalized == u["email"]))
        assert user is not None
        assert user.password_hash.startswith("$argon2id$")
        assert PASSWORD not in user.password_hash
        assert db.scalar(select(Membership).where(Membership.user_id == user.id)) is not None
        assert client.get(ME).status_code == 200

    def test_response_and_cookie_never_expose_secrets(self, client: TestClient) -> None:
        res = client.post(
            SIGN_UP, json={"email": _email(), "password": PASSWORD, "display_name": "Grace"}
        )
        assert "password" not in res.text.lower() or "password_hash" not in res.text
        assert "argon2" not in res.text
        cookie = res.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "samesite=lax" in cookie
        assert "path=/" in cookie
        assert "fos_session=" in cookie

    def test_session_token_is_stored_hashed(self, client: TestClient, db: DbSession) -> None:
        make_user(client)
        raw = client.cookies.get("fos_session")
        assert raw
        assert db.scalar(select(LoginSession).where(LoginSession.token_hash == raw)) is None
        assert (
            db.scalar(select(LoginSession).where(LoginSession.token_hash == hash_token(raw)))
            is not None
        )

    @pytest.mark.parametrize(
        ("payload", "field"),
        [
            ({"email": "not-an-email", "password": PASSWORD, "display_name": "A"}, "email"),
            ({"email": "a@example.com", "password": "short", "display_name": "A"}, "password"),
            (
                {"email": "a@example.com", "password": "password1234", "display_name": "A"},
                "password",
            ),
            (
                {"email": "a@example.com", "password": "aaaaaaaaaaaaaaaa", "display_name": "A"},
                "password",
            ),
            (
                {
                    "email": "alice.smith@example.com",
                    "password": "xx-alice.smith-xx",
                    "display_name": "A",
                },
                "password",
            ),
            ({"email": "a@example.com", "password": "x" * 129, "display_name": "A"}, "password"),
            (
                {"email": "a@example.com", "password": PASSWORD, "display_name": "   "},
                "display_name",
            ),
            (
                {"email": "a@example.com", "password": PASSWORD, "display_name": "x" * 121},
                "display_name",
            ),
            (
                {"email": "a@example.com", "password": PASSWORD, "display_name": "bad\x00name"},
                "display_name",
            ),
            ({"email": "a@example.com", "password": PASSWORD}, "display_name"),
        ],
    )
    def test_invalid_input_returns_field_errors(
        self, client: TestClient, payload: dict[str, str], field: str
    ) -> None:
        res = client.post(SIGN_UP, json=payload)
        assert res.status_code == 422, res.text
        err = res.json()["error"]
        assert err["code"] == "validation_error"
        assert field in err["fields"]
        assert "set-cookie" not in res.headers

    def test_duplicate_email_is_case_insensitive(self, client: TestClient) -> None:
        u = make_user(client)
        _fresh(client)
        res = client.post(
            SIGN_UP,
            json={"email": u["email"].upper(), "password": PASSWORD, "display_name": "Other"},
        )
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "email_in_use"

    def test_unknown_fields_are_ignored_not_persisted(
        self, client: TestClient, db: DbSession
    ) -> None:
        res = client.post(
            SIGN_UP,
            json={
                "email": _email(),
                "password": PASSWORD,
                "display_name": "Mal",
                "is_active": False,
                "id": str(uuid.uuid4()),
            },
        )
        assert res.status_code == 201
        assert (
            db.scalar(select(User).where(User.id == uuid.UUID(res.json()["user"]["id"])))
            is not None
        )

    def test_audit_event_has_no_credentials(self, client: TestClient, db: DbSession) -> None:
        u = make_user(client)
        user_id = uuid.UUID(u["me"]["user"]["id"])
        events = db.scalars(select(AuditEvent).where(AuditEvent.actor_user_id == user_id)).all()
        assert [e.action for e in events] == ["auth.sign_up"]
        blob = " ".join(
            str(v) for e in events for v in (e.details, e.target_id, e.user_agent, e.action)
        )
        assert PASSWORD not in blob and "argon2" not in blob

    def test_sign_up_rate_limited_per_ip(self, client: TestClient) -> None:
        for _ in range(10):
            _fresh(client)
            client.post(
                SIGN_UP, json={"email": _email(), "password": "tooshort", "display_name": "A"}
            )
        res = client.post(
            SIGN_UP, json={"email": _email(), "password": PASSWORD, "display_name": "A"}
        )
        assert res.status_code == 429
        assert int(res.headers["retry-after"]) > 0
        assert res.json()["error"]["code"] == "rate_limited"


class TestSignIn:
    def test_success_creates_new_session_and_audit(self, client: TestClient, db: DbSession) -> None:
        u = make_user(client)
        old = client.cookies.get("fos_session")
        res = client.post(SIGN_IN, json={"email": u["email"].upper(), "password": u["password"]})
        assert res.status_code == 200
        assert client.cookies.get("fos_session") != old  # session id rotates on sign-in
        actions = db.scalars(
            select(AuditEvent.action).where(
                AuditEvent.actor_user_id == uuid.UUID(u["me"]["user"]["id"])
            )
        ).all()
        assert "auth.sign_in" in actions

    def test_wrong_password_and_unknown_user_look_identical(self, client: TestClient) -> None:
        u = make_user(client)
        _fresh(client)
        wrong = client.post(SIGN_IN, json={"email": u["email"], "password": "wrong password!"})
        unknown = client.post(SIGN_IN, json={"email": _email(), "password": "wrong password!"})
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json() == unknown.json()
        assert wrong.json()["error"]["code"] == "invalid_credentials"
        assert "set-cookie" not in wrong.headers

    def test_failed_attempts_are_audited_without_the_email_or_password(
        self, client: TestClient, db: DbSession
    ) -> None:
        email = _email()
        client.post(SIGN_IN, json={"email": email, "password": "very-secret-guess"})
        ev = db.scalars(
            select(AuditEvent)
            .where(AuditEvent.action == "auth.sign_in_failed")
            .order_by(AuditEvent.created_at.desc())
        ).first()
        assert ev is not None
        assert email not in str(ev.details) and "very-secret-guess" not in str(ev.details)
        assert len(ev.details["email_hash"]) == 12

    def test_account_lockout_window_and_reset_on_success(self, client: TestClient) -> None:
        u = make_user(client)
        _fresh(client)
        for _ in range(10):
            assert (
                client.post(
                    SIGN_IN, json={"email": u["email"], "password": "nope nope nope"}
                ).status_code
                == 401
            )
        blocked = client.post(SIGN_IN, json={"email": u["email"], "password": u["password"]})
        assert blocked.status_code == 429  # even the right password is refused while locked
        assert int(blocked.headers["retry-after"]) > 0

    def test_successful_sign_in_resets_the_counter(self, client: TestClient) -> None:
        u = make_user(client)
        _fresh(client)
        for _ in range(8):
            client.post(SIGN_IN, json={"email": u["email"], "password": "nope nope nope"})
        assert (
            client.post(SIGN_IN, json={"email": u["email"], "password": u["password"]}).status_code
            == 200
        )
        for _ in range(8):
            assert (
                client.post(
                    SIGN_IN, json={"email": u["email"], "password": "nope nope nope"}
                ).status_code
                == 401
            )

    def test_inactive_user_cannot_sign_in(self, client: TestClient, db: DbSession) -> None:
        u = make_user(client)
        db.execute(
            User.__table__.update()
            .where(User.email_normalized == u["email"])
            .values(is_active=False)
        )
        db.commit()
        _fresh(client)
        assert (
            client.post(SIGN_IN, json={"email": u["email"], "password": u["password"]}).status_code
            == 401
        )

    def test_inactive_user_existing_session_is_rejected(
        self, client: TestClient, db: DbSession
    ) -> None:
        u = make_user(client)
        db.execute(
            User.__table__.update()
            .where(User.email_normalized == u["email"])
            .values(is_active=False)
        )
        db.commit()
        assert client.get(ME).status_code == 401

    def test_oversized_password_rejected_before_hashing(self, client: TestClient) -> None:
        res = client.post(SIGN_IN, json={"email": _email(), "password": "x" * 5000})
        assert res.status_code == 422


class TestSessions:
    def test_protected_endpoint_requires_authentication(self, client: TestClient) -> None:
        res = client.get(ME)
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "not_authenticated"

    def test_tampered_or_unknown_cookie_is_rejected_and_cleared(self, client: TestClient) -> None:
        make_user(client)
        client.cookies.set("fos_session", "definitely-not-a-valid-token", domain="localhost.local")
        client.cookies.clear()
        client.cookies.set("fos_session", "definitely-not-a-valid-token")
        res = client.get(ME)
        assert res.status_code == 401
        assert "fos_session" in res.headers.get("set-cookie", "")  # cleared

    def test_sign_out_revokes_session_server_side(self, client: TestClient, db: DbSession) -> None:
        make_user(client)
        token = client.cookies.get("fos_session")
        assert token
        res = client.post("/api/v1/auth/sign-out")
        assert res.status_code == 204
        assert "max-age=0" in res.headers["set-cookie"].lower()
        # Replaying the old cookie must fail: the session row is gone, not merely the cookie.
        client.cookies.set("fos_session", token)
        assert client.get(ME).status_code == 401
        assert (
            db.scalar(select(LoginSession).where(LoginSession.token_hash == hash_token(token)))
            is None
        )

    def test_sign_out_is_idempotent_without_a_session(self, client: TestClient) -> None:
        assert client.post("/api/v1/auth/sign-out").status_code == 204

    def test_idle_session_expires(self, client: TestClient, db: DbSession) -> None:
        make_user(client)
        settings = get_settings()
        s = db.scalar(select(LoginSession).order_by(LoginSession.created_at.desc()))
        assert s is not None
        session_id = s.id
        s.last_seen_at = utcnow() - timedelta(minutes=settings.session_idle_timeout_minutes + 1)
        db.commit()
        res = client.get(ME)
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "session_expired"
        assert "max-age=0" in res.headers["set-cookie"].lower()
        db.expire_all()
        assert db.get(LoginSession, session_id) is None
        assert client.get(ME).json()["error"]["code"] == "not_authenticated"

    def test_absolute_lifetime_is_enforced_even_if_active(
        self, client: TestClient, db: DbSession
    ) -> None:
        make_user(client)
        s = db.scalar(select(LoginSession).order_by(LoginSession.created_at.desc()))
        assert s is not None
        s.expires_at = utcnow() - timedelta(seconds=1)
        s.last_seen_at = utcnow()
        db.commit()
        assert client.get(ME).json()["error"]["code"] == "session_expired"

    def test_activity_refreshes_the_server_side_idle_window(
        self, client: TestClient, db: DbSession
    ) -> None:
        make_user(client)
        s = db.scalar(select(LoginSession).order_by(LoginSession.created_at.desc()))
        assert s is not None
        before = utcnow() - timedelta(minutes=30)
        s.last_seen_at = before
        db.commit()
        res = client.get(ME)
        assert res.status_code == 200
        assert (
            "set-cookie" not in res.headers
        )  # cookie lifetime is the absolute cap; idle is server-side
        db.expire_all()
        refreshed = db.get(LoginSession, s.id)
        assert refreshed is not None and refreshed.last_seen_at.replace(
            tzinfo=None
        ) > before.replace(tzinfo=None)

    def test_cookie_lifetime_matches_absolute_session_cap(self, client: TestClient) -> None:
        res = client.post(
            SIGN_UP, json={"email": _email(), "password": PASSWORD, "display_name": "Cap"}
        )
        max_age = int(res.headers["set-cookie"].lower().split("max-age=")[1].split(";")[0])
        days = get_settings().session_absolute_timeout_days
        assert days * 86400 - 60 <= max_age <= days * 86400

    def test_production_cookies_are_secure_and_host_prefixed(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(get_settings(), "app_env", "production")
        res = client.post(
            SIGN_UP, json={"email": _email(), "password": PASSWORD, "display_name": "Prod"}
        )
        assert res.status_code == 201
        header = res.headers["set-cookie"]
        assert header.startswith("__Host-fos_session=")
        assert "Secure" in header and "HttpOnly" in header and "Path=/" in header
        assert "Domain" not in header


class TestCsrf:
    def test_cross_origin_post_is_rejected(self, client: TestClient) -> None:
        res = client.post(
            SIGN_UP,
            json={"email": _email(), "password": PASSWORD, "display_name": "X"},
            headers={"Origin": "https://evil.example"},
        )
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "csrf_rejected"

    def test_post_without_origin_needs_custom_header(self, client: TestClient) -> None:
        payload = {"email": _email(), "password": PASSWORD, "display_name": "X"}
        no_origin = TestClient(client.app)
        assert no_origin.post(SIGN_UP, json=payload).status_code == 403
        ok = no_origin.post(SIGN_UP, json=payload, headers={"X-Requested-With": "freelancer-os"})
        assert ok.status_code == 201

    def test_null_origin_rejected_and_gets_are_unaffected(self, client: TestClient) -> None:
        assert client.post("/api/v1/auth/sign-out", headers={"Origin": "null"}).status_code == 403
        assert client.get("/health", headers={"Origin": "https://evil.example"}).status_code == 200

    def test_sign_out_cannot_be_forced_cross_site(self, client: TestClient) -> None:
        make_user(client)
        res = client.post("/api/v1/auth/sign-out", headers={"Origin": "https://evil.example"})
        assert res.status_code == 403
        assert client.get(ME).status_code == 200


class TestPasswordReset:
    def test_full_flow_revokes_sessions_and_is_single_use(
        self,
        client: TestClient,
        mailer,
        db: DbSession,  # type: ignore[no-untyped-def]
    ) -> None:
        u = make_user(client)
        res = client.post("/api/v1/auth/password-reset/request", json={"email": u["email"]})
        assert res.status_code == 202
        assert len(mailer.sent) == 1
        to, url = mailer.sent[0]
        assert to == u["email"] and url.startswith("http://localhost:3000/reset-password?token=")
        token = url.split("token=")[1]
        # Only the hash is stored.
        from app.db.models import PasswordResetToken

        assert (
            db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == token))
            is None
        )

        new_pw = "a brand new passphrase"
        done = client.post(
            "/api/v1/auth/password-reset/confirm", json={"token": token, "password": new_pw}
        )
        assert done.status_code == 204
        assert client.get(ME).status_code == 401  # the earlier session was revoked
        again = client.post(
            "/api/v1/auth/password-reset/confirm", json={"token": token, "password": new_pw + "x"}
        )
        assert again.status_code == 400 and again.json()["error"]["code"] == "invalid_token"
        assert (
            client.post(SIGN_IN, json={"email": u["email"], "password": u["password"]}).status_code
            == 401
        )
        assert (
            client.post(SIGN_IN, json={"email": u["email"], "password": new_pw}).status_code == 200
        )

    def test_request_does_not_reveal_whether_email_is_registered(
        self,
        client: TestClient,
        mailer,  # type: ignore[no-untyped-def]
    ) -> None:
        known = make_user(client)
        _fresh(client)
        a = client.post("/api/v1/auth/password-reset/request", json={"email": known["email"]})
        b = client.post("/api/v1/auth/password-reset/request", json={"email": _email()})
        assert a.status_code == b.status_code == 202
        assert a.json() == b.json()
        assert len(mailer.sent) == 1

    def test_only_newest_link_works(self, client: TestClient, mailer) -> None:  # type: ignore[no-untyped-def]
        u = make_user(client)
        for _ in range(2):
            client.post("/api/v1/auth/password-reset/request", json={"email": u["email"]})
        first = mailer.sent[0][1].split("token=")[1]
        second = mailer.sent[1][1].split("token=")[1]
        pw = "yet another passphrase"
        assert (
            client.post(
                "/api/v1/auth/password-reset/confirm", json={"token": first, "password": pw}
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/api/v1/auth/password-reset/confirm", json={"token": second, "password": pw}
            ).status_code
            == 204
        )

    def test_expired_token_and_weak_password_are_rejected(
        self,
        client: TestClient,
        mailer,
        db: DbSession,  # type: ignore[no-untyped-def]
    ) -> None:
        from app.db.models import PasswordResetToken

        u = make_user(client)
        client.post("/api/v1/auth/password-reset/request", json={"email": u["email"]})
        token = mailer.sent[0][1].split("token=")[1]
        weak = client.post(
            "/api/v1/auth/password-reset/confirm", json={"token": token, "password": "short"}
        )
        assert weak.status_code == 422 and "password" in weak.json()["error"]["fields"]
        rec = db.scalar(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(token))
        )
        assert (
            rec is not None and rec.used_at is None
        )  # a rejected password does not burn the token
        rec.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
        res = client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": token, "password": "a fine passphrase"},
        )
        assert res.status_code == 400

    def test_garbage_token_rejected(self, client: TestClient) -> None:
        res = client.post(
            "/api/v1/auth/password-reset/confirm", json={"token": "x" * 40, "password": PASSWORD}
        )
        assert res.status_code == 400
        assert (
            client.post(
                "/api/v1/auth/password-reset/confirm",
                json={"token": "bad token!!bad token!!", "password": PASSWORD},
            ).status_code
            == 422
        )

    def test_unavailable_when_mail_backend_disabled(self, client: TestClient) -> None:
        from app.mailer import DisabledMailer

        client.app.state.mailer = DisabledMailer()  # type: ignore[attr-defined]
        assert client.get("/api/v1/auth/config").json() == {"password_reset_enabled": False}
        res = client.post("/api/v1/auth/password-reset/request", json={"email": _email()})
        assert (
            res.status_code == 503 and res.json()["error"]["code"] == "password_reset_unavailable"
        )

    def test_request_is_rate_limited_per_email(self, client: TestClient) -> None:
        email = _email()
        codes = [
            client.post("/api/v1/auth/password-reset/request", json={"email": email}).status_code
            for _ in range(6)
        ]
        assert codes == [202] * 5 + [429]

    def test_audit_trail(self, client: TestClient, mailer, db: DbSession) -> None:  # type: ignore[no-untyped-def]
        u = make_user(client)
        client.post("/api/v1/auth/password-reset/request", json={"email": u["email"]})
        token = mailer.sent[0][1].split("token=")[1]
        client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": token, "password": "a fine new passphrase"},
        )
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.actor_user_id == uuid.UUID(u["me"]["user"]["id"]))
        ).all()
        actions = {e.action for e in events}
        assert {"auth.password_reset_requested", "auth.password_reset_completed"} <= actions
        assert token not in str([e.details for e in events])


def test_error_format_for_unknown_routes_and_methods(client: TestClient) -> None:
    res = client.get("/api/v1/nope")
    assert res.status_code == 404 and res.json()["error"]["code"] == "not_found"
    assert client.get(SIGN_IN).status_code == 405


def test_signing_up_creates_exactly_one_workspace_and_onboarding_row(
    client: TestClient, db: DbSession
) -> None:
    u = make_user(client)
    wid = uuid.UUID(u["workspace_id"])
    assert db.scalar(select(Workspace).where(Workspace.id == wid)) is not None
    rows = db.scalars(
        select(OnboardingProgress).where(OnboardingProgress.workspace_id == wid)
    ).all()
    assert len(rows) == 1 and rows[0].status == "not_started"
