"""Smaller pieces of the email foundation: address/MIME handling, the credential store's update, Google configuration,
the demo connector and migration 0007."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from email import message_from_bytes

import pytest
from sqlalchemy import inspect
from sqlalchemy.orm import Session as DbSession

from app.config import ConfigError, load_settings
from app.db.models_email import CredentialSecret
from app.mailbox import mime
from app.mailbox.demo import DemoConnector
from app.mailbox.errors import NotSupported
from app.mailbox.types import OutgoingMessage
from app.security.credentials import CredentialError, EncryptedDbCredentialStore
from tests.conftest import make_user

# ----------------------------------------------------------------------------- addresses and MIME


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Jordan@Example.COM", "jordan@example.com"),
        ("Jordan Lee <jordan@example.com>", "jordan@example.com"),
        ("  a@b.example ", "a@b.example"),
        ("a@b.example, c@d.example", None),
        ("a@b.example\nBcc: x@y.example", None),
        ("not an address", None),
        ("", None),
        ("a@", None),
        ("<>", None),
    ],
)
def test_normalize_address_accepts_one_clean_address_only(raw: str, expected: str | None) -> None:
    assert mime.normalize_address(raw) == expected


def test_addresses_parses_lists_dedupes_and_drops_junk() -> None:
    header = (
        'Jordan <Jordan@Example.com>, "Lee, Sam" <sam@example.org>, jordan@example.com, garbage, <>'
    )
    assert mime.addresses(header) == ("jordan@example.com", "sam@example.org")
    assert mime.addresses(None) == () and mime.addresses("") == ()


def test_dates_are_parsed_leniently_into_utc() -> None:
    assert mime.parse_date("Tue, 13 Oct 2026 10:30:00 +0200") == datetime(
        2026, 10, 13, 8, 30, tzinfo=UTC
    )
    assert mime.parse_date("13 Oct 2026 10:30:00 GMT") == datetime(2026, 10, 13, 10, 30, tzinfo=UTC)
    assert mime.parse_date("yesterday-ish") is None and mime.parse_date(None) is None


def test_untrusted_headers_are_flattened_and_capped() -> None:
    assert mime.clean_header("Hello\r\nBcc: x\x00y\x07z", 200) == "Hello Bcc: x y z"
    assert mime.clean_header("x" * 600, 500) == "x" * 500
    assert mime.clean_header("   ", 10) is None and mime.clean_header(None, 10) is None


def test_html_is_reduced_to_text_without_scripts_styles_or_tags() -> None:
    html = "<html><head><title>t</title><style>p{color:red}</style></head><body><p>Hello&nbsp;<b>world</b></p><script>steal()</script><div>Line two</div></body></html>"
    text = mime.html_to_text(html)
    assert "Hello" in text and "world" in text and "Line two" in text
    for bad in ("steal", "color:red", "<", ">", "title"):
        assert bad not in text


def test_outgoing_messages_are_built_with_safe_headers() -> None:
    raw = mime.build_rfc822(
        OutgoingMessage(
            "Me@Example.com",
            "You@Example.org",
            "Hello",
            "Line one\nLine two",
            in_reply_to="<abc@mail.example>",
        )
    )
    parsed = message_from_bytes(raw)
    assert (parsed["From"], parsed["To"], parsed["Subject"]) == (
        "me@example.com",
        "you@example.org",
        "Hello",
    )
    assert (
        parsed["In-Reply-To"] == "<abc@mail.example>"
        and "Line two" in parsed.get_payload(decode=True).decode()
    )
    for bad in (
        OutgoingMessage("me@example.com", "you@example.org", "A\nBcc: x@y.example", "b"),
        OutgoingMessage("me@example.com", "you@example.org\r\nBcc: x@y.example", "s", "b"),
        OutgoingMessage("bad", "you@example.org", "s", "b"),
        OutgoingMessage("me@example.com", "you@example.org", "s", "b", in_reply_to="<a>\r\nX: y"),
    ):
        with pytest.raises(ValueError):
            mime.build_rfc822(bad)


def test_base64url_round_trips_without_padding_trouble() -> None:
    for n in range(0, 12):
        data = bytes(range(n))
        assert mime.b64url_decode(mime.b64url_encode(data).rstrip("=")) == data


# ----------------------------------------------------------------------------- credential store


def test_updating_a_stored_secret_keeps_the_envelope_bound_and_survives_key_rotation(
    client, db: DbSession
) -> None:  # type: ignore[no-untyped-def]
    u = make_user(client)
    wid = uuid.UUID(u["workspace_id"])
    store = EncryptedDbCredentialStore([("v1", "Zm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFyMTI=")])
    cred = store.put(db, wid, "email_oauth", {"access_token": "old", "refresh_token": "r"})
    store.update(db, wid, cred, {"access_token": "new", "refresh_token": "r"})
    db.commit()
    assert store.get(db, wid, cred) == {"access_token": "new", "refresh_token": "r"}
    row = db.get(CredentialSecret, cred)
    assert row is not None and row.rotated_at is not None and b"new" not in bytes(row.ciphertext)
    with pytest.raises(CredentialError):
        store.update(db, wid, cred, {})
    with pytest.raises(CredentialError):
        store.update(db, uuid.uuid4(), cred, {"a": "b"})  # another workspace cannot touch it
    store.delete(db, wid, cred)
    db.commit()


# ----------------------------------------------------------------------------- configuration


def test_google_credentials_must_be_set_together_and_the_default_redirect_points_at_the_web_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_settings()
    assert not settings.gmail_configured
    assert (
        settings.effective_google_redirect_uri
        == "http://localhost:3000/api/v1/email/oauth/callback"
    )
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id.apps.example")
    with pytest.raises(ConfigError, match="set together"):
        load_settings()
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "s" * 24)
    ok = load_settings()
    assert (
        ok.gmail_configured
        and "s" * 24 not in repr(ok)
        and "s" * 24 not in str(ok.google_client_secret)
    )
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "ftp://x.example/cb")
    with pytest.raises(ConfigError, match="GOOGLE_REDIRECT_URI"):
        load_settings()


def test_production_requires_an_https_redirect_uri_when_google_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for k, v in {
        "APP_ENV": "production", "APP_SECRET_KEY": "x" * 48, "CREDENTIAL_ENCRYPTION_KEYS": "v1:" + "A" * 43 + "=",
        "RATE_LIMIT_BACKEND": "redis", "MAIL_BACKEND": "disabled", "AI_PROVIDER": "disabled",
        "GOOGLE_CLIENT_ID": "id", "GOOGLE_CLIENT_SECRET": "s" * 24, "WEB_BASE_URL": "http://app.example",
    }.items():  # fmt: skip
        monkeypatch.setenv(k, v)
    with pytest.raises(ConfigError, match="https"):
        load_settings()
    monkeypatch.setenv("WEB_BASE_URL", "https://app.example")
    assert (
        load_settings().effective_google_redirect_uri
        == "https://app.example/api/v1/email/oauth/callback"
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("EMAIL_SEND_LIMIT_PER_HOUR", "0"),
        ("EMAIL_SYNC_MAX_PAGES", "0"),
        ("EMAIL_HTTP_TIMEOUT_SECONDS", "0"),
    ],
)
def test_email_limits_are_bounded(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ConfigError, match=name):
        load_settings()


# ----------------------------------------------------------------------------- demo connector


def test_the_demo_connector_is_local_deterministic_and_cannot_do_oauth() -> None:
    demo = DemoConnector()
    now = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
    one, two = demo.sync("", cursor=None, now=now), demo.sync("", cursor=None, now=now)
    assert one == two and one.done and one.cursor == "demo:6" and len(one.messages) == 6
    assert all(m.provider_message_id.startswith("demo-") for m in one.messages)
    assert all(
        m.from_address.endswith(".example") or m.to_addresses[0].endswith(".example")
        for m in one.messages
    )
    assert demo.sync("", cursor="demo:6", now=now).messages == ()
    partial = demo.sync("", cursor=None, now=now, page_size=4)
    assert (
        not partial.done
        and partial.cursor == "demo:4"
        and demo.sync("", cursor="demo:4", now=now).done
    )
    with pytest.raises(NotSupported):
        demo.authorization_url(state="s", redirect_uri="r", code_challenge="c")
    with pytest.raises(NotSupported):
        demo.exchange_code(code="c", redirect_uri="r", code_verifier="v")
    sent = demo.send(
        "", OutgoingMessage("alex@alex-rivera.example", "jordan@northwind.example", "s", "b")
    )
    assert sent.delivery_state == "demo" and sent.provider_message_id.startswith("demo-sent-")
    assert demo.configured() and demo.profile("").email_address == "alex@alex-rivera.example"


# ----------------------------------------------------------------------------- migration 0007


def test_0007_adds_and_removes_the_email_columns_and_keeps_one_message_per_draft() -> None:
    from app.db.session import get_engine
    from tests.test_migrations import at_revision

    def cols(table: str) -> set[str]:
        return {c["name"] for c in inspect(get_engine()).get_columns(table)}

    def uniques() -> set[str]:
        return {u["name"] for u in inspect(get_engine()).get_unique_constraints("messages")}

    assert {"last_health_check_at", "rate_limited_until"} <= cols("email_accounts")
    assert {"draft_id", "delivery_error_code"} <= cols(
        "messages"
    ) and "uq_messages_workspace_draft" in uniques()
    with at_revision("0006"):
        assert not ({"last_health_check_at", "rate_limited_until"} & cols("email_accounts"))
        assert (
            not ({"draft_id", "delivery_error_code"} & cols("messages"))
            and "uq_messages_workspace_draft" not in uniques()
        )
        assert {"provider_message_id", "delivery_state"} <= cols(
            "messages"
        )  # nothing else was touched
    assert {"draft_id", "delivery_error_code"} <= cols("messages")
