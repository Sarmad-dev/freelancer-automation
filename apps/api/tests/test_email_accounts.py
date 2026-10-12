"""Mailbox accounts through the API: demo mailbox, OAuth connect (state, PKCE, scopes), tokens, sync, health, disconnect."""

from __future__ import annotations

import base64
import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db.models import AuditEvent
from app.db.models_crm import Activity, Contact, Lead
from app.db.models_email import Conversation, CredentialSecret, EmailAccount, Message
from app.mailbox.errors import (
    AccessRevoked,
    AuthExpired,
    HistoryExpired,
    InsufficientScopes,
    PermanentError,
    RateLimited,
    TransientError,
)
from app.mailbox.gmail import REQUIRED_SCOPES
from app.mailbox.types import AccountProfile, SyncPage
from app.security.credentials import EncryptedDbCredentialStore
from tests.conftest import add_member, make_user, second_client
from tests.email_helpers import (
    ACCESS,
    CODE,
    GMAIL_ADDRESS,
    NEW_ACCESS,
    REFRESH,
    callback,
    connect_gmail,
    install,
    remote,
    start_connect,
    tokens,
    ws_url,
)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def page(
    *messages, cursor: str | None = "hist:200", done: bool = True, skipped: int = 0
) -> SyncPage:  # type: ignore[no-untyped-def]
    return SyncPage(tuple(messages), cursor, done, skipped)


def store_of(client: TestClient) -> EncryptedDbCredentialStore:
    return client.app.state.credentials  # type: ignore[no-any-return, attr-defined]


def account_row(db: DbSession, account_id: str) -> EmailAccount:
    db.expire_all()
    row = db.get(EmailAccount, uuid.UUID(account_id))
    assert row is not None
    return row


def now_patch(monkeypatch: pytest.MonkeyPatch, when: datetime) -> None:
    monkeypatch.setattr("app.routers.email.utcnow", lambda: when)


# ----------------------------------------------------------------------------- providers and the demo mailbox


def test_providers_list_is_honest_about_what_is_configured_and_verified(client: TestClient) -> None:
    u = make_user(client)
    res = client.get(ws_url(u["workspace_id"], "/providers"))
    assert res.status_code == 200
    by_key = {p["key"]: p for p in res.json()}
    assert by_key["demo"]["is_demo"] and by_key["demo"]["configured"]
    assert by_key["gmail"]["configured"] is False  # no client id/secret in the test environment
    assert by_key["gmail"]["verified_live"] is False and by_key["demo"]["verified_live"] is False
    assert [s["scope"] for s in by_key["gmail"]["scopes"]] == list(REQUIRED_SCOPES)
    assert all(s["why"] for s in by_key["gmail"]["scopes"])
    assert any("Not verified" in n for n in by_key["gmail"]["notes"])


def test_connecting_an_unconfigured_provider_is_refused_with_a_clear_reason(
    client: TestClient,
) -> None:
    u = make_user(client)
    res = client.post(ws_url(u["workspace_id"], "/accounts/connect"), json={"provider": "gmail"})
    assert res.status_code == 409 and res.json()["error"]["code"] == "provider_not_configured"
    assert (
        client.post(
            ws_url(u["workspace_id"], "/accounts/connect"), json={"provider": "outlook"}
        ).status_code
        == 422
    )


def test_the_demo_mailbox_is_created_once_labelled_and_owner_only(
    client: TestClient, db: DbSession
) -> None:
    owner = make_user(client)
    wid = owner["workspace_id"]
    first = client.post(ws_url(wid, "/accounts/demo"))
    assert first.status_code == 201
    body = first.json()
    assert body["provider"] == "demo" and body["is_demo"] and body["status"] == "demo"
    assert "no real email" in body["status_label"] and body["email_address"].endswith(".example")
    second = client.post(ws_url(wid, "/accounts/demo"))
    assert second.status_code == 200 and second.json()["id"] == body["id"]
    assert len(client.get(ws_url(wid, "/accounts")).json()) == 1
    member = second_client(client)
    m = make_user(member)
    add_member(db, wid, m["me"]["user"]["id"])
    assert member.get(ws_url(wid, "/accounts")).status_code == 200  # members can read
    assert member.post(ws_url(wid, "/accounts/demo")).status_code == 403  # but not change
    assert member.post(ws_url(wid, f"/accounts/{body['id']}/sync")).status_code == 403
    assert member.post(ws_url(wid, f"/accounts/{body['id']}/disconnect")).status_code == 403


def test_demo_sync_is_idempotent_flagged_as_sample_and_separate_from_real_data(
    client: TestClient, db: DbSession
) -> None:
    u = make_user(client)
    wid = u["workspace_id"]
    acct = client.post(ws_url(wid, "/accounts/demo")).json()
    first = client.post(ws_url(wid, f"/accounts/{acct['id']}/sync"))
    assert first.status_code == 200, first.text
    assert (
        first.json()["conversations_created"],
        first.json()["messages_created"],
        first.json()["complete"],
    ) == (3, 6, True)
    again = client.post(ws_url(wid, f"/accounts/{acct['id']}/sync")).json()
    assert (
        again["conversations_created"],
        again["messages_created"],
        again["messages_updated"],
    ) == (0, 0, 0)
    rows = db.scalars(select(Message).where(Message.workspace_id == uuid.UUID(wid))).all()
    assert len(rows) == 6 and all(m.is_sample and m.delivery_state == "demo" for m in rows)
    assert all(
        c.is_sample
        for c in db.scalars(select(Conversation).where(Conversation.workspace_id == uuid.UUID(wid)))
    )
    assert (
        account_row(db, acct["id"]).sync_cursor == "demo:6"
        and account_row(db, acct["id"]).credential_id is None
    )


