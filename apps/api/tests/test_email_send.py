"""Drafts and guarded sending: approval bound to the exact text, suppression, idempotency, limits, and every way a send can end."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db.models import AuditEvent
from app.db.models_crm import Activity
from app.db.models_email import Conversation, Draft, EmailAccount, Message
from app.mailbox.errors import (
    AccessRevoked,
    AuthExpired,
    PermanentError,
    RateLimited,
    SendOutcomeUnknown,
    TransientError,
)
from app.mailbox.types import SendResult
from tests.conftest import add_member, make_user, second_client
from tests.email_helpers import ACCESS, NEW_ACCESS, connect_gmail, install, ws_url

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def durl(wid: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{wid}/drafts{suffix}"


def key() -> str:
    return "send-" + uuid.uuid4().hex[:16]


class Env:
    """A signed-in owner with a connected (fake) Gmail mailbox."""

    def __init__(self, client: TestClient, db: DbSession) -> None:
        self.client, self.db = client, db
        self.user = make_user(client)
        self.wid: str = self.user["workspace_id"]
        self.fake = install(client)
        self.account = connect_gmail(client, self.wid, self.fake)

    def draft(self, *, approve: bool = True, to: str = "jordan@northwind.example", subject: str = "Hello Jordan",
              body: str = "A short, honest message.", **extra: Any) -> dict[str, Any]:  # fmt: skip
        res = self.client.post(durl(self.wid), json={"to_address": to, "subject": subject, "body_text": body,
                                                       "email_account_id": self.account["id"], **extra})  # fmt: skip
        assert res.status_code == 201, res.text
        d = res.json()
        if approve:
            a = self.client.post(durl(self.wid, f"/{d['id']}/approve"))
            assert a.status_code == 200, a.text
            d = a.json()
        return d

    def send(self, draft_id: str, k: str | None = None, client: TestClient | None = None) -> Any:
        return (client or self.client).post(
            durl(self.wid, f"/{draft_id}/send"),
            json={"idempotency_key": k if k is not None else key()},
        )

    def suppress(self, email: str) -> None:
        assert self.client.post(
            f"/api/v1/workspaces/{self.wid}/suppressions", json={"email": email}
        ).status_code in (200, 201)

    def audit(self) -> list[AuditEvent]:
        self.db.expire_all()
        return list(
            self.db.scalars(
                select(AuditEvent)
                .where(AuditEvent.workspace_id == uuid.UUID(self.wid))
                .order_by(AuditEvent.created_at)
            )
        )

    def actions(self) -> list[str]:
        return [e.action for e in self.audit()]


@pytest.fixture
def env(client: TestClient, db: DbSession) -> Env:
    return Env(client, db)


# ----------------------------------------------------------------------------- drafts and approval


def test_a_draft_is_normalised_validated_and_starts_unapproved(env: Env) -> None:
    d = env.draft(approve=False, to="  Jordan@Northwind.EXAMPLE ")
    assert (
        d["to_address"] == "jordan@northwind.example"
        and d["status"] == "draft"
        and d["author"] == "user"
    )
    assert d["approval_is_current"] is False and d["send_locked"] is False and d["message"] is None
    bad = env.client.post(
        durl(env.wid), json={"to_address": "not an email", "subject": "s", "body_text": "b"}
    )
    assert bad.status_code == 422 and "to_address" in bad.json()["error"]["fields"]
    for subject in ("Hi\nBcc: x@y.example", "Hi\r\nBcc: x@y.example"):
        flattened = env.client.post(durl(env.wid), json={"subject": subject})
        assert (
            flattened.status_code == 201 and flattened.json()["subject"] == "Hi Bcc: x@y.example"
        )  # one line: no header can start
    assert (
        env.client.post(durl(env.wid), json={"subject": "bell\x07"}).status_code == 422
    )  # control characters are refused
    two = env.client.post(durl(env.wid), json={"to_address": "a@b.example, c@d.example"})
    assert two.status_code == 422  # one recipient per message


def test_approval_needs_a_recipient_subject_and_body(env: Env) -> None:
    d = env.draft(approve=False, to="", subject="", body="")
    res = env.client.post(durl(env.wid, f"/{d['id']}/approve"))
    assert res.status_code == 422
    assert set(res.json()["error"]["fields"]) == {"to_address", "subject", "body_text"}


def test_editing_after_approval_withdraws_it_and_sending_then_needs_a_new_approval(
    env: Env,
) -> None:
    d = env.draft()
    assert d["status"] == "approved" and d["approval_is_current"] and d["approved_at"]
    edited = env.client.patch(
        durl(env.wid, f"/{d['id']}"), json={"body_text": "A sneaky change."}
    ).json()
    assert (
        edited["status"] == "draft"
        and edited["approval_is_current"] is False
        and edited["approved_at"] is None
    )
    assert edited["version"] == d["version"] + 1
    blocked = env.send(d["id"])
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "draft_not_approved"
    assert env.fake.sent == []
    again = env.client.post(durl(env.wid, f"/{d['id']}/approve")).json()
    assert env.send(d["id"]).status_code == 201 and again["approval_is_current"]


def test_a_change_made_behind_the_apis_back_is_caught_at_send_time(env: Env) -> None:
    d = env.draft()
    row = env.db.get(Draft, uuid.UUID(d["id"]))
    assert row is not None
    row.body_text = "Tampered after approval"  # e.g. a bug or a direct database edit
    env.db.commit()
    res = env.send(d["id"])
    assert (
        res.status_code == 409
        and res.json()["error"]["code"] == "draft_changed"
        and env.fake.sent == []
    )
    row.body_text, row.to_address = "A short, honest message.", "someone-else@example.org"
    env.db.commit()
    assert env.send(d["id"]).json()["error"]["code"] == "draft_changed" and env.fake.sent == []


def test_drafts_can_be_listed_filtered_discarded_and_are_workspace_scoped(
    env: Env, client: TestClient
) -> None:
    a, b = env.draft(approve=False), env.draft()
    listing = client.get(durl(env.wid), params={"status": "approved"}).json()
    assert [x["id"] for x in listing["items"]] == [b["id"]] and listing["total"] == 1
    assert client.post(durl(env.wid, f"/{a['id']}/discard")).json()["status"] == "discarded"
    assert env.send(a["id"]).json()["error"]["code"] == "draft_not_approved"
    assert client.patch(durl(env.wid, f"/{a['id']}"), json={"subject": "x"}).status_code == 409
    other = second_client(client)
    o = make_user(other)
    assert other.get(durl(o["workspace_id"])).json()["items"] == []
    assert other.get(durl(o["workspace_id"], f"/{b['id']}")).status_code == 404
    assert (
        other.post(
            durl(o["workspace_id"], f"/{b['id']}/send"), json={"idempotency_key": key()}
        ).status_code
        == 404
    )
    assert (
        other.post(durl(env.wid, f"/{b['id']}/send"), json={"idempotency_key": key()}).status_code
        == 404
    )


def test_only_owners_can_change_drafts_or_send(env: Env, client: TestClient) -> None:
    d = env.draft()
    member = second_client(client)
    m = make_user(member)
    add_member(env.db, env.wid, m["me"]["user"]["id"])
    assert member.get(durl(env.wid, f"/{d['id']}")).status_code == 200
    for method, suffix, body in (("post", "", {"subject": "x"}), ("patch", f"/{d['id']}", {"subject": "x"}), ("post", f"/{d['id']}/approve", None),
                                 ("post", f"/{d['id']}/discard", None), ("post", f"/{d['id']}/send", {"idempotency_key": key()}),
                                 ("post", f"/{d['id']}/resolve-send", {"outcome": "sent"})):  # fmt: skip
        res = getattr(member, method)(
            durl(env.wid, suffix), **({"json": body} if body is not None else {})
        )
        assert res.status_code == 403, (method, suffix)
    assert env.fake.sent == []


# ----------------------------------------------------------------------------- suppression


def test_a_suppressed_recipient_is_never_sent_to_and_the_block_is_audited(env: Env) -> None:
    d = env.draft(to="Jordan@Northwind.example")
    env.suppress("JORDAN@northwind.example")  # added AFTER approval, different case
    res = env.send(d["id"])
    assert res.status_code == 409 and res.json()["error"]["code"] == "recipient_suppressed"
    assert env.fake.sent == [] and "send" not in env.fake.calls
    assert "email.send_blocked" in env.actions()
    row = env.db.get(Draft, uuid.UUID(d["id"]))
    assert row is not None and row.send_idempotency_key is None and row.status == "approved"
    assert (
        env.db.scalars(select(Message).where(Message.draft_id == row.id)).all() == []
    )  # nothing was even queued


def test_removing_the_suppression_makes_the_same_draft_sendable_again(env: Env) -> None:
    d = env.draft()
    entry = env.client.post(
        f"/api/v1/workspaces/{env.wid}/suppressions",
        json={"email": "jordan@northwind.example", "reason": "unsubscribe"},
    ).json()
    assert env.send(d["id"]).status_code == 409
    assert (
        env.client.delete(f"/api/v1/workspaces/{env.wid}/suppressions/{entry['id']}").status_code
        == 204
    )
    assert env.send(d["id"]).status_code == 201 and len(env.fake.sent) == 1


def test_suppression_is_per_workspace(env: Env, client: TestClient) -> None:
    other = second_client(client)
    o = make_user(other)
    other.post(
        f"/api/v1/workspaces/{o['workspace_id']}/suppressions",
        json={"email": "jordan@northwind.example"},
    )
    assert (
        env.send(env.draft()["id"]).status_code == 201
    )  # the other workspace's list does not apply here


def test_suppression_api_is_owner_only_idempotent_and_audits_a_hash_not_the_address(
    env: Env, client: TestClient
) -> None:
    base = f"/api/v1/workspaces/{env.wid}/suppressions"
    first = client.post(
        base, json={"email": "Dana@Example.org", "reason": "complaint", "note": "asked twice"}
    )
    assert first.status_code == 201 and first.json()["email"] == "dana@example.org"
    again = client.post(base, json={"email": "dana@example.org"})
    assert (
        again.status_code == 200
        and again.json()["id"] == first.json()["id"]
        and again.json()["reason"] == "complaint"
    )
    assert client.post(base, json={"email": "nope"}).status_code == 422
    assert client.get(base).json()["total"] == 1
    events = [e for e in env.audit() if e.action.startswith("suppression.")]
    assert events and all(
        "dana" not in json.dumps(e.details) and "@" not in json.dumps(e.details) for e in events
    )
    member = second_client(client)
    m = make_user(member)
    add_member(env.db, env.wid, m["me"]["user"]["id"])
    assert (
        member.get(base).status_code == 200
        and member.post(base, json={"email": "x@y.example"}).status_code == 403
    )
    assert member.delete(f"{base}/{first.json()['id']}").status_code == 403


# ----------------------------------------------------------------------------- idempotency


def test_a_successful_send_is_recorded_audited_and_linked(env: Env) -> None:
    d = env.draft()
    res = env.send(d["id"], "my-key-12345")
    assert res.status_code == 201, res.text
    body = res.json()
    assert (
        body["replayed"] is False and body["draft"]["status"] == "sent" and body["draft"]["sent_at"]
    )
    msg = body["draft"]["message"]
    assert (
        msg["delivery_state"] == "sent"
        and msg["delivery_label"] == "Sent."
        and msg["is_demo"] is False
    )
    assert len(env.fake.sent) == 1 and env.fake.sent_tokens == [ACCESS]
    out = env.fake.sent[0]
    assert (out.to_address, out.subject, out.body_text, out.from_address) == (
        "jordan@northwind.example",
        "Hello Jordan",
        "A short, honest message.",
        "me@gmail.example",
    )
    row = env.db.scalar(select(Message).where(Message.draft_id == uuid.UUID(d["id"])))
    assert (
        row is not None
        and row.direction == "outbound"
        and not row.provider_message_id.startswith("pending:")
    )
    conv = env.db.get(Conversation, row.conversation_id)
    assert conv is not None and not conv.provider_thread_id.startswith(
        "local:"
    )  # replaced by the provider's thread id
    actions = env.actions()
    assert actions.index("email.send_queued") < actions.index("email.sent")
    sent_event = next(e for e in env.audit() if e.action == "email.sent")
    assert (
        sent_event.details == {"provider": "gmail", "state": "sent"}
        and sent_event.target_id == d["id"]
    )


def test_the_same_key_never_sends_twice(env: Env) -> None:
    d = env.draft()
    first = env.send(d["id"], "retry-me-0001")
    again = env.send(d["id"], "retry-me-0001")
    third = env.send(d["id"], "retry-me-0001")
    assert (first.status_code, again.status_code, third.status_code) == (201, 200, 200)
    assert (
        again.json()["replayed"]
        and again.json()["draft"]["message"]["id"] == first.json()["draft"]["message"]["id"]
    )
    assert len(env.fake.sent) == 1
    assert (
        len(env.db.scalars(select(Message).where(Message.draft_id == uuid.UUID(d["id"]))).all())
        == 1
    )


def test_a_different_key_cannot_resend_a_sent_draft_and_a_key_cannot_be_borrowed_by_another_draft(
    env: Env,
) -> None:
    d1, d2 = env.draft(), env.draft(subject="Another")
    assert env.send(d1["id"], "shared-key-001").status_code == 201
    other_key = env.send(d1["id"], "other-key-0002")
    assert other_key.status_code == 409 and other_key.json()["error"]["code"] == "already_sent"
    borrowed = env.send(d2["id"], "shared-key-001")
    assert (
        borrowed.status_code == 409
        and borrowed.json()["error"]["code"] == "idempotency_key_conflict"
    )
    assert len(env.fake.sent) == 1


@pytest.mark.parametrize("bad", ["short", "has spaces in it", "semi;colon-key1", "x" * 101, ""])
def test_malformed_idempotency_keys_are_rejected(env: Env, bad: str) -> None:
    assert env.send(env.draft()["id"], bad).status_code == 422 and env.fake.sent == []


def test_a_double_submit_during_an_in_flight_send_cannot_cause_a_second_send(env: Env) -> None:
    """While the provider call is running, the same key is replayed and a different key is refused."""
    d = env.draft()
    inner: dict[str, Any] = {}

    def slow_send(message: Any) -> SendResult:
        inner["same"] = env.send(d["id"], "double-0000001")  # the "second click" arrives mid-send
        inner["other"] = env.send(d["id"], "double-0000002")
        return SendResult("gm-1", "gt-1", "sent")

    original = env.fake.send
    env.fake.send = lambda token, message: (original(token, message), slow_send(message))[1]  # type: ignore[method-assign]
    first = env.send(d["id"], "double-0000001")
    assert first.status_code == 201 and len(env.fake.sent) == 1
    assert (
        inner["same"].status_code == 200
        and inner["same"].json()["draft"]["message"]["delivery_state"] == "queued"
    )
    assert inner["same"].json()["replayed"] is True
    assert (
        inner["other"].status_code == 409
        and inner["other"].json()["error"]["code"] == "send_in_progress"
    )


# ----------------------------------------------------------------------------- demo mailbox


def test_sending_from_the_demo_mailbox_is_simulated_and_labelled(
    env: Env, client: TestClient
) -> None:
    demo = client.post(ws_url(env.wid, "/accounts/demo")).json()
    d = env.draft(email_account_id=demo["id"])
    res = env.send(d["id"])
    assert res.status_code == 201
    msg = res.json()["draft"]["message"]
    assert (
        msg["delivery_state"] == "demo"
        and "Demo only" in msg["delivery_label"]
        and msg["is_demo"] is True
    )
    assert (
        res.json()["draft"]["status"] == "sent" and env.fake.sent == []
    )  # no real provider was touched
    row = env.db.scalar(select(Message).where(Message.draft_id == uuid.UUID(d["id"])))
    assert row is not None and row.is_sample and row.delivery_state == "demo"
    assert [e.details for e in env.audit() if e.action == "email.sent"] == [
        {"provider": "demo", "state": "demo"}
    ]


def test_a_demo_mailbox_still_obeys_approval_and_suppression(env: Env, client: TestClient) -> None:
    demo = client.post(ws_url(env.wid, "/accounts/demo")).json()
    unapproved = env.draft(approve=False, email_account_id=demo["id"])
    assert env.send(unapproved["id"]).json()["error"]["code"] == "draft_not_approved"
    env.suppress("jordan@northwind.example")
    assert (
        env.send(env.draft(email_account_id=demo["id"])["id"]).json()["error"]["code"]
        == "recipient_suppressed"
    )


# ----------------------------------------------------------------------------- how a send can end


def test_a_provider_rate_limit_fails_the_send_cleanly_and_a_retry_reuses_the_same_message(
    env: Env,
) -> None:
    d = env.draft()
    env.fake.sends = [RateLimited(retry_after=90)]
    res = env.send(d["id"], "rl-key-000001")
    assert (
        res.status_code == 429
        and res.headers["retry-after"] == "90"
        and res.json()["error"]["code"] == "rate_limited"
    )
    shown = env.client.get(durl(env.wid, f"/{d['id']}")).json()
    assert shown["status"] == "approved" and shown["message"]["delivery_state"] == "failed"
    assert (
        shown["message"]["delivery_error_code"] == "rate_limited"
        and "Failed" in shown["message"]["delivery_label"]
    )
    assert shown["send_locked"] is False  # nothing was sent, so it can be retried or edited
    # the mailbox is now in a back-off window
    blocked = env.send(d["id"], "rl-key-000002")
    assert blocked.status_code == 429 and len(env.fake.sent) == 1
    row = env.db.get(EmailAccount, uuid.UUID(env.account["id"]))
    row.rate_limited_until = None  # type: ignore[union-attr]
    env.db.commit()
    env.fake.sends = [SendResult("gm-ok", "gt-ok", "sent")]
    ok = env.send(d["id"], "rl-key-000003")
    assert ok.status_code == 201
    assert (
        len(env.db.scalars(select(Message).where(Message.draft_id == uuid.UUID(d["id"]))).all())
        == 1
    )  # one row, reused


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [(PermanentError(), 502, "provider_rejected"), (TransientError(), 503, "provider_unavailable")],
)
def test_definite_failures_are_reported_and_leave_the_draft_retryable(
    env: Env, error: Exception, status: int, code: str
) -> None:
    d = env.draft()
    env.fake.sends = [error]
    res = env.send(d["id"])
    assert res.status_code == status and res.json()["error"]["code"] == code
    shown = env.client.get(durl(env.wid, f"/{d['id']}")).json()
    assert (
        shown["status"] == "approved"
        and shown["message"]["delivery_state"] == "failed"
        and shown["sent_at"] is None
    )
    assert "email.send_failed" in env.actions() and "email.sent" not in env.actions()
    env.fake.sends = [SendResult("gm-2", "gt-2", "sent")]
    assert env.send(d["id"]).status_code == 201


def test_an_unconfirmed_send_is_recorded_as_unknown_and_never_retried_automatically(
    env: Env,
) -> None:
    d = env.draft()
    env.fake.sends = [SendOutcomeUnknown()]
    res = env.send(d["id"], "unknown-key-001")
    assert res.status_code == 202, res.text
    msg = res.json()["draft"]["message"]
    assert msg["delivery_state"] == "unknown" and "Check your mailbox" in msg["delivery_label"]
    assert (
        res.json()["draft"]["status"] == "approved" and res.json()["draft"]["send_locked"] is True
    )
    # a click-happy retry with the same key just reads the recorded state
    replay = env.send(d["id"], "unknown-key-001")
    assert replay.status_code == 200 and replay.json()["replayed"] and len(env.fake.sent) == 1
    # a new key is refused until a person says what happened
    new_key = env.send(d["id"], "unknown-key-002")
    assert (
        new_key.status_code == 409
        and new_key.json()["error"]["code"] == "send_outcome_unknown"
        and len(env.fake.sent) == 1
    )
    assert env.client.patch(durl(env.wid, f"/{d['id']}"), json={"subject": "x"}).status_code == 409
    assert env.client.post(durl(env.wid, f"/{d['id']}/discard")).status_code == 409
    assert "email.send_unknown" in env.actions()


def test_an_unexpected_crash_after_the_request_left_is_treated_as_unknown_not_failed(
    env: Env,
) -> None:
    d = env.draft()
    env.fake.sends = [RuntimeError("boom with private detail")]
    res = env.send(d["id"])
    assert res.status_code == 202 and res.json()["draft"]["message"]["delivery_state"] == "unknown"
    assert "private detail" not in res.text


def test_resolving_an_unknown_send_as_sent_or_not_sent(env: Env) -> None:
    sent_draft, lost_draft = env.draft(), env.draft(subject="Second")
    env.fake.sends = [SendOutcomeUnknown(), SendOutcomeUnknown()]
    env.send(sent_draft["id"])
    env.send(lost_draft["id"])
    nothing = env.client.post(
        durl(env.wid, f"/{env.draft()['id']}/resolve-send"), json={"outcome": "sent"}
    )
    assert nothing.status_code == 409 and nothing.json()["error"]["code"] == "nothing_to_resolve"
    done = env.client.post(
        durl(env.wid, f"/{sent_draft['id']}/resolve-send"), json={"outcome": "sent"}
    ).json()
    assert (
        done["status"] == "sent"
        and done["message"]["delivery_state"] == "sent"
        and done["send_locked"]
    )
    retry = env.client.post(
        durl(env.wid, f"/{lost_draft['id']}/resolve-send"), json={"outcome": "not_sent"}
    ).json()
    assert (
        retry["message"]["delivery_state"] == "failed"
        and retry["send_locked"] is False
        and retry["status"] == "approved"
    )
    env.fake.sends = [SendResult("gm-3", "gt-3", "sent")]
    assert env.send(lost_draft["id"]).status_code == 201
    assert (
        env.client.post(
            durl(env.wid, f"/{sent_draft['id']}/resolve-send"), json={"outcome": "sent"}
        ).status_code
        == 409
    )
    assert (
        env.client.post(
            durl(env.wid, f"/{lost_draft['id']}/resolve-send"), json={"outcome": "maybe"}
        ).status_code
        == 422
    )


def test_a_revoked_connection_fails_the_send_and_asks_for_a_reconnect(env: Env) -> None:
    d = env.draft()
    env.fake.sends = [AuthExpired()]
    env.fake.refreshes = [AccessRevoked()]
    res = env.send(d["id"])
    assert res.status_code == 409 and res.json()["error"]["code"] == "reconnect_required"
    acct = env.client.get(ws_url(env.wid, f"/accounts/{env.account['id']}")).json()
    assert acct["status"] == "needs_reauth" and acct["needs_reconnect"]
    again = env.send(d["id"])
    assert again.status_code == 409 and again.json()["error"]["code"] == "reconnect_required"
    assert (
        env.client.get(durl(env.wid, f"/{d['id']}")).json()["message"]["delivery_state"] == "failed"
    )
    assert len(env.fake.sent) == 1  # the second attempt never reached the provider


def test_an_expired_access_token_is_refreshed_once_and_the_send_proceeds(env: Env) -> None:
    d = env.draft()
    env.fake.sends = [AuthExpired(), SendResult("gm-9", "gt-9", "sent")]
    res = env.send(d["id"])
    assert res.status_code == 201 and env.fake.calls.count("refresh") == 1
    assert env.fake.sent_tokens == [
        ACCESS,
        NEW_ACCESS,
    ]  # a 401 means "not sent", so the retry cannot duplicate


# ----------------------------------------------------------------------------- limits and mailbox rules


def test_workspace_send_limits_stop_a_burst_before_the_provider_is_called(
    env: Env, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    settings = get_settings().model_copy(update={"email_send_limit_per_hour": 2})
    client.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    codes = [env.send(env.draft(subject=f"S{i}")["id"]).status_code for i in range(4)]
    assert codes == [201, 201, 429, 429] and len(env.fake.sent) == 2
    blocked = env.send(env.draft(subject="S9")["id"])
    assert (
        blocked.json()["error"]["code"] == "send_rate_limited"
        and int(blocked.headers["retry-after"]) > 0
    )
    client.app.dependency_overrides.clear()  # type: ignore[attr-defined]


def test_suppressed_and_unapproved_attempts_do_not_use_up_the_send_quota(
    env: Env, client: TestClient
) -> None:
    from app.config import get_settings

    settings = get_settings().model_copy(update={"email_send_limit_per_hour": 1})
    client.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    env.suppress("blocked@example.org")
    for _ in range(3):
        assert env.send(env.draft(to="blocked@example.org")["id"]).status_code == 409
        assert env.send(env.draft(approve=False)["id"]).status_code == 409
    assert env.send(env.draft()["id"]).status_code == 201
    client.app.dependency_overrides.clear()  # type: ignore[attr-defined]


def test_a_disconnected_mailbox_cannot_send_and_the_draft_stays_unsent(
    env: Env, client: TestClient
) -> None:
    d = env.draft()
    client.post(ws_url(env.wid, f"/accounts/{env.account['id']}/disconnect"))
    res = env.send(d["id"])
    assert res.status_code == 409 and res.json()["error"]["code"] == "reconnect_required"
    assert (
        env.fake.sent == []
        and env.client.get(durl(env.wid, f"/{d['id']}")).json()["message"] is None
    )


def test_the_sending_mailbox_must_be_chosen_when_it_is_ambiguous_or_missing(
    client: TestClient, db: DbSession
) -> None:
    u = make_user(client)
    wid = u["workspace_id"]
    fake = install(client)
    body = {"to_address": "a@b.example", "subject": "s", "body_text": "b"}
    d = client.post(durl(wid), json=body).json()
    client.post(durl(wid, f"/{d['id']}/approve"))
    none = client.post(durl(wid, f"/{d['id']}/send"), json={"idempotency_key": key()})
    assert none.status_code == 422 and none.json()["error"]["code"] == "email_account_required"
    demo = client.post(ws_url(wid, "/accounts/demo")).json()
    assert (
        client.post(durl(wid, f"/{d['id']}/send"), json={"idempotency_key": key()}).status_code
        == 201
    )  # exactly one usable mailbox
    d2 = client.post(durl(wid), json=body).json()
    client.post(durl(wid, f"/{d2['id']}/approve"))
    connect_gmail(client, wid, fake)
    two = client.post(durl(wid, f"/{d2['id']}/send"), json={"idempotency_key": key()})
    assert two.status_code == 422 and two.json()["error"]["code"] == "email_account_required"
    assert demo["id"]


def test_replies_go_out_on_the_conversations_own_mailbox_and_thread(env: Env) -> None:
    fake = env.fake
    from tests.email_helpers import remote
    from tests.test_email_accounts import page

    fake.syncs = [page(remote("m1", "thread-77"))]
    env.client.post(ws_url(env.wid, f"/accounts/{env.account['id']}/sync"))
    conv = env.db.scalar(select(Conversation).where(Conversation.provider_thread_id == "thread-77"))
    assert conv is not None
    d = env.client.post(
        durl(env.wid),
        json={
            "conversation_id": str(conv.id),
            "to_address": "jordan@northwind.example",
            "subject": "Re: Hello",
            "body_text": "Thanks!",
        },
    ).json()
    env.client.post(durl(env.wid, f"/{d['id']}/approve"))
    res = env.send(d["id"])
    assert res.status_code == 201 and fake.sent[-1].thread_id == "thread-77"
    assert res.json()["draft"]["message"]["conversation_id"] == str(conv.id)


def test_sending_records_an_email_entry_on_the_leads_timeline_once(env: Env) -> None:
    lead = env.client.post(
        f"/api/v1/workspaces/{env.wid}/leads", json={"title": "Northwind site"}
    ).json()
    d = env.draft(lead_id=lead["id"])
    env.send(d["id"], "timeline-key-1")
    env.send(d["id"], "timeline-key-1")  # replay
    entries = env.db.scalars(
        select(Activity).where(Activity.lead_id == uuid.UUID(lead["id"]), Activity.kind == "email")
    ).all()
    assert [a.summary for a in entries] == ["Email sent: Hello Jordan"]


def test_audit_events_and_logs_never_contain_addresses_or_message_text(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    d = env.draft(body="Very private body text 7781")
    with caplog.at_level(logging.DEBUG):
        env.send(d["id"])
        env.fake.sends = [SendOutcomeUnknown()]
        env.send(env.draft(subject="Second subject")["id"])
    blob = json.dumps([e.details for e in env.audit()]) + " ".join(
        r.getMessage() for r in caplog.records if not r.name.startswith("httpx")
    )
    for needle in (
        "jordan@northwind.example",
        "private body text",
        "Hello Jordan",
        "Second subject",
        ACCESS,
    ):
        assert needle not in blob
    assert {"email.send_queued", "email.sent", "email.send_unknown"} <= set(env.actions())
