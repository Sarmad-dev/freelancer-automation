"""The demo mailbox: a local, fictional connector that never touches a network.

It exists so the product can be explored and tested end to end without any real account. Everything it produces is
flagged as a sample, sends are recorded as ``demo`` (never delivered) and no credentials are involved. It shares message
ids with the seed data (``demo-msg-1``, ``demo-msg-2``) so syncing never duplicates seeded rows.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from app.mailbox.errors import NotSupported
from app.mailbox.types import (
    AccountProfile,
    ConnectorManifest,
    MessageBody,
    OutgoingMessage,
    RemoteMessage,
    SendResult,
    SyncPage,
    TokenSet,
)

DEMO_ACCOUNT_ID = "demo-mailbox"
DEMO_ADDRESS = "alex@alex-rivera.example"
DEMO_DISPLAY_NAME = "Alex Rivera (demo)"

MANIFEST = ConnectorManifest(
    key="demo",
    label="Demo mailbox",
    is_demo=True,
    capabilities=("sync", "create_draft", "send_simulated"),
    notes=(
        "Fictional data kept on this server only.",
        "Sending is simulated: nothing is delivered to anyone.",
    ),
)

# (id, thread, direction, counterpart, subject, snippet, hours ago)
_FIXTURES: tuple[tuple[str, str, str, str, str, str, float], ...] = (
    ("demo-msg-1", "demo-thread-1", "outbound", "jordan@northwind.example", "Website rebuild",
     "Hi Jordan, fictional outreach message.", 48),
    ("demo-msg-2", "demo-thread-1", "inbound", "jordan@northwind.example", "Re: Website rebuild",
     "Sounds interesting, can we talk next week? (fictional)", 5),
    ("demo-msg-3", "demo-thread-2", "outbound", "sam@fabrikam.example", "A note about your onboarding flow",
     "Hi Sam, a short fictional introduction.", 30),
    ("demo-msg-4", "demo-thread-2", "inbound", "sam@fabrikam.example", "Re: A note about your onboarding flow",
     "We already have a team for this, thanks. (fictional)", 20),
    ("demo-msg-5", "demo-thread-3", "outbound", "riley@contoso.example", "Quick question",
     "Hi Riley, fictional follow-up.", 72),
    ("demo-msg-6", "demo-thread-3", "inbound", "riley@contoso.example", "Automatic reply: Quick question",
     "I am out of the office until Monday. (fictional)", 71),
)  # fmt: skip


class DemoConnector:
    manifest = MANIFEST

    def configured(self) -> bool:
        return True

    def authorization_url(
        self, *, state: str, redirect_uri: str, code_challenge: str, login_hint: str | None = None
    ) -> str:
        raise NotSupported()

    def exchange_code(self, *, code: str, redirect_uri: str, code_verifier: str) -> TokenSet:
        raise NotSupported()

    def refresh(self, refresh_token: str) -> TokenSet:
        raise NotSupported()

    def revoke(self, token: str) -> bool:
        return True  # nothing was ever issued

    def profile(self, access_token: str) -> AccountProfile:
        return AccountProfile(
            account_id=DEMO_ACCOUNT_ID,
            email_address=DEMO_ADDRESS,
            display_name=DEMO_DISPLAY_NAME,
            history_marker=str(len(_FIXTURES)),
        )

    def sync(
        self, access_token: str, *, cursor: str | None, now: datetime, page_size: int = 25
    ) -> SyncPage:
        start = int(cursor.split(":", 1)[1]) if cursor and cursor.startswith("demo:") else 0
        chunk = _FIXTURES[start : start + page_size]
        messages = tuple(
            RemoteMessage(
                provider_message_id=mid,
                provider_thread_id=thread,
                direction="inbound" if direction == "inbound" else "outbound",
                from_address=other if direction == "inbound" else DEMO_ADDRESS,
                to_addresses=(DEMO_ADDRESS,) if direction == "inbound" else (other,),
                subject=subject,
                snippet=snippet,
                sent_at=now - timedelta(hours=hours),
                unread=direction == "inbound" and hours < 24,
            )
            for mid, thread, direction, other, subject, snippet, hours in chunk
        )
        end = start + len(chunk)
        return SyncPage(messages=messages, cursor=f"demo:{end}", done=end >= len(_FIXTURES))

    def fetch_body(self, access_token: str, provider_message_id: str) -> MessageBody:
        for mid, *_rest, snippet, _hours in _FIXTURES:
            if mid == provider_message_id:
                return MessageBody(text=snippet)
        return MessageBody(text="")

    def create_draft(self, access_token: str, message: OutgoingMessage) -> str:
        return f"demo-draft-{uuid.uuid4().hex[:12]}"

    def send(self, access_token: str, message: OutgoingMessage) -> SendResult:
        """Simulated: records nothing anywhere and reaches no one."""
        return SendResult(
            provider_message_id=f"demo-sent-{uuid.uuid4().hex[:12]}",
            provider_thread_id=message.thread_id or f"demo-thread-{uuid.uuid4().hex[:8]}",
            delivery_state="demo",
        )