def test_synced_conversations_link_to_known_contacts_and_leads_and_add_one_timeline_entry_each(
    client: TestClient, db: DbSession
) -> None:
    u = make_user(client)
    wid = u["workspace_id"]
    contact = client.post(
        f"/api/v1/workspaces/{wid}/contacts",
        json={"full_name": "Jordan Lee", "email": "jordan@northwind.example"},
    ).json()
    lead = client.post(
        f"/api/v1/workspaces/{wid}/leads",
        json={"title": "Northwind site", "contact_id": contact["id"]},
    ).json()
    acct = client.post(ws_url(wid, "/accounts/demo")).json()
    for _ in range(2):
        assert client.post(ws_url(wid, f"/accounts/{acct['id']}/sync")).status_code == 200
    conv = db.scalar(
        select(Conversation).where(
            Conversation.workspace_id == uuid.UUID(wid),
            Conversation.provider_thread_id == "demo-thread-1",
        )
    )
    assert (
        conv is not None
        and str(conv.lead_id) == lead["id"]
        and str(conv.contact_id) == contact["id"]
    )
    other = db.scalar(
        select(Conversation).where(
            Conversation.workspace_id == uuid.UUID(wid),
            Conversation.provider_thread_id == "demo-thread-2",
        )
    )
    assert (
        other is not None and other.lead_id is None and other.contact_id is None
    )  # no contact for sam@fabrikam
    emails = db.scalars(
        select(Activity).where(Activity.lead_id == uuid.UUID(lead["id"]), Activity.kind == "email")
    ).all()
    assert len(emails) == 2  # one outbound + one inbound, not duplicated by the second sync
    assert any(a.summary.startswith("Email received") for a in emails)
    assert conv.unread is True


def test_accounts_are_workspace_isolated(client: TestClient) -> None:
    a = make_user(client)
    other = second_client(client)
    b = make_user(other)
    acct = client.post(ws_url(a["workspace_id"], "/accounts/demo")).json()
    assert other.get(ws_url(b["workspace_id"], "/accounts")).json() == []
    assert other.get(ws_url(b["workspace_id"], f"/accounts/{acct['id']}")).status_code == 404
    assert other.post(ws_url(b["workspace_id"], f"/accounts/{acct['id']}/sync")).status_code == 404
    assert other.get(ws_url(a["workspace_id"], "/accounts")).status_code == 404


# ----------------------------------------------------------------------------- OAuth connect


def test_connect_flow_creates_a_connected_account_without_exposing_any_token(
    client: TestClient, db: DbSession, caplog: pytest.LogCaptureFixture
) -> None:
    u = make_user(client)
    wid = u["workspace_id"]
    fake = install(client)
    with caplog.at_level(logging.DEBUG):
        res = client.post(ws_url(wid, "/accounts/connect"), json={"provider": "gmail"})
        state = parse_qs(urlparse(res.json()["authorization_url"]).query)["state"][0]
        cb = callback(client, state, code=CODE)
    assert cb.status_code == 303
    location = cb.headers["location"]
    assert location.startswith("/integrations?") and "email=connected" in location
    assert (
        CODE not in location
        and state not in location
        and ACCESS not in location
        and REFRESH not in location
    )
    assert (
        cb.headers["cache-control"] == "no-store" and cb.headers["referrer-policy"] == "no-referrer"
    )

    accounts = client.get(ws_url(wid, "/accounts")).json()
    [acct] = accounts
    assert (
        acct["status"] == "connected"
        and acct["email_address"] == GMAIL_ADDRESS
        and not acct["is_demo"]
    )
    assert (
        acct["granted_scopes"] == list(REQUIRED_SCOPES) and acct["last_health_check_at"] is not None
    )
    server_logs = "\n".join(
        r.getMessage() for r in caplog.records if not r.name.startswith("httpx")
    )  # the test client's own log is the browser side
    everything = res.text + client.get(ws_url(wid, "/accounts")).text + server_logs
    leaked = [
        n
        for n, secret in (
            ("access", ACCESS),
            ("refresh", REFRESH),
            ("code", CODE),
            ("verifier", fake.last_exchange["verifier"]),
        )
        if secret in everything
    ]
    assert leaked == [], server_logs[:800]

    row = account_row(db, acct["id"])
    assert row.credential_id is not None
    stored = store_of(client).get(db, uuid.UUID(wid), row.credential_id)
    assert stored["refresh_token"] == REFRESH and stored["access_token"] == ACCESS
    raw = db.get(CredentialSecret, row.credential_id)
    assert raw is not None and REFRESH.encode() not in bytes(raw.ciphertext)  # encrypted at rest
    for col in (
        "email_address",
        "display_name",
        "provider_account_id",
        "sync_cursor",
        "last_error_code",
    ):
        assert REFRESH not in str(getattr(row, col) or "")
    actions = [
        e.action
        for e in db.scalars(select(AuditEvent).where(AuditEvent.workspace_id == uuid.UUID(wid)))
    ]
    assert "email.connect_started" in actions and "email.account_connected" in actions


