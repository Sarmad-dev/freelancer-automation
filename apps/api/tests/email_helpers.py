"""Fakes and helpers for the mailbox/draft tests: a scriptable provider and a one-call 'connect Gmail' flow."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.mailbox.demo import DemoConnector
from app.mailbox.errors import EmailError
from app.mailbox.gmail import REQUIRED_SCOPES
from app.mailbox.registry import ConnectorRegistry
from app.mailbox.types import (
    AccountProfile,
    ConnectorManifest,
    MessageBody,
    OutgoingMessage,
    RemoteMessage,
    ScopeInfo,
    SendResult,
    SyncPage,
    TokenSet,
)

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
ACCESS = "ACCESS-TOKEN-SECRET-aaaaaaaa"
REFRESH = "REFRESH-TOKEN-SECRET-bbbbbbbb"
NEW_ACCESS = "NEW-ACCESS-TOKEN-SECRET-cccccccc"
CODE = "AUTH-CODE-dddddddd"
GMAIL_ADDRESS = "me@gmail.example"


def tokens(
    access: str = ACCESS,
    refresh: str | None = REFRESH,
    scopes: tuple[str, ...] = REQUIRED_SCOPES,
    expires_in: int = 3600,
) -> TokenSet:
    return TokenSet(
        access_token=access,
        refresh_token=refresh,
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
        scopes=scopes,
    )


def remote(
    mid: str,
    thread: str = "t1",
    *,
    direction: Literal["inbound", "outbound"] = "inbound",
    other: str = "jordan@northwind.example",
    subject: str | None = "Hello",
    when: datetime = NOW,
    unread: bool = True,
) -> RemoteMessage:
    return RemoteMessage(
        provider_message_id=mid,
        provider_thread_id=thread,
        direction=direction,
        from_address=other if direction == "inbound" else GMAIL_ADDRESS,
        to_addresses=(GMAIL_ADDRESS,) if direction == "inbound" else (other,),
        subject=subject,
        snippet=f"snippet of {mid}",
        sent_at=when,
        unread=unread and direction == "inbound",
    )


class FakeProvider:
    """A scriptable stand-in for a real provider. Each queue is consumed one call at a time; an exception is raised."""

    manifest = ConnectorManifest(
        key="gmail",
        label="Gmail (fake)",
        is_demo=False,
        capabilities=("oauth", "sync", "send"),
        scopes=tuple(ScopeInfo(s, "because") for s in REQUIRED_SCOPES),
    )

    def __init__(self, *, configured: bool = True) -> None:
        self._configured = configured
        self.calls: list[str] = []
        self.exchange: list[TokenSet | Exception] = [tokens()]
        self.refreshes: list[TokenSet | Exception] = [tokens(NEW_ACCESS)]
        self.profiles: list[AccountProfile | Exception] = [
            AccountProfile(GMAIL_ADDRESS, GMAIL_ADDRESS, history_marker="100")
        ]
        self.syncs: list[SyncPage | Exception] = []
        self.sends: list[SendResult | Exception] = []
        self.revoke_result: bool | Exception = True
        self.sync_args: list[dict[str, Any]] = []
        self.sent: list[OutgoingMessage] = []
        self.sent_tokens: list[str] = []
        self.revoked_tokens: list[str] = []
        self.last_auth: dict[str, Any] = {}
        self.last_exchange: dict[str, Any] = {}
        self.access_used: list[str] = []

    def configured(self) -> bool:
        return self._configured

    @staticmethod
    def _next(queue: list[Any]) -> Any:
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    def authorization_url(
        self, *, state: str, redirect_uri: str, code_challenge: str, login_hint: str | None = None
    ) -> str:
        self.calls.append("authorization_url")
        self.last_auth = {"state": state, "redirect_uri": redirect_uri, "challenge": code_challenge}
        return f"https://accounts.example/consent?state={state}&code_challenge={code_challenge}"

    def exchange_code(self, *, code: str, redirect_uri: str, code_verifier: str) -> TokenSet:
        self.calls.append("exchange_code")
        self.last_exchange = {"code": code, "verifier": code_verifier, "redirect_uri": redirect_uri}
        result: TokenSet = self._next(self.exchange)
        return result

    def refresh(self, refresh_token: str) -> TokenSet:
        self.calls.append("refresh")
        result: TokenSet = self._next(self.refreshes)
        return result

    def revoke(self, token: str) -> bool:
        self.calls.append("revoke")
        self.revoked_tokens.append(token)
        if isinstance(self.revoke_result, Exception):
            raise self.revoke_result
        return self.revoke_result

    def profile(self, access_token: str) -> AccountProfile:
        self.calls.append("profile")
        self.access_used.append(access_token)
        result: AccountProfile = self._next(self.profiles)
        return result

    def sync(self, access_token: str, *, cursor: str | None, now: datetime, page_size: int = 25) -> SyncPage:
        self.calls.append("sync")
        self.access_used.append(access_token)
        self.sync_args.append({"cursor": cursor})
        result: SyncPage = self._next(self.syncs)
        return result

    def fetch_body(self, access_token: str, provider_message_id: str) -> MessageBody:
        return MessageBody(text="body")

    def create_draft(self, access_token: str, message: OutgoingMessage) -> str:
        return "draft-1"

    def send(self, access_token: str, message: OutgoingMessage) -> SendResult:
        self.calls.append("send")
        self.sent.append(message)
        self.sent_tokens.append(access_token)
        if not self.sends:
            return SendResult(f"gm-{uuid.uuid4().hex[:8]}", f"gt-{uuid.uuid4().hex[:8]}", "sent")
        result: SendResult = self._next(self.sends)
        return result


def install(client: TestClient, fake: FakeProvider | None = None) -> FakeProvider:
    fake = fake or FakeProvider()
    client.app.state.mailbox = ConnectorRegistry({"demo": DemoConnector(), "gmail": fake})  # type: ignore[attr-defined]
    return fake


def ws_url(wid: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{wid}/email{suffix}"


def start_connect(client: TestClient, wid: str) -> str:
    res = client.post(ws_url(wid, "/accounts/connect"), json={"provider": "gmail"})
    assert res.status_code == 200, res.text
    url = res.json()["authorization_url"]
    return parse_qs(urlparse(url).query)["state"][0]


def callback(client: TestClient, state: str, **params: str) -> Any:
    query = {"state": state, **params}
    return client.get("/api/v1/email/oauth/callback", params=query, follow_redirects=False)


def connect_gmail(client: TestClient, wid: str, fake: FakeProvider) -> dict[str, Any]:
    """Run the whole connect flow through the API and return the new account."""
    state = start_connect(client, wid)
    res = callback(client, state, code=CODE)
    assert res.status_code == 303 and "email=connected" in res.headers["location"], res.headers
    accounts = client.get(ws_url(wid, "/accounts")).json()
    return next(a for a in accounts if a["provider"] == "gmail")
