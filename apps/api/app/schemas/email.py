"""Mailbox connectors, accounts, sync and suppression (MVP Prompt 9)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.text import bounded


class ScopeOut(BaseModel):
    scope: str
    why: str


class ProviderOut(BaseModel):
    key: str
    label: str
    is_demo: bool
    configured: bool = Field(
        description="Whether this server has what it needs to use the provider."
    )
    capabilities: list[str]
    scopes: list[ScopeOut]
    setup_doc: str | None
    notes: list[str]
    verified_live: bool = Field(
        description="True only once the provider has been verified end to end against a real account. Never true yet."
    )


class EmailAccountOut(BaseModel):
    id: uuid.UUID
    provider: str
    email_address: str
    display_name: str | None
    status: Literal["connected", "demo", "needs_reauth", "disconnected", "error"]
    status_label: str
    is_demo: bool
    needs_reconnect: bool
    granted_scopes: list[str]
    last_synced_at: datetime | None
    last_health_check_at: datetime | None
    rate_limited_until: datetime | None
    last_error_code: str | None
    last_error: str | None = Field(description="The last problem in plain language.")
    created_at: datetime


class ConnectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["gmail"]
    login_hint: str | None = Field(default=None, max_length=254)


class ConnectOut(BaseModel):
    authorization_url: str


class SyncOut(BaseModel):
    account: EmailAccountOut
    conversations_created: int
    messages_created: int
    messages_updated: int
    skipped: int
    pages: int
    complete: bool
    rate_limited_until: datetime | None
    error_code: str | None
    classification_pending: int = Field(
        default=0,
        description="Replies waiting to be classified in the background (not waited for).",
    )


class TestOut(BaseModel):
    ok: bool
    account: EmailAccountOut


class DisconnectOut(BaseModel):
    account: EmailAccountOut
    revoked: bool = Field(
        description="Whether the provider confirmed the grant is revoked. If false, remove access in the provider's account settings."
    )


class SuppressionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Annotated[str, bounded(3, 254)]
    reason: Literal["unsubscribe", "bounce", "complaint", "manual", "replied_stop"] = "manual"
    note: Annotated[str, bounded(0, 300)] | None = None


class SuppressionOut(BaseModel):
    id: uuid.UUID
    email: str
    reason: str
    source: str | None
    note: str | None
    created_at: datetime