def test_pkce_challenge_matches_the_verifier_sent_at_exchange(client: TestClient) -> None:
    u = make_user(client)
    fake = install(client)
    connect_gmail(client, u["workspace_id"], fake)
    verifier = fake.last_exchange["verifier"]
    assert 43 <= len(verifier) <= 128
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    assert fake.last_auth["challenge"] == expected
    assert (
        fake.last_exchange["redirect_uri"]
        == fake.last_auth["redirect_uri"]
        == "http://localhost:3000/api/v1/email/oauth/callback"
    )


def test_state_is_single_use_and_replays_are_rejected(client: TestClient, db: DbSession) -> None:
    u = make_user(client)
    fake = install(client)
    state = start_connect(client, u["workspace_id"])
    assert "email=connected" in callback(client, state, code=CODE).headers["location"]
    replay = callback(client, state, code=CODE)
    assert (
        "email=error" in replay.headers["location"]
        and "reason=invalid_state" in replay.headers["location"]
    )
    assert fake.calls.count("exchange_code") == 1
    assert (
        db.scalars(
            select(CredentialSecret).where(
                CredentialSecret.purpose == "email_oauth_pending",
                CredentialSecret.workspace_id == uuid.UUID(u["workspace_id"]),
            )
        ).all()
        == []
    )


@pytest.mark.parametrize(
    "mangle",
    [
        lambda s: s + "x",
        lambda s: s[:-3],
        lambda s: "garbage",
        lambda s: "",
        lambda s: s.replace(".", ":"),
        lambda s: f"{uuid.uuid4().hex}.{s.split('.', 1)[1]}",
    ],
)
def test_forged_or_tampered_state_never_reaches_the_provider(client: TestClient, mangle) -> None:  # type: ignore[no-untyped-def]
    u = make_user(client)
    fake = install(client)
    state = start_connect(client, u["workspace_id"])
    res = callback(client, mangle(state), code=CODE)
    assert "reason=invalid_state" in res.headers["location"]
    assert "exchange_code" not in fake.calls


def test_state_started_by_one_user_cannot_be_completed_by_another(
    client: TestClient, db: DbSession
) -> None:
    owner = make_user(client)
    fake = install(client)
    state = start_connect(client, owner["workspace_id"])
    attacker = second_client(client)
    make_user(attacker)
    res = callback(attacker, state, code=CODE)
    assert "reason=wrong_user" in res.headers["location"]
    assert "exchange_code" not in fake.calls
    assert client.get(ws_url(owner["workspace_id"], "/accounts")).json() == []
    assert (
        callback(client, state, code=CODE).headers["location"].endswith("reason=invalid_state")
    )  # consumed by the attempt


def test_expired_state_is_rejected(client: TestClient, db: DbSession) -> None:
    u = make_user(client)
    fake = install(client)
    state = start_connect(client, u["workspace_id"])
    cred = db.get(CredentialSecret, uuid.UUID(state.split(".")[1]))
    assert cred is not None
    cred.created_at = datetime.now(UTC) - timedelta(minutes=11)
    db.commit()
    assert "reason=expired" in callback(client, state, code=CODE).headers["location"]
    assert "exchange_code" not in fake.calls


def test_the_callback_requires_a_signed_in_user(client: TestClient) -> None:
    u = make_user(client)
    fake = install(client)
    state = start_connect(client, u["workspace_id"])
    anonymous = second_client(client)
    anonymous.cookies.clear()
    res = callback(anonymous, state, code=CODE)
    assert res.status_code == 303 and "reason=signed_out" in res.headers["location"]
    assert "exchange_code" not in fake.calls


