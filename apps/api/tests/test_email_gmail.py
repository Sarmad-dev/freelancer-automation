"""The Gmail connector against simulated Google responses. This is the whole of its verification: no real account or
OAuth client was available, so request shapes follow Google's documented API and must be re-checked against the live docs."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from email import message_from_bytes
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.mailbox import mime
from app.mailbox.errors import (
    AccessRevoked,
    AuthExpired,
    HistoryExpired,
    InsufficientScopes,
    NotConfigured,
    NotSupported,
    PermanentError,
    RateLimited,
    SendOutcomeUnknown,
    TransientError,
)
from app.mailbox.gmail import REQUIRED_SCOPES, GmailConnector
from app.mailbox.types import OutgoingMessage

SECRET = "client-secret-xyz-123456"
TOKEN = "ya29.ACCESS-TOKEN-VALUE"
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def gmail(handler: Any, **kw: Any) -> tuple[GmailConnector, list[httpx.Request], list[float]]:
    seen: list[httpx.Request] = []
    sleeps: list[float] = []

    def wrapped(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        out = handler(req)
        if isinstance(out, Exception):
            raise out
        return out

    connector = GmailConnector(
        client_id="client-id-1",
        client_secret=SECRET,
        transport=httpx.MockTransport(wrapped),
        sleep=sleeps.append,
        now=lambda: NOW,
        **kw,
    )
    return connector, seen, sleeps


def err(
    status: int, reason: str = "", *, headers: dict[str, str] | None = None, gstatus: str = ""
) -> httpx.Response:
    body = {"error": {"code": status, "message": "HUMAN TEXT with private detail", "status": gstatus,
                      "errors": [{"reason": reason}] if reason else []}}  # fmt: skip
    return httpx.Response(status, json=body, headers=headers)


def message(mid: str, thread: str = "t1", *, frm: str = "Jordan <jordan@northwind.example>", labels: list[str] | None = None,
            date_ms: str = "1760000000000", parts: list[dict[str, Any]] | None = None, subject: str = "Hi") -> dict[str, Any]:  # fmt: skip
    return {
        "id": mid,
        "threadId": thread,
        "labelIds": labels if labels is not None else ["INBOX", "UNREAD"],
        "snippet": "A short preview",
        "internalDate": date_ms,
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "From", "value": frm},
                {"name": "To", "value": "Me <me@gmail.example>"},
                {"name": "Subject", "value": subject},
            ],
            "parts": parts or [],
        },
    }


# ----------------------------------------------------------------------------- OAuth


def test_authorization_url_uses_pkce_offline_access_minimal_scopes_and_no_secret() -> None:
    connector, _, _ = gmail(lambda r: httpx.Response(200))
    url = connector.authorization_url(
        state="STATE1",
        redirect_uri="https://app.example/cb",
        code_challenge="CHAL",
        login_hint="a@b.example",
    )
    parsed = urlparse(url)
    q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    assert (
        f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        == "https://accounts.google.com/o/oauth2/v2/auth"
    )
    assert (
        q["client_id"] == "client-id-1" and q["response_type"] == "code" and q["state"] == "STATE1"
    )
    assert q["redirect_uri"] == "https://app.example/cb"
    assert q["code_challenge"] == "CHAL" and q["code_challenge_method"] == "S256"
    assert (
        q["access_type"] == "offline"
        and q["prompt"] == "consent"
        and q["login_hint"] == "a@b.example"
    )
    assert q["scope"].split() == list(REQUIRED_SCOPES)
    assert not any(
        "compose" in s or "modify" in s or "mail.google.com" in s for s in q["scope"].split()
    )
    assert SECRET not in url


def test_an_unconfigured_connector_refuses_everything_that_needs_credentials() -> None:
    c = GmailConnector(client_id="", client_secret="")
    assert not c.configured()
    with pytest.raises(NotConfigured):
        c.authorization_url(state="s", redirect_uri="r", code_challenge="c")
    with pytest.raises(NotConfigured):
        c.exchange_code(code="c", redirect_uri="r", code_verifier="v")
    with pytest.raises(NotConfigured):
        c.refresh("rt")


def test_code_exchange_posts_the_verifier_and_secret_in_the_body_only() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": TOKEN, "expires_in": 3599, "refresh_token": "1//RT",
                                         "scope": " ".join(REQUIRED_SCOPES), "token_type": "Bearer"})  # fmt: skip

    connector, seen, _ = gmail(handler)
    result = connector.exchange_code(
        code="CODE", redirect_uri="https://app.example/cb", code_verifier="VERIFIER"
    )
    req = seen[0]
    assert str(req.url) == "https://oauth2.googleapis.com/token" and req.method == "POST"
    form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
    assert (
        form["grant_type"] == "authorization_code"
        and form["code"] == "CODE"
        and form["code_verifier"] == "VERIFIER"
    )
    assert form["client_secret"] == SECRET and form["client_id"] == "client-id-1"
    assert SECRET not in str(req.url)
    assert result.access_token == TOKEN and result.refresh_token == "1//RT"
    assert result.scopes == REQUIRED_SCOPES and result.expires_at == datetime(
        2026, 10, 12, 12, 59, 59, tzinfo=UTC
    )


def test_token_errors_map_to_actionable_exceptions() -> None:
    bad_code, _, _ = gmail(
        lambda r: httpx.Response(
            400, json={"error": "invalid_grant", "error_description": "Bad code"}
        )
    )
    with pytest.raises(PermanentError):
        bad_code.exchange_code(code="x", redirect_uri="r", code_verifier="v")
    with pytest.raises(AccessRevoked):  # the same error while REFRESHING means the grant is gone
        bad_code.refresh("rt")
    client_bad, _, _ = gmail(lambda r: httpx.Response(401, json={"error": "invalid_client"}))
    with pytest.raises(PermanentError):
        client_bad.refresh("rt")
    down, _, _ = gmail(lambda r: httpx.Response(503))
    with pytest.raises(TransientError):
        down.refresh("rt")
    net, _, _ = gmail(lambda r: httpx.ConnectError("refused"))
    with pytest.raises(TransientError):
        net.refresh("rt")
    junk, _, _ = gmail(lambda r: httpx.Response(200, json={"nothing": "useful"}))
    with pytest.raises(PermanentError):
        junk.refresh("rt")


def test_refresh_returns_a_new_access_token_and_keeps_scopes() -> None:
    connector, seen, _ = gmail(
        lambda r: httpx.Response(
            200,
            json={"access_token": "NEW", "expires_in": 3600, "scope": " ".join(REQUIRED_SCOPES)},
        )
    )
    result = connector.refresh("RT-1")
    form = parse_qs(seen[0].content.decode())
    assert form["grant_type"] == ["refresh_token"] and form["refresh_token"] == ["RT-1"]
    assert result.access_token == "NEW" and result.refresh_token is None


def test_revoke_sends_the_token_in_the_body_and_treats_already_revoked_as_success() -> None:
    ok, seen, _ = gmail(lambda r: httpx.Response(200))
    assert ok.revoke("RT-1") is True
    assert str(seen[0].url) == "https://oauth2.googleapis.com/revoke" and "RT-1" not in str(
        seen[0].url
    )
    assert parse_qs(seen[0].content.decode()) == {"token": ["RT-1"]}
    gone, _, _ = gmail(lambda r: httpx.Response(400, json={"error": "invalid_token"}))
    assert gone.revoke("RT-1") is True
    broken, _, _ = gmail(lambda r: httpx.Response(500))
    assert broken.revoke("RT-1") is False
    offline, _, _ = gmail(lambda r: httpx.ConnectError("down"))
    assert offline.revoke("RT-1") is False


# ----------------------------------------------------------------------------- API errors and retries


def test_profile_success_and_bearer_header() -> None:
    connector, seen, _ = gmail(
        lambda r: httpx.Response(200, json={"emailAddress": "Me@Gmail.Example", "historyId": "777"})
    )
    profile = connector.profile(TOKEN)
    assert profile.email_address == "me@gmail.example" and profile.account_id == "me@gmail.example"
    assert profile.history_marker == "777"
    assert seen[0].headers["authorization"] == f"Bearer {TOKEN}"
    assert str(seen[0].url) == "https://gmail.googleapis.com/gmail/v1/users/me/profile"


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (err(401), AuthExpired),
        (err(403, "insufficientPermissions"), InsufficientScopes),
        (err(403, "rateLimitExceeded"), RateLimited),
        (err(403, "userRateLimitExceeded"), RateLimited),
        (err(429), RateLimited),
        (err(403, "dailyLimitExceeded"), RateLimited),
        (err(400), PermanentError),
        (err(403, "somethingElse"), PermanentError),
        (httpx.Response(200, text="<html>"), PermanentError),
        (httpx.Response(200, json={"emailAddress": "not an address"}), PermanentError),
    ],
)
def test_error_responses_map_to_stable_exceptions_without_leaking_provider_text(
    response: httpx.Response, error: type[Exception]
) -> None:
    connector, _, _ = gmail(lambda r: response, max_attempts=1)
    with pytest.raises(error) as exc:
        connector.profile(TOKEN)
    assert "private detail" not in str(exc.value) and TOKEN not in str(exc.value)


def test_safe_requests_retry_transient_failures_with_backoff_and_retry_after_then_give_up() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return (
            err(503)
            if calls["n"] < 3
            else httpx.Response(200, json={"emailAddress": "me@gmail.example"})
        )

    connector, _, sleeps = gmail(handler, max_attempts=3)
    assert connector.profile(TOKEN).email_address == "me@gmail.example"
    assert calls["n"] == 3 and len(sleeps) == 2 and all(0 < s <= 10 for s in sleeps)

    always_limited, seen, sleeps2 = gmail(
        lambda r: err(429, headers={"retry-after": "500"}), max_attempts=3
    )
    with pytest.raises(RateLimited) as exc:
        always_limited.profile(TOKEN)
    assert (
        len(seen) == 3 and exc.value.retry_after == 500 and max(sleeps2) == 10
    )  # sleeps are capped, the hint is reported

    timeouts, seen3, _ = gmail(lambda r: httpx.ReadTimeout("slow", request=r), max_attempts=2)
    with pytest.raises(TransientError):
        timeouts.profile(TOKEN)
    assert len(seen3) == 2


# ----------------------------------------------------------------------------- sync


def test_full_sync_pages_through_threads_and_normalises_messages() -> None:
    sent = message("m2", frm="Me <me@gmail.example>", labels=["SENT"], date_ms="1760000100000")
    inbound = message(
        "m1",
        parts=[
            {"mimeType": "text/plain", "body": {"size": 10, "data": b64("hello")}},
            {
                "mimeType": "application/pdf",
                "filename": "proposal.pdf",
                "body": {"size": 2048, "attachmentId": "a1"},
            },
        ],
    )

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        q = dict(req.url.params)
        if path.endswith("/profile"):
            return httpx.Response(
                200, json={"emailAddress": "me@gmail.example", "historyId": "500"}
            )
        if path.endswith("/threads"):
            if q.get("pageToken") == "P2":
                return httpx.Response(200, json={"threads": [{"id": "t2"}]})
            return httpx.Response(200, json={"threads": [{"id": "t1"}], "nextPageToken": "P2"})
        if path.endswith("/threads/t1"):
            assert q["format"] == "full"
            return httpx.Response(
                200,
                json={
                    "id": "t1",
                    "messages": [inbound, {"id": "bad"}, message("d1", labels=["DRAFT"])],
                },
            )
        if path.endswith("/threads/t2"):
            return httpx.Response(200, json={"id": "t2", "messages": [sent]})
        raise AssertionError(path)

    connector, _, _ = gmail(handler)
    first = connector.sync(TOKEN, cursor=None, now=NOW)
    assert (
        not first.done and first.cursor == "full:500:P2" and first.skipped == 1
    )  # the malformed one; the draft is ignored
    [m] = first.messages
    assert (m.provider_message_id, m.provider_thread_id, m.direction) == ("m1", "t1", "inbound")
    assert (
        m.from_address == "jordan@northwind.example"
        and m.to_addresses == ("me@gmail.example",)
        and m.unread
    )
    assert m.subject == "Hi" and m.snippet == "A short preview"
    assert (
        m.body_text == "hello" and m.body_html is None
    )  # bodies are carried so the inbox can store the cleaned copy
    assert m.sent_at == datetime.fromtimestamp(1760000000, tz=UTC)
    assert [(a.filename, a.mime_type, a.size) for a in m.attachments] == [
        ("proposal.pdf", "application/pdf", 2048)
    ]

    second = connector.sync(TOKEN, cursor=first.cursor, now=NOW)
    assert second.done and second.cursor == "hist:500"
    assert [(x.provider_message_id, x.direction) for x in second.messages] == [("m2", "outbound")]


def test_incremental_sync_reads_history_dedupes_ids_and_resumes_by_offset() -> None:
    fetched: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        q = dict(req.url.params)
        if path.endswith("/profile"):
            return httpx.Response(
                200, json={"emailAddress": "me@gmail.example", "historyId": "900"}
            )
        if path.endswith("/history"):
            assert q["startHistoryId"] == "500" and q["historyTypes"] == "messageAdded"
            if q.get("pageToken") == "H2":
                return httpx.Response(200, json={"history": [{"messagesAdded": [{"message": {"id": "m3", "labelIds": ["INBOX"]}},
                                                                                {"message": {"id": "m1"}}]}], "historyId": "950"})  # fmt: skip
            return httpx.Response(200, json={"history": [{"messagesAdded": [{"message": {"id": "m1"}}, {"message": {"id": "m2"}},
                                                                            {"message": {"id": "dr", "labelIds": ["DRAFT"]}}]}],
                                             "historyId": "930", "nextPageToken": "H2"})  # fmt: skip
        if "/messages/" in path:
            mid = path.rsplit("/", 1)[1]
            fetched.append(mid)
            if mid == "m2":
                return err(404)
            return httpx.Response(200, json=message(mid, "tX"))
        raise AssertionError(path)

    connector, _, _ = gmail(handler)
    first = connector.sync(TOKEN, cursor="hist:500", now=NOW, page_size=2)
    assert (
        not first.done and first.cursor == "histp:500:2" and first.skipped == 1
    )  # m2 vanished (404)
    assert [m.provider_message_id for m in first.messages] == ["m1"] and fetched == ["m1", "m2"]
    second = connector.sync(TOKEN, cursor=first.cursor, now=NOW, page_size=2)
    assert second.done and second.cursor == "hist:950"
    assert [m.provider_message_id for m in second.messages] == ["m3"]


def test_a_stale_history_cursor_asks_for_a_full_sync() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(200, json={"emailAddress": "me@gmail.example", "historyId": "1"})
            if req.url.path.endswith("/profile")
            else err(404)
        )

    connector, _, _ = gmail(handler)
    with pytest.raises(HistoryExpired):
        connector.sync(TOKEN, cursor="hist:1", now=NOW)


def test_garbage_cursors_fall_back_to_a_full_sync() -> None:
    paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        if req.url.path.endswith("/profile"):
            return httpx.Response(200, json={"emailAddress": "me@gmail.example", "historyId": "42"})
        return httpx.Response(200, json={"threads": []})

    connector, _, _ = gmail(handler)
    for cursor in ("junk", "hist:abc", "histp:1", "demo:5", ""):
        page = connector.sync(TOKEN, cursor=cursor, now=NOW)
        assert page.done and page.cursor == "hist:42"
    assert not any("/history" in p for p in paths)


# ----------------------------------------------------------------------------- bodies, drafts, sending


def test_fetch_body_prefers_plain_text_and_falls_back_to_stripped_html() -> None:
    multi = message("m1", parts=[
        {"mimeType": "text/plain", "body": {"data": b64("Plain version")}},
        {"mimeType": "text/html", "body": {"data": b64("<p>HTML <b>version</b></p>")}},
    ])  # fmt: skip
    html_only = message(
        "m2",
        parts=[
            {
                "mimeType": "text/html",
                "body": {
                    "data": b64("<style>x{}</style><p>Hello&nbsp;there</p><script>evil()</script>")
                },
            }
        ],
    )
    bodies = {"m1": multi, "m2": html_only}
    connector, _, _ = gmail(
        lambda r: httpx.Response(200, json=bodies[r.url.path.rsplit("/", 1)[1]])
    )
    one = connector.fetch_body(TOKEN, "m1")
    assert one.text == "Plain version" and one.html == "<p>HTML <b>version</b></p>"
    two = connector.fetch_body(TOKEN, "m2")
    assert "Hello" in two.text and "evil" not in two.text and "x{}" not in two.text


def test_send_builds_a_safe_rfc822_message_and_posts_it_once() -> None:
    connector, seen, _ = gmail(
        lambda r: httpx.Response(200, json={"id": "sent-1", "threadId": "thr-1"})
    )
    result = connector.send(
        TOKEN,
        OutgoingMessage(
            from_address="me@gmail.example",
            to_address="Jordan@Northwind.Example",
            subject="Hello ünïcode",
            body_text="Body line\nSecond line",
            thread_id="thr-0",
        ),
    )
    assert (result.provider_message_id, result.provider_thread_id, result.delivery_state) == (
        "sent-1",
        "thr-1",
        "sent",
    )
    assert (
        len(seen) == 1
        and str(seen[0].url).endswith("/messages/send")
        and seen[0].headers["authorization"] == f"Bearer {TOKEN}"
    )
    body = json.loads(seen[0].content)
    assert body["threadId"] == "thr-0"
    parsed = message_from_bytes(mime.b64url_decode(body["raw"]))
    assert parsed["To"] == "jordan@northwind.example" and parsed["From"] == "me@gmail.example"
    assert parsed["Subject"] in (
        "Hello ünïcode",
        "=?utf-8?b?SGVsbG8gw7xuw69jb2Rl?=",
    ) or "Hello" in str(parsed["Subject"])
    assert "Body line" in parsed.get_payload(decode=True).decode()


@pytest.mark.parametrize(
    "outgoing",
    [
        OutgoingMessage("me@gmail.example", "a@b.example", "Hi\nBcc: victim@example.com", "x"),
        OutgoingMessage("me@gmail.example", "a@b.example\nBcc: v@example.com", "Hi", "x"),
        OutgoingMessage("me@gmail.example", "not-an-address", "Hi", "x"),
        OutgoingMessage("me@gmail.example", "a@b.example, c@d.example", "Hi", "x"),
        OutgoingMessage(
            "me@gmail.example", "a@b.example", "Hi", "x", in_reply_to="<a@b>\nBcc: x@y.example"
        ),
    ],
)
def test_header_injection_and_bad_addresses_are_refused_before_any_request(
    outgoing: OutgoingMessage,
) -> None:
    connector, seen, _ = gmail(lambda r: httpx.Response(200, json={"id": "x", "threadId": "y"}))
    with pytest.raises(PermanentError):
        connector.send(TOKEN, outgoing)
    assert seen == []


@pytest.mark.parametrize(
    ("handler", "error"),
    [
        (lambda r: httpx.ReadTimeout("slow", request=r), SendOutcomeUnknown),
        (lambda r: httpx.ReadError("reset", request=r), SendOutcomeUnknown),
        (lambda r: err(500), SendOutcomeUnknown),
        (lambda r: err(503), SendOutcomeUnknown),
        (lambda r: httpx.Response(200, text="not json"), SendOutcomeUnknown),
        (lambda r: httpx.Response(200, json={"id": 5}), SendOutcomeUnknown),
        (lambda r: httpx.ConnectError("refused"), TransientError),  # the request never left
        (lambda r: err(429, headers={"retry-after": "30"}), RateLimited),
        (lambda r: err(401), AuthExpired),
        (lambda r: err(400), PermanentError),
    ],
)
def test_a_send_is_attempted_exactly_once_and_ambiguity_is_never_hidden(
    handler: Any, error: type[Exception]
) -> None:
    connector, seen, sleeps = gmail(handler, max_attempts=5)
    with pytest.raises(error):
        connector.send(TOKEN, OutgoingMessage("me@gmail.example", "a@b.example", "Hi", "x"))
    assert len(seen) <= 1 and sleeps == []


def test_creating_provider_drafts_is_not_offered_without_the_compose_scope() -> None:
    connector, _, _ = gmail(lambda r: httpx.Response(200))
    with pytest.raises(NotSupported):
        connector.create_draft(TOKEN, OutgoingMessage("a@b.example", "c@d.example", "s", "b"))
    assert "create_draft" not in connector.manifest.capabilities


def test_redirects_are_not_followed_and_secrets_stay_out_of_repr() -> None:
    connector, seen, _ = gmail(
        lambda r: httpx.Response(302, headers={"location": "https://evil.example/steal"}),
        max_attempts=1,
    )
    with pytest.raises(PermanentError):
        connector.profile(TOKEN)
    assert len(seen) == 1
    assert SECRET not in repr(connector) and SECRET not in str(connector)
