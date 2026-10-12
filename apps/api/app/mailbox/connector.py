"""The interface every email provider implements, so the rest of the product never branches on a provider."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.mailbox.types import (
    AccountProfile,
    ConnectorManifest,
    MessageBody,
    OutgoingMessage,
    SendResult,
    SyncPage,
    TokenSet,
)


class EmailConnector(Protocol):
    manifest: ConnectorManifest

    def configured(self) -> bool:
        """Whether this server has what it needs (client id/secret) to use the provider."""
        ...

    # --- OAuth (providers without OAuth, like the demo, raise NotSupported) ---
    def authorization_url(
        self, *, state: str, redirect_uri: str, code_challenge: str, login_hint: str | None = None
    ) -> str: ...

    def exchange_code(self, *, code: str, redirect_uri: str, code_verifier: str) -> TokenSet: ...

    def refresh(self, refresh_token: str) -> TokenSet: ...

    def revoke(self, token: str) -> bool:
        """Best-effort revocation at the provider. True when the provider confirms the token is dead."""
        ...

    # --- mailbox ---
    def profile(self, access_token: str) -> AccountProfile:
        """Identity + health check: succeeds only if the token really works."""
        ...

    def sync(
        self, access_token: str, *, cursor: str | None, now: datetime, page_size: int = 25
    ) -> SyncPage:
        """One page of changes since ``cursor`` (None = full sync). May raise ``HistoryExpired``."""
        ...

    def fetch_body(self, access_token: str, provider_message_id: str) -> MessageBody: ...

    def create_draft(self, access_token: str, message: OutgoingMessage) -> str:
        """Create a draft in the provider mailbox and return its id."""
        ...

    def send(self, access_token: str, message: OutgoingMessage) -> SendResult:
        """Send ONE approved message. Never retries on its own: an ambiguous failure raises ``SendOutcomeUnknown``."""
        ...