def test_a_member_who_is_not_the_owner_cannot_finish_a_connection(
    client: TestClient, db: DbSession
) -> None:
    owner = make_user(client)
    member = second_client(client)
    m = make_user(member)
    add_member(db, owner["workspace_id"], m["me"]["user"]["id"])
    install(client)
    assert (
        member.post(
            ws_url(owner["workspace_id"], "/accounts/connect"), json={"provider": "gmail"}
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        (lambda f: None, "denied"),
        (
            lambda f: f.exchange.__setitem__(0, tokens(scopes=(REQUIRED_SCOPES[0],))),
            "insufficient_scopes",
        ),
        (lambda f: f.exchange.__setitem__(0, tokens(refresh=None)), "no_refresh_token"),
        (lambda f: f.exchange.__setitem__(0, PermanentError()), "exchange_failed"),
        (lambda f: f.exchange.__setitem__(0, TransientError()), "provider_unavailable"),
        (lambda f: f.profiles.__setitem__(0, PermanentError()), "profile_failed"),
    ],
)
def test_every_failed_connection_is_explained_and_creates_no_account(
    client: TestClient, db: DbSession, setup, reason: str
) -> None:  # type: ignore[no-untyped-def]
    u = make_user(client)
    fake = install(client)
    setup(fake)
    state = start_connect(client, u["workspace_id"])
    params = {"error": "access_denied"} if reason == "denied" else {"code": CODE}
    res = callback(client, state, **params)
    assert (
        f"reason={reason}" in res.headers["location"] and "email=error" in res.headers["location"]
    )
    assert client.get(ws_url(u["workspace_id"], "/accounts")).json() == []
    leftover = db.scalars(
        select(CredentialSecret).where(
            CredentialSecret.workspace_id == uuid.UUID(u["workspace_id"])
        )
    ).all()
    assert leftover == []  # neither the pending record nor any token was kept
    assert "email.connect_failed" in [
        e.action
        for e in db.scalars(
            select(AuditEvent).where(AuditEvent.workspace_id == uuid.UUID(u["workspace_id"]))
        )
    ]
    if reason == "denied":
        assert "exchange_code" not in fake.calls


def test_reconnecting_replaces_the_credentials_and_clears_the_reconnect_state(
    client: TestClient, db: DbSession
) -> None:
    u = make_user(client)
    wid = u["workspace_id"]
    fake = install(client)
    first = connect_gmail(client, wid, fake)
    row = account_row(db, first["id"])
    old_cred = row.credential_id
    row.status, row.last_error_code, row.sync_cursor = "needs_reauth", "access_revoked", "hist:5"
    db.commit()
    fake.exchange[0] = tokens(access="ACCESS-2", refresh="REFRESH-2")
    second = connect_gmail(client, wid, fake)
    assert (
        second["id"] == first["id"]
        and second["status"] == "connected"
        and second["last_error"] is None
    )
    row = account_row(db, first["id"])
    assert row.credential_id != old_cred and row.sync_cursor is None
    assert db.get(CredentialSecret, old_cred) is None
    assert (
        store_of(client).get(db, uuid.UUID(wid), row.credential_id)["refresh_token"] == "REFRESH-2"
    )
    assert len(client.get(ws_url(wid, "/accounts")).json()) == 1


# ----------------------------------------------------------------------------- token refresh and revocation


def test_an_expiring_access_token_is_refreshed_and_the_new_one_is_stored(
    client: TestClient, db: DbSession
) -> None:
    u = make_user(client)
    wid = u["workspace_id"]
    fake = install(client)
    acct = connect_gmail(client, wid, fake)
    row = account_row(db, acct["id"])
    secret = store_of(client).get(db, uuid.UUID(wid), row.credential_id)
    secret["expires_at"] = (
        datetime.now(UTC) + timedelta(seconds=30)
    ).isoformat()  # inside the safety margin
    store_of(client).update(db, uuid.UUID(wid), row.credential_id, secret)
    db.commit()
    fake.syncs = [page()]
    assert client.post(ws_url(wid, f"/accounts/{acct['id']}/sync")).status_code == 200
    assert "refresh" in fake.calls and fake.access_used[-1] == NEW_ACCESS
    db.expire_all()
    stored = store_of(client).get(db, uuid.UUID(wid), row.credential_id)
    assert (
        stored["access_token"] == NEW_ACCESS and stored["refresh_token"] == REFRESH
    )  # refresh token kept


def test_a_fresh_access_token_is_used_without_refreshing(client: TestClient) -> None:
    u = make_user(client)
    fake = install(client)
    acct = connect_gmail(client, u["workspace_id"], fake)
    fake.syncs = [page()]
    client.post(ws_url(u["workspace_id"], f"/accounts/{acct['id']}/sync"))
    assert "refresh" not in fake.calls and fake.access_used[-1] == ACCESS


def test_a_revoked_grant_marks_the_account_reconnect_needed_and_stops_calling_the_provider(
    client: TestClient, db: DbSession
) -> None:
    u = make_user(client)
    wid = u["workspace_id"]
    fake = install(client)
    acct = connect_gmail(client, wid, fake)
    row = account_row(db, acct["id"])
    secret = store_of(client).get(db, uuid.UUID(wid), row.credential_id)
    secret["expires_at"] = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    store_of(client).update(db, uuid.UUID(wid), row.credential_id, secret)
    db.commit()
    fake.refreshes = [AccessRevoked()]
    res = client.post(ws_url(wid, f"/accounts/{acct['id']}/sync"))
    assert res.status_code == 409 and res.json()["error"]["code"] == "reconnect_required"
    shown = client.get(ws_url(wid, f"/accounts/{acct['id']}")).json()
    assert (
        shown["status"] == "needs_reauth"
        and shown["needs_reconnect"]
        and shown["last_error_code"] == "access_revoked"
    )
    assert "Reconnect" in shown["last_error"]
    calls_before = len(fake.calls)
    again = client.post(ws_url(wid, f"/accounts/{acct['id']}/sync"))
    assert (
        again.status_code == 409 and len(fake.calls) == calls_before
    )  # nothing is sent to the provider any more
    assert client.post(ws_url(wid, f"/accounts/{acct['id']}/test")).status_code == 409


