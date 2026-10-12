"""Gmail connector (Gmail API v1 + Google OAuth 2.0 web-server flow with PKCE).

STATUS: implemented from Google's documented endpoints and exercised against simulated responses only. It has NOT been
run against Google: no OAuth client credentials were available, and the official documentation could not be fetched from
the build sandbox, so every endpoint, parameter and error shape here must be re-checked against the current docs before
the first real connection (see docs/EMAIL.md). Nothing in the product says "connected" until a real profile call succeeds.

Scopes (least privilege for read + approved send):
- ``gmail.readonly``: read threads and messages for the inbox. (Restricted scope: needs Google verification for public apps.)
- ``gmail.send``: send messages the user approved. (Sensitive scope.)
Creating drafts inside Gmail would need ``gmail.compose``; it is not requested, so ``create_draft`` is unavailable.

Security: tokens are passed per call and never logged; error messages never include response bodies; redirects are not
followed; ``send`` is never retried automatically.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from app.mailbox import mime
from app.mailbox.errors import (
    AccessRevoked,
    AuthExpired,
    EmailError,
    HistoryExpired,
    InsufficientScopes,
    NotConfigured,
    NotSupported,
    PermanentError,
    RateLimited,
    RemoteNotFound,
    SendOutcomeUnknown,
    TransientError,
)
from app.mailbox.types import (
    AccountProfile,
    AttachmentInfo,
    ConnectorManifest,
    MessageBody,
    OutgoingMessage,
    RemoteMessage,
    ScopeInfo,
    SendResult,
    SyncPage,
    TokenSet,
)

logger = logging.getLogger("freelancer_os.gmail")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://gmail.googleapis.com/gmail/v1/users/me"

SCOPE_READ = "https://www.googleapis.com/auth/gmail.readonly"
SCOPE_SEND = "https://www.googleapis.com/auth/gmail.send"
SCOPE_COMPOSE = "https://www.googleapis.com/auth/gmail.compose"
REQUIRED_SCOPES = (SCOPE_READ, SCOPE_SEND)

MANIFEST = ConnectorManifest(
    key="gmail",
    label="Gmail",
    is_demo=False,
    capabilities=("oauth", "sync", "fetch_body", "send", "health_check", "revoke"),
    scopes=(
        ScopeInfo(
            SCOPE_READ,
            "Read your conversations so replies appear in the inbox. Nothing is changed or deleted.",
        ),
        ScopeInfo(
            SCOPE_SEND,
            "Send only the messages you have approved. Freelancer OS cannot send without your approval.",
        ),
    ),
    setup_doc="docs/EMAIL.md#configure-gmail",
    notes=(
        "Not verified against a live Google account.",
        "Google treats read access to mail as a restricted scope: public apps need Google's verification.",
    ),
)

_RATE_REASONS = {
    "rateLimitExceeded",
    "userRateLimitExceeded",
    "dailyLimitExceeded",
    "quotaExceeded",
    "RATE_LIMIT_EXCEEDED",
}
_SCOPE_REASONS = {"insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}
_MAX_RETRY_WAIT = 10.0
_SKIP_LABELS = {"DRAFT", "CHAT"}


def _reasons(response: httpx.Response) -> tuple[set[str], str]:
    """Machine reasons/status from a Google error body (never the human message)."""
    try:
        err = response.json().get("error", {})
    except (ValueError, AttributeError):
        return set(), ""
    if not isinstance(err, dict):
        return set(), ""
    found: set[str] = set()
    for item in [*err.get("errors", []), *err.get("details", [])]:
        if isinstance(item, dict) and isinstance(item.get("reason"), str):
            found.add(item["reason"])
    status = err.get("status")
    return found, status if isinstance(status, str) else ""


def _retry_after(response: httpx.Response, default: int) -> int:
    raw = response.headers.get("retry-after", "")
    return min(int(raw), 3600) if raw.isdigit() else default


class GmailConnector:
    manifest = MANIFEST

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        max_attempts: int = 3,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._timeout = timeout
        self._http = httpx.Client(transport=transport, follow_redirects=False)
        self._sleep = sleep
        self._now = now
        self._max_attempts = max_attempts

    def __repr__(self) -> str:  # never show the secret
        return f"GmailConnector(client_id={self._client_id!r})"

    def configured(self) -> bool:
        return bool(self._client_id and self._client_secret)

    # ------------------------------------------------------------------ OAuth

    def authorization_url(
        self, *, state: str, redirect_uri: str, code_challenge: str, login_hint: str | None = None
    ) -> str:
        if not self.configured():
            raise NotConfigured()
        params = {
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(REQUIRED_SCOPES),
            "state": state,
            "access_type": "offline",  # ask for a refresh token
            "prompt": "consent",  # make Google return it even if the user connected before
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        if login_hint:
            params["login_hint"] = login_hint
        return f"{AUTH_URL}?{urlencode(params)}"

    def _token_request(self, form: dict[str, str], *, refreshing: bool) -> TokenSet:
        if not self.configured():
            raise NotConfigured()
        form = {**form, "client_id": self._client_id, "client_secret": self._client_secret}
        try:
            response = self._http.post(TOKEN_URL, data=form, timeout=self._timeout)
        except httpx.TimeoutException as exc:
            raise TransientError() from exc
        except httpx.HTTPError as exc:
            raise TransientError() from exc
        if response.status_code >= 500 or response.status_code == 429:
            raise TransientError(retry_after=_retry_after(response, 30))
        if response.status_code != 200:
            try:
                code = str(response.json().get("error", ""))
            except (ValueError, AttributeError):
                code = ""
            if code == "invalid_grant":
                if refreshing:
                    raise AccessRevoked()
                raise PermanentError()  # the authorization code was used, expired or tampered with
            raise PermanentError()
        try:
            data = response.json()
            access = data["access_token"]
            expires_in = int(data.get("expires_in", 3600))
        except (ValueError, KeyError, TypeError) as exc:
            raise PermanentError() from exc
        refresh = data.get("refresh_token")
        scopes = tuple(str(data.get("scope", "")).split())
        return TokenSet(
            access_token=str(access),
            refresh_token=str(refresh) if isinstance(refresh, str) and refresh else None,
            expires_at=self._now() + timedelta(seconds=max(60, expires_in)),
            scopes=scopes,
        )

    def exchange_code(self, *, code: str, redirect_uri: str, code_verifier: str) -> TokenSet:
        return self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
            refreshing=False,
        )

    def refresh(self, refresh_token: str) -> TokenSet:
        return self._token_request(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}, refreshing=True
        )

    def revoke(self, token: str) -> bool:
        try:
            response = self._http.post(REVOKE_URL, data={"token": token}, timeout=self._timeout)
        except httpx.HTTPError:
            return False
        # 200 = revoked. 400 invalid_token = already revoked/expired, which is the state we wanted.
        return response.status_code == 200 or (
            response.status_code == 400 and _reasons_body(response) == "invalid_token"
        )

    # ------------------------------------------------------------------ HTTP

    def _api(
        self,
        method: str,
        path: str,
        access_token: str,
        *,
        params: dict[str, Any] | list[tuple[str, Any]] | None = None,
        body: dict[str, Any] | None = None,
        sending: bool = False,
    ) -> dict[str, Any]:
        """One Gmail API call. Safe requests are retried on 429/5xx/network errors (bounded, honouring Retry-After);
        a send is attempted exactly once."""
        attempts = 1 if sending else self._max_attempts
        last: EmailError | None = None
        for attempt in range(attempts):
            if attempt:
                wait = last.retry_after if last and last.retry_after else 2**attempt * 0.5
                self._sleep(min(float(wait), _MAX_RETRY_WAIT))
            try:
                response = self._http.request(
                    method,
                    f"{API}{path}",
                    params=params,
                    json=body,
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=self._timeout,
                )
            except httpx.TimeoutException as exc:
                if sending:
                    raise SendOutcomeUnknown() from exc
                last = TransientError()
                continue
            except httpx.ConnectError as exc:
                # The request never left: safe to report as a plain failure even for a send.
                last = TransientError()
                if sending:
                    raise last from exc
                continue
            except httpx.HTTPError as exc:
                if sending:
                    raise SendOutcomeUnknown() from exc
                last = TransientError()
                continue
            try:
                return self._interpret(response, sending=sending)
            except (RateLimited, TransientError) as exc:
                last = exc
                if sending or attempt == attempts - 1:
                    raise
        raise last or TransientError()

    def _interpret(self, response: httpx.Response, *, sending: bool) -> dict[str, Any]:
        status = response.status_code
        if 200 <= status < 300:
            if not response.content:
                return {}
            try:
                data = response.json()
            except ValueError as exc:
                if sending:
                    raise SendOutcomeUnknown() from exc
                raise PermanentError() from exc
            if not isinstance(data, dict):
                if sending:
                    raise SendOutcomeUnknown()
                raise PermanentError()
            return data
        reasons, gstatus = _reasons(response)
        if status == 401:
            raise AuthExpired()
        if status == 429 or (
            status == 403 and (reasons & _RATE_REASONS or gstatus == "RESOURCE_EXHAUSTED")
        ):
            daily = bool(reasons & {"dailyLimitExceeded", "quotaExceeded"})
            raise RateLimited(retry_after=_retry_after(response, 3600 if daily else 60))
        if status == 403 and (reasons & _SCOPE_REASONS):
            raise InsufficientScopes()
        if status == 404:
            raise RemoteNotFound()
        if status in (408, 500, 502, 503, 504):
            if sending:
                raise SendOutcomeUnknown()
            raise TransientError(retry_after=_retry_after(response, 0) or None)
        raise PermanentError()

    # ------------------------------------------------------------------ mailbox

    def profile(self, access_token: str) -> AccountProfile:
        data = self._api("GET", "/profile", access_token)
        address = mime.normalize_address(str(data.get("emailAddress", "")))
        if address is None:
            raise PermanentError()
        history = data.get("historyId")
        return AccountProfile(
            account_id=address,
            email_address=address,
            history_marker=str(history) if history is not None else None,
        )

    def sync(
        self, access_token: str, *, cursor: str | None, now: datetime, page_size: int = 25
    ) -> SyncPage:
        profile = self.profile(access_token)  # also the health check; gives us our own address
        kind, parts = _parse_cursor(cursor)
        if kind == "hist":
            return self._sync_history(access_token, profile, parts[0], 0, page_size)
        if kind == "histp":
            return self._sync_history(access_token, profile, parts[0], int(parts[1]), page_size)
        marker = parts[0] if kind == "full" else profile.history_marker
        page_token = parts[1] if kind == "full" and len(parts) > 1 else None
        return self._sync_full(access_token, profile, marker, page_token, page_size)

    def _sync_full(
        self,
        access_token: str,
        profile: AccountProfile,
        marker: str | None,
        page_token: str | None,
        page_size: int,
    ) -> SyncPage:
        params: dict[str, Any] = {"maxResults": page_size}
        if page_token:
            params["pageToken"] = page_token
        listing = self._api("GET", "/threads", access_token, params=params)
        messages: list[RemoteMessage] = []
        skipped = 0
        for thread in listing.get("threads") or []:
            thread_id = thread.get("id") if isinstance(thread, dict) else None
            if not isinstance(thread_id, str):
                skipped += 1
                continue
            try:
                full = self._api(
                    "GET", f"/threads/{thread_id}", access_token, params={"format": "full"}
                )
            except RemoteNotFound:
                skipped += 1
                continue
            for raw in full.get("messages") or []:
                if _is_ignorable(raw):
                    continue
                parsed = _to_remote(raw, profile.email_address)
                if parsed is None:
                    skipped += 1
                else:
                    messages.append(parsed)
        nxt = listing.get("nextPageToken")
        if isinstance(nxt, str) and nxt:
            return SyncPage(tuple(messages), f"full:{marker or ''}:{nxt}", False, skipped)
        return SyncPage(tuple(messages), f"hist:{marker}" if marker else None, True, skipped)

    def _sync_history(
        self, access_token: str, profile: AccountProfile, start: str, offset: int, page_size: int
    ) -> SyncPage:
        ids: list[str] = []
        page_token: str | None = None
        newest = start
        for _ in range(50):  # id-only listing; bounded
            params: dict[str, Any] = {
                "startHistoryId": start,
                "historyTypes": "messageAdded",
                "maxResults": 500,
            }
            if page_token:
                params["pageToken"] = page_token
            try:
                data = self._api("GET", "/history", access_token, params=params)
            except RemoteNotFound as exc:
                raise HistoryExpired() from exc
            for record in data.get("history") or []:
                for added in (record or {}).get("messagesAdded") or []:
                    msg = (added or {}).get("message") or {}
                    mid = msg.get("id")
                    if (
                        isinstance(mid, str)
                        and mid not in ids
                        and not (set(msg.get("labelIds") or []) & _SKIP_LABELS)
                    ):
                        ids.append(mid)
            if data.get("historyId") is not None:
                newest = str(data["historyId"])
            token = data.get("nextPageToken")
            page_token = token if isinstance(token, str) and token else None
            if page_token is None:
                break
        chunk = ids[offset : offset + page_size]
        messages: list[RemoteMessage] = []
        skipped = 0
        for mid in chunk:
            try:
                raw = self._api("GET", f"/messages/{mid}", access_token, params={"format": "full"})
            except RemoteNotFound:
                skipped += 1
                continue
            if _is_ignorable(raw):
                continue
            parsed = _to_remote(raw, profile.email_address)
            if parsed is None:
                skipped += 1
            else:
                messages.append(parsed)
        end = offset + len(chunk)
        if end < len(ids):
            return SyncPage(tuple(messages), f"histp:{start}:{end}", False, skipped)
        return SyncPage(tuple(messages), f"hist:{newest}", True, skipped)

    def fetch_body(self, access_token: str, provider_message_id: str) -> MessageBody:
        raw = self._api(
            "GET", f"/messages/{provider_message_id}", access_token, params={"format": "full"}
        )
        text, html = _bodies(raw.get("payload") or {})
        return MessageBody(text=text or (mime.html_to_text(html) if html else ""), html=html)

    def create_draft(self, access_token: str, message: OutgoingMessage) -> str:
        raise NotSupported()  # would need the gmail.compose scope, which is deliberately not requested

    def send(self, access_token: str, message: OutgoingMessage) -> SendResult:
        try:
            raw = mime.b64url_encode(mime.build_rfc822(message))
        except ValueError as exc:
            raise PermanentError() from exc
        body: dict[str, Any] = {"raw": raw}
        if message.thread_id:
            body["threadId"] = message.thread_id
        data = self._api("POST", "/messages/send", access_token, body=body, sending=True)
        mid, tid = data.get("id"), data.get("threadId")
        if not isinstance(mid, str) or not isinstance(tid, str):
            raise SendOutcomeUnknown()  # a 2xx without an id: do not guess
        return SendResult(provider_message_id=mid, provider_thread_id=tid, delivery_state="sent")


# ---------------------------------------------------------------------- helpers


def _reasons_body(response: httpx.Response) -> str:
    try:
        return str(response.json().get("error", ""))
    except (ValueError, AttributeError):
        return ""


def _parse_cursor(cursor: str | None) -> tuple[str, list[str]]:
    """``(kind, parts)``; anything unrecognised is a request for a full sync."""
    if cursor:
        kind, _, rest = cursor.partition(":")
        if kind == "hist" and rest.isdigit():
            return "hist", [rest]
        if kind == "histp":
            start, _, off = rest.partition(":")
            if start.isdigit() and off.isdigit():
                return "histp", [start, off]
        if kind == "full":
            marker, _, token = rest.partition(":")
            return "full", [marker, token] if token else [marker]
    return "none", []


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for h in payload.get("headers") or []:
        if (
            isinstance(h, dict)
            and isinstance(h.get("name"), str)
            and isinstance(h.get("value"), str)
        ):
            out.setdefault(h["name"].lower(), h["value"])
    return out


def _walk(payload: dict[str, Any]) -> list[dict[str, Any]]:
    stack, out = [payload], []
    while stack:
        part = stack.pop(0)
        if isinstance(part, dict):
            out.append(part)
            stack.extend(part.get("parts") or [])
    return out


def _bodies(payload: dict[str, Any]) -> tuple[str, str | None]:
    text, html = "", None
    for part in _walk(payload):
        data = (part.get("body") or {}).get("data")
        if not isinstance(data, str) or part.get("filename"):
            continue
        try:
            decoded = mime.b64url_decode(data).decode("utf-8", errors="replace")
        except ValueError:
            continue
        if part.get("mimeType") == "text/plain" and not text:
            text = decoded
        elif part.get("mimeType") == "text/html" and html is None:
            html = decoded
    return text, html


def _attachments(payload: dict[str, Any]) -> tuple[AttachmentInfo, ...]:
    out: list[AttachmentInfo] = []
    for part in _walk(payload):
        name = part.get("filename")
        if isinstance(name, str) and name:
            size = (part.get("body") or {}).get("size")
            out.append(
                AttachmentInfo(
                    filename=mime.clean_header(name, 200) or "attachment",
                    mime_type=str(part.get("mimeType") or "application/octet-stream")[:100],
                    size=size if isinstance(size, int) and size >= 0 else None,
                )
            )
    return tuple(out[:20])


def _is_ignorable(raw: Any) -> bool:
    """Drafts and chat messages are not conversations."""
    return isinstance(raw, dict) and bool(set(raw.get("labelIds") or []) & _SKIP_LABELS)


def _to_remote(raw: Any, own_address: str) -> RemoteMessage | None:
    """Normalise a Gmail message, or None when it is malformed (the caller counts it as skipped)."""
    if not isinstance(raw, dict):
        return None
    labels = set(raw.get("labelIds") or [])
    mid, tid = raw.get("id"), raw.get("threadId")
    if not isinstance(mid, str) or not isinstance(tid, str):
        return None
    payload: dict[str, Any] = raw["payload"] if isinstance(raw.get("payload"), dict) else {}
    headers = _headers(payload)
    sender = mime.addresses(headers.get("from"))
    if not sender:
        return None
    sent_at = None
    internal = raw.get("internalDate")
    if isinstance(internal, str) and internal.isdigit():
        sent_at = datetime.fromtimestamp(int(internal) / 1000, tz=UTC)
    sent_at = sent_at or mime.parse_date(headers.get("date"))
    if sent_at is None:
        return None
    outbound = "SENT" in labels or sender[0] == own_address
    snippet = raw.get("snippet")
    return RemoteMessage(
        provider_message_id=mid,
        provider_thread_id=tid,
        direction="outbound" if outbound else "inbound",
        from_address=sender[0],
        to_addresses=mime.addresses(headers.get("to")),
        subject=mime.clean_header(headers.get("subject"), 500),
        snippet=mime.clean_header(snippet, 500) if isinstance(snippet, str) else None,
        sent_at=sent_at,
        attachments=_attachments(payload),
        unread="UNREAD" in labels,
    )


__all__ = ["REQUIRED_SCOPES", "GmailConnector"]
