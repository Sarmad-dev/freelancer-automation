"""Normalised data exchanged with connectors. No provider-specific shapes leak past a connector."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class AuthorizationStart:
    url: str


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_at: datetime
    scopes: tuple[str, ...]


@dataclass(frozen=True)
class AccountProfile:
    """Who the token belongs to, and the provider's current position (used as the first sync cursor)."""

    account_id: str
    email_address: str
    display_name: str | None = None
    history_marker: str | None = None


@dataclass(frozen=True)
class AttachmentInfo:
    filename: str
    mime_type: str
    size: int | None = None


@dataclass(frozen=True)
class RemoteMessage:
    provider_message_id: str
    provider_thread_id: str
    direction: Literal["inbound", "outbound"]
    from_address: str
    to_addresses: tuple[str, ...]
    subject: str | None
    snippet: str | None
    sent_at: datetime
    attachments: tuple[AttachmentInfo, ...] = ()
    unread: bool = False


@dataclass(frozen=True)
class SyncPage:
    messages: tuple[RemoteMessage, ...]
    # Opaque cursor to persist after this page is stored (progress marker or the next incremental position).
    cursor: str | None
    done: bool
    skipped: int = 0


@dataclass(frozen=True)
class MessageBody:
    """Fetched on demand and never stored by the framework (retention is decided with the inbox, Prompt 10)."""

    text: str
    html: str | None = None


@dataclass(frozen=True)
class OutgoingMessage:
    from_address: str
    to_address: str
    subject: str
    body_text: str
    thread_id: str | None = None
    in_reply_to: str | None = None


@dataclass(frozen=True)
class SendResult:
    provider_message_id: str
    provider_thread_id: str
    delivery_state: Literal["sent", "demo"]


@dataclass(frozen=True)
class ScopeInfo:
    scope: str
    why: str


@dataclass(frozen=True)
class ConnectorManifest:
    key: str
    label: str
    is_demo: bool
    capabilities: tuple[str, ...]
    scopes: tuple[ScopeInfo, ...] = ()
    setup_doc: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)