def test_a_401_from_the_api_triggers_one_forced_refresh_then_gives_up(
    client: TestClient, db: DbSession
) -> None:
    u = make_user(client)
    wid = u["workspace_id"]
    fake = install(client)
    acct = connect_gmail(client, wid, fake)
    fake.syncs = [AuthExpired(), page(remote("m1"))]
    ok = client.post(ws_url(wid, f"/accounts/{acct['id']}/sync"))
    assert (
        ok.status_code == 200
        and ok.json()["messages_created"] == 1
        and fake.calls.count("refresh") == 1
    )
    fake.syncs = [AuthExpired()]
    bad = client.post(ws_url(wid, f"/accounts/{acct['id']}/sync"))
    assert bad.status_code == 409 and account_row(db, acct["id"]).status == "needs_reauth"


def test_missing_permissions_surface_as_a_reconnect_request(
    client: TestClient, db: DbSession
) -> None:
    u = make_user(client)
    fake = install(client)
    acct = connect_gmail(client, u["workspace_id"], fake)
    fake.syncs = [InsufficientScopes()]
    res = client.post(ws_url(u["workspace_id"], f"/accounts/{acct['id']}/sync"))
    assert (
        res.status_code == 409
        and account_row(db, acct["id"]).last_error_code == "insufficient_scopes"
    )


# ----------------------------------------------------------------------------- sync: pagination, idempotency, limits, errors


def test_sync_pages_are_stored_one_by_one_and_the_cursor_follows_what_was_stored(
    client: TestClient, db: DbSession
) -> None:
    u = make_user(client)
    wid = u["workspace_id"]
    fake = install(client)
    acct = connect_gmail(client, wid, fake)
    fake.syncs = [
        page(
            remote("m1", "t1"),
            remote("m2", "t1", direction="outbound"),
            cursor="full:100:P2",
            done=False,
        ),
        page(remote("m3", "t2"), cursor="hist:100", done=True),
    ]
    res = client.post(ws_url(wid, f"/accounts/{acct['id']}/sync")).json()
    assert (
        res["pages"],
        res["messages_created"],
        res["conversations_created"],
        res["complete"],
    ) == (2, 3, 2, True)
    assert [a["cursor"] for a in fake.sync_args] == [None, "full:100:P2"]
    row = account_row(db, acct["id"])
    assert (
        row.sync_cursor == "hist:100"
        and row.last_synced_at is not None
        and row.status == "connected"
    )
    conv = db.scalar(
        select(Conversation).where(
            Conversation.provider_thread_id == "t1", Conversation.email_account_id == row.id
        )
    )
    assert conv is not None and conv.subject == "Hello" and conv.last_message_at is not None


def test_replaying_the_same_page_never_duplicates_and_updates_changed_fields_only(
    client: TestClient, db: DbSession
) -> None:
    u = make_user(client)
    wid = u["workspace_id"]
    fake = install(client)
    acct = connect_gmail(client, wid, fake)
    fake.syncs = [page(remote("m1"), remote("m2", "t2"))]
    assert client.post(ws_url(wid, f"/accounts/{acct['id']}/sync")).json()["messages_created"] == 2
    again = client.post(ws_url(wid, f"/accounts/{acct['id']}/sync")).json()
    assert (
        again["messages_created"],
        again["messages_updated"],
        again["conversations_created"],
    ) == (0, 0, 0)
    fake.syncs = [page(remote("m1", subject="Edited subject"))]
    changed = client.post(ws_url(wid, f"/accounts/{acct['id']}/sync")).json()
    assert (changed["messages_created"], changed["messages_updated"]) == (0, 1)
    rows = db.scalars(
        select(Message).where(Message.email_account_id == uuid.UUID(acct["id"]))
    ).all()
    assert len(rows) == 2 and {m.subject for m in rows} == {"Edited subject", "Hello"}
    assert all(not m.is_sample for m in rows)  # real provider data is never flagged as demo


def test_the_max_pages_cap_leaves_a_resumable_cursor(client: TestClient, db: DbSession) -> None:
    from app.services import email_accounts as svc

    u = make_user(client)
    wid = u["workspace_id"]
    fake = install(client)
    acct = connect_gmail(client, wid, fake)
    fake.syncs = [
        page(remote(f"m{i}", f"t{i}"), cursor=f"full:100:P{i}", done=False) for i in range(1, 6)
    ]
    summary = svc.sync_account(
        db,
        _ctx(db, wid, u["email"]),
        store_of(client),
        client.app.state.mailbox,
        account_row(db, acct["id"]),
        now=datetime.now(UTC),
        max_pages=2,
    )  # type: ignore[attr-defined]
    assert summary.pages == 2 and not summary.complete
    assert account_row(db, acct["id"]).sync_cursor == "full:100:P2"
    assert db.scalar(select(Conversation).where(Conversation.provider_thread_id == "t3")) is None


def _ctx(db: DbSession, wid: str, email: str):  # type: ignore[no-untyped-def]
    from app.db.models import Membership, User, Workspace
    from app.deps import WorkspaceContext

    user = db.scalar(select(User).where(User.email_normalized == email.lower()))
    ws = db.get(Workspace, uuid.UUID(wid))
    membership = db.scalar(
        select(Membership).where(Membership.workspace_id == ws.id, Membership.user_id == user.id)
    )  # type: ignore[union-attr]
    return WorkspaceContext(user=user, workspace=ws, membership=membership)  # type: ignore[arg-type]


def test_an_expired_history_cursor_restarts_with_a_full_sync(
    client: TestClient, db: DbSession
) -> None:
    u = make_user(client)
    wid = u["workspace_id"]
    fake = install(client)
    acct = connect_gmail(client, wid, fake)
    row = account_row(db, acct["id"])
    row.sync_cursor = "hist:1"
    db.commit()
    fake.syncs = [HistoryExpired(), page(remote("m1"), cursor="hist:300")]
    res = client.post(ws_url(wid, f"/accounts/{acct['id']}/sync"))
    assert res.status_code == 200 and res.json()["messages_created"] == 1
    assert [a["cursor"] for a in fake.sync_args] == ["hist:1", None]
    fake.syncs = [HistoryExpired()]
    row = account_row(db, acct["id"])
    row.sync_cursor = "hist:1"
    db.commit()
    assert (
        client.post(ws_url(wid, f"/accounts/{acct['id']}/sync")).status_code == 502
    )  # a second expiry is a real problem


def test_provider_rate_limits_keep_progress_then_block_calls_until_the_window_passes(
    client: TestClient, db: DbSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    u = make_user(client)
    wid = u["workspace_id"]
    fake = install(client)
    acct = connect_gmail(client, wid, fake)
    start = datetime.now(UTC)
    now_patch(monkeypatch, start)
    fake.syncs = [
        page(remote("m1"), cursor="full:100:P2", done=False),
        RateLimited(retry_after=120),
    ]
    partial = client.post(ws_url(wid, f"/accounts/{acct['id']}/sync"))
    assert (
        partial.status_code == 200
        and partial.json()["error_code"] == "rate_limited"
        and not partial.json()["complete"]
    )
    assert (
        partial.json()["messages_created"] == 1 and partial.json()["rate_limited_until"] is not None
    )
    row = account_row(db, acct["id"])
    assert (
        row.sync_cursor == "full:100:P2" and row.status == "connected"
    )  # progress kept, account not downgraded

    calls = len(fake.calls)
    blocked = client.post(ws_url(wid, f"/accounts/{acct['id']}/sync"))
    assert blocked.status_code == 429 and blocked.json()["error"]["code"] == "rate_limited"
    assert (
        1 <= int(blocked.headers["retry-after"]) <= 121 and len(fake.calls) == calls
    )  # the provider is not called

    now_patch(monkeypatch, start + timedelta(seconds=130))
    fake.syncs = [page(remote("m2", "t2"), cursor="hist:150")]
    resumed = client.post(ws_url(wid, f"/accounts/{acct['id']}/sync"))
    assert (
        resumed.status_code == 200
        and resumed.json()["complete"]
        and resumed.json()["rate_limited_until"] is None
    )
    assert fake.sync_args[-1]["cursor"] == "full:100:P2"


def test_a_rate_limit_on_the_very_first_page_is_a_429_with_retry_after(client: TestClient) -> None:
    u = make_user(client)
    fake = install(client)
    acct = connect_gmail(client, u["workspace_id"], fake)
    fake.syncs = [RateLimited(retry_after=45)]
    res = client.post(ws_url(u["workspace_id"], f"/accounts/{acct['id']}/sync"))
    assert res.status_code == 429 and res.headers["retry-after"] == "45"


def test_transient_provider_failures_never_downgrade_a_working_account(
    client: TestClient, db: DbSession
) -> None:
    u = make_user(client)
    wid = u["workspace_id"]
    fake = install(client)
    acct = connect_gmail(client, wid, fake)
    fake.syncs = [TransientError()]
    res = client.post(ws_url(wid, f"/accounts/{acct['id']}/sync"))
    assert res.status_code == 503 and res.json()["error"]["code"] == "provider_unavailable"
    shown = client.get(ws_url(wid, f"/accounts/{acct['id']}")).json()
    assert (
        shown["status"] == "connected"
        and shown["last_error_code"] == "provider_unavailable"
        and shown["last_error"]
    )
    fake.syncs = [page(remote("m1"), cursor="full:1:P", done=False), TransientError()]
    partial = client.post(ws_url(wid, f"/accounts/{acct['id']}/sync"))
    assert (
        partial.status_code == 200
        and partial.json()["error_code"] == "provider_unavailable"
        and partial.json()["messages_created"] == 1
    )
    fake.syncs = [page(remote("m2"), cursor="hist:2")]
    assert client.post(ws_url(wid, f"/accounts/{acct['id']}/sync")).status_code == 200
    assert (
        client.get(ws_url(wid, f"/accounts/{acct['id']}")).json()["last_error"] is None
    )  # recovery clears the warning


def test_a_permanent_provider_error_is_surfaced_as_a_problem_state(client: TestClient) -> None:
    u = make_user(client)
    fake = install(client)
    acct = connect_gmail(client, u["workspace_id"], fake)
    fake.syncs = [PermanentError()]
    res = client.post(ws_url(u["workspace_id"], f"/accounts/{acct['id']}/sync"))
    assert res.status_code == 502
    shown = client.get(ws_url(u["workspace_id"], f"/accounts/{acct['id']}")).json()
    assert shown["status"] == "error" and shown["last_error_code"] == "provider_rejected"


def test_manual_syncs_are_rate_limited_per_mailbox(client: TestClient) -> None:
    u = make_user(client)
    acct = client.post(ws_url(u["workspace_id"], "/accounts/demo")).json()
    codes = [
        client.post(ws_url(u["workspace_id"], f"/accounts/{acct['id']}/sync")).status_code
        for _ in range(8)
    ]
    assert codes[:6] == [200] * 6 and codes[6:] == [429, 429]


def test_malformed_messages_are_counted_not_stored(client: TestClient) -> None:
    u = make_user(client)
    fake = install(client)
    acct = connect_gmail(client, u["workspace_id"], fake)
    fake.syncs = [page(remote("m1"), skipped=2)]
    res = client.post(ws_url(u["workspace_id"], f"/accounts/{acct['id']}/sync")).json()
    assert res["skipped"] == 2 and res["messages_created"] == 1


# ----------------------------------------------------------------------------- health check and disconnect


def test_test_connection_makes_a_real_call_and_only_then_reports_connected(
    client: TestClient, db: DbSession
) -> None:
    u = make_user(client)
    wid = u["workspace_id"]
    fake = install(client)
    acct = connect_gmail(client, wid, fake)
    before = fake.calls.count("profile")
    fake.profiles = [AccountProfile(GMAIL_ADDRESS, GMAIL_ADDRESS)]
    ok = client.post(ws_url(wid, f"/accounts/{acct['id']}/test")).json()
    assert (
        ok["ok"]
        and ok["account"]["status"] == "connected"
        and fake.calls.count("profile") == before + 1
    )
    fake.profiles = [TransientError()]
    bad = client.post(ws_url(wid, f"/accounts/{acct['id']}/test")).json()
    assert bad["ok"] is False and bad["account"]["last_error_code"] == "provider_unavailable"
    assert bad["account"]["status"] == "connected"  # one failed check is not a disconnect
    fake.profiles = [AccessRevoked()]
    assert client.post(ws_url(wid, f"/accounts/{acct['id']}/test")).status_code == 409
    assert client.get(ws_url(wid, f"/accounts/{acct['id']}")).json()["status"] == "needs_reauth"


def test_the_demo_mailbox_test_never_touches_a_provider(client: TestClient) -> None:
    u = make_user(client)
    fake = install(client)
    acct = client.post(ws_url(u["workspace_id"], "/accounts/demo")).json()
    res = client.post(ws_url(u["workspace_id"], f"/accounts/{acct['id']}/test")).json()
    assert res["ok"] and res["account"]["status"] == "demo" and fake.calls == []


def test_disconnect_revokes_deletes_credentials_and_keeps_the_history(
    client: TestClient, db: DbSession
) -> None:
    u = make_user(client)
    wid = u["workspace_id"]
    fake = install(client)
    acct = connect_gmail(client, wid, fake)
    fake.syncs = [page(remote("m1"))]
    client.post(ws_url(wid, f"/accounts/{acct['id']}/sync"))
    cred_id = account_row(db, acct["id"]).credential_id
    res = client.post(ws_url(wid, f"/accounts/{acct['id']}/disconnect"))
    assert res.status_code == 200 and res.json()["revoked"] is True
    assert fake.revoked_tokens == [REFRESH]  # the long-lived token is the one revoked
    row = account_row(db, acct["id"])
    assert (
        row.status == "disconnected"
        and row.credential_id is None
        and row.sync_cursor is None
        and row.granted_scopes == []
    )
    assert db.get(CredentialSecret, cred_id) is None
    assert db.scalars(
        select(Message).where(Message.email_account_id == row.id)
    ).all()  # history stays
    assert client.post(ws_url(wid, f"/accounts/{acct['id']}/sync")).status_code == 409
    again = client.post(ws_url(wid, f"/accounts/{acct['id']}/disconnect"))
    assert again.status_code == 200  # idempotent
    assert "email.disconnected" in [
        e.action
        for e in db.scalars(select(AuditEvent).where(AuditEvent.workspace_id == uuid.UUID(wid)))
    ]


def test_disconnect_succeeds_locally_even_if_the_provider_cannot_be_reached(
    client: TestClient, db: DbSession
) -> None:
    u = make_user(client)
    wid = u["workspace_id"]
    fake = install(client)
    acct = connect_gmail(client, wid, fake)
    fake.revoke_result = TransientError()
    res = client.post(ws_url(wid, f"/accounts/{acct['id']}/disconnect")).json()
    assert res["revoked"] is False and res["account"]["status"] == "disconnected"
    assert res["account"]["last_error_code"] == "revocation_unconfirmed"
    assert (
        account_row(db, acct["id"]).credential_id is None
    )  # never keep a credential because a provider is down


def test_disconnecting_the_demo_mailbox_keeps_it_usable_and_deletes_nothing(
    client: TestClient, db: DbSession
) -> None:
    u = make_user(client)
    acct = client.post(ws_url(u["workspace_id"], "/accounts/demo")).json()
    res = client.post(ws_url(u["workspace_id"], f"/accounts/{acct['id']}/disconnect")).json()
    assert res["account"]["status"] == "demo" and res["revoked"] is True


def test_real_and_demo_accounts_cannot_be_crossed(client: TestClient, db: DbSession) -> None:
    from app.mailbox.registry import ConnectorRegistry

    u = make_user(client)
    wid = u["workspace_id"]
    fake = install(client)
    acct = connect_gmail(client, wid, fake)
    row = account_row(db, acct["id"])
    row.is_demo = True  # corrupt flag: a real provider account claiming to be demo
    db.commit()
    res = client.post(ws_url(wid, f"/accounts/{acct['id']}/sync"))
    assert res.status_code == 409 and res.json()["error"]["code"] == "provider_mismatch"
    assert fake.calls.count("sync") == 0
    assert isinstance(client.app.state.mailbox, ConnectorRegistry)  # type: ignore[attr-defined]


def test_contacts_and_leads_models_are_untouched_by_a_failed_connect(
    client: TestClient, db: DbSession
) -> None:
    u = make_user(client)
    install(client)
    before = db.scalars(
        select(Contact).where(Contact.workspace_id == uuid.UUID(u["workspace_id"]))
    ).all()
    callback(client, "nope", code=CODE)
    assert (
        db.scalars(
            select(Contact).where(Contact.workspace_id == uuid.UUID(u["workspace_id"]))
        ).all()
        == before
    )
    assert (
        db.scalars(select(Lead).where(Lead.workspace_id == uuid.UUID(u["workspace_id"]))).all()
        == []
    )


def test_access_logs_never_keep_the_oauth_code_or_state() -> None:
    from app.main import RedactOAuthQuery

    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1234", "GET", "/api/v1/email/oauth/callback?state=SECRETSTATE&code=SECRETCODE", "1.1", 303), None,
    )  # fmt: skip
    assert RedactOAuthQuery().filter(record)
    rendered = record.getMessage()
    assert (
        "SECRETSTATE" not in rendered
        and "SECRETCODE" not in rendered
        and "/email/oauth/callback?[redacted]" in rendered
    )
    other = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("c", "GET", "/api/v1/health?x=1", "1.1", 200),
        None,
    )
    RedactOAuthQuery().filter(other)
    assert "x=1" in other.getMessage()


def test_a_flow_cannot_be_finished_by_someone_who_is_no_longer_the_owner(
    client: TestClient, db: DbSession
) -> None:
    from app.db.models import Membership

    u = make_user(client)
    fake = install(client)
    state = start_connect(client, u["workspace_id"])
    membership = db.scalar(
        select(Membership).where(Membership.workspace_id == uuid.UUID(u["workspace_id"]))
    )
    assert membership is not None
    membership.role = "member"  # e.g. their role was reduced while the consent screen was open
    db.commit()
    res = callback(client, state, code=CODE)
    assert "reason=not_allowed" in res.headers["location"] and "exchange_code" not in fake.calls
    assert client.get(ws_url(u["workspace_id"], "/accounts")).json() == []


def test_starting_a_connection_is_rate_limited_and_cleans_up_abandoned_flows(
    client: TestClient, db: DbSession
) -> None:
    u = make_user(client)
    wid = u["workspace_id"]
    install(client)
    stale = store_of(client).put(
        db, uuid.UUID(wid), "email_oauth_pending", {"token": "t", "user_id": "x"}
    )
    row = db.get(CredentialSecret, stale)
    assert row is not None
    row.created_at = datetime.now(UTC) - timedelta(hours=2)
    db.commit()
    first = client.post(ws_url(wid, "/accounts/connect"), json={"provider": "gmail"})
    assert first.status_code == 200
    db.expire_all()
    assert db.get(CredentialSecret, stale) is None  # the abandoned record was purged
    codes = [
        client.post(ws_url(wid, "/accounts/connect"), json={"provider": "gmail"}).status_code
        for _ in range(10)
    ]
    assert codes[:9] == [200] * 9 and codes[9] == 429
    blocked = client.post(ws_url(wid, "/accounts/connect"), json={"provider": "gmail"})
    assert (
        blocked.json()["error"]["code"] == "connect_rate_limited"
        and int(blocked.headers["retry-after"]) > 0
    )


def test_inbound_messages_from_a_real_provider_are_not_labelled_as_unknown_deliveries(
    client: TestClient, db: DbSession
) -> None:
    u = make_user(client)
    fake = install(client)
    acct = connect_gmail(client, u["workspace_id"], fake)
    fake.syncs = [page(remote("m1"), remote("m2", direction="outbound"))]
    client.post(ws_url(u["workspace_id"], f"/accounts/{acct['id']}/sync"))
    states = {
        m.provider_message_id: m.delivery_state
        for m in db.scalars(
            select(Message).where(Message.email_account_id == uuid.UUID(acct["id"]))
        )
    }
    assert states == {"m1": "sent", "m2": "sent"}
