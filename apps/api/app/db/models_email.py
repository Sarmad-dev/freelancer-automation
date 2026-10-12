"""Email, outreach and integration metadata.

Secrets: OAuth tokens and API keys NEVER live in these general-purpose tables. ``EmailAccount`` and
``IntegrationConnection`` hold only a ``credential_id`` pointing into ``credential_secrets``, whose payload
is encrypted at rest by ``app.security.credentials``. Message bodies are not stored in the MVP schema
(only metadata and a short snippet); a body/retention decision is part of MVP Prompt 10.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app import domain
from app.clock import utcnow
from app.db.base import Base
from app.db.mixins import TenantMixin, Timestamps, check_in, pk_column, tenant_fk


class CredentialSecret(TenantMixin, Base):
    """Encrypted credential material (OAuth tokens, API keys). The only table allowed to hold secrets."""

    __tablename__ = "credential_secrets"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_credential_secrets_workspace_id_id"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    purpose: Mapped[str] = mapped_column(String(60), nullable=False)
    # Authenticated encryption (Fernet); never plaintext. ``key_id`` supports key rotation.
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_id: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailAccount(TenantMixin, Timestamps, Base):
    __tablename__ = "email_accounts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_email_accounts_workspace_id_id"),
        # One row per connected mailbox: a provider account id can only be linked once per workspace.
        UniqueConstraint(
            "workspace_id",
            "provider",
            "provider_account_id",
            name="uq_email_accounts_provider_account",
        ),
        check_in("provider", domain.PROVIDERS),
        check_in("status", domain.CONNECTION_STATUSES),
        tenant_fk("email_accounts", "credential_id", "credential_secrets"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_account_id: Mapped[str] = mapped_column(String(200), nullable=False)
    email_address: Mapped[str] = mapped_column(String(254), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="disconnected")
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    credential_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    granted_scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # Provider sync cursor (e.g. Gmail historyId). Opaque and non-secret.
    sync_cursor: Mapped[str | None] = mapped_column(String(200))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(60))


class Conversation(TenantMixin, Timestamps, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_conversations_workspace_id_id"),
        UniqueConstraint(
            "email_account_id", "provider_thread_id", name="uq_conversations_account_thread"
        ),
        check_in("status", domain.CONVERSATION_STATUSES),
        CheckConstraint(
            "classification IS NULL OR classification IN ("
            + ", ".join(f"'{c}'" for c in domain.REPLY_CATEGORIES)
            + ")",
            name="classification_valid",
        ),
        CheckConstraint(
            "classification_confidence IS NULL OR (classification_confidence >= 0 AND classification_confidence <= 1)",
            name="confidence_range",
        ),
        tenant_fk("conversations", "email_account_id", "email_accounts", ondelete="CASCADE"),
        tenant_fk("conversations", "lead_id", "leads"),
        tenant_fk("conversations", "contact_id", "contacts"),
        Index("ix_conversations_workspace_last_message", "workspace_id", "last_message_at"),
        Index("ix_conversations_workspace_lead", "workspace_id", "lead_id"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    email_account_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    provider_thread_id: Mapped[str] = mapped_column(String(200), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(500))
    lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="open")
    unread: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    classification: Mapped[str | None] = mapped_column(String(20))
    classification_confidence: Mapped[float | None] = mapped_column(Float)
    classification_explanation: Mapped[str | None] = mapped_column(String(1000))
    is_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Message(TenantMixin, Base):
    """Message metadata. No body column by design (see module docstring)."""

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_messages_workspace_id_id"),
        # Idempotent sync: re-fetching the same provider message upserts instead of duplicating.
        UniqueConstraint(
            "email_account_id", "provider_message_id", name="uq_messages_account_provider_message"
        ),
        check_in("direction", domain.MESSAGE_DIRECTIONS),
        check_in("delivery_state", domain.MESSAGE_DELIVERY_STATES),
        tenant_fk("messages", "email_account_id", "email_accounts", ondelete="CASCADE"),
        tenant_fk("messages", "conversation_id", "conversations", ondelete="CASCADE"),
        Index(
            "ix_messages_workspace_conversation_sent", "workspace_id", "conversation_id", "sent_at"
        ),
    )

    id: Mapped[uuid.UUID] = pk_column()
    email_account_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    provider_message_id: Mapped[str] = mapped_column(String(200), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    delivery_state: Mapped[str] = mapped_column(String(10), nullable=False, default="unknown")
    from_address: Mapped[str] = mapped_column(String(254), nullable=False)
    to_addresses: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    subject: Mapped[str | None] = mapped_column(String(500))
    snippet: Mapped[str | None] = mapped_column(String(500))
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    is_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Draft(TenantMixin, Timestamps, Base):
    """An outbound message awaiting review. Approval binds to ``content_hash`` so edits require re-approval."""

    __tablename__ = "drafts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_drafts_workspace_id_id"),
        UniqueConstraint(
            "workspace_id", "send_idempotency_key", name="uq_drafts_workspace_send_key"
        ),
        check_in("status", domain.DRAFT_STATUSES),
        check_in("author", domain.DRAFT_AUTHORS),
        CheckConstraint("version >= 1", name="version_positive"),
        tenant_fk("drafts", "lead_id", "leads", ondelete="CASCADE"),
        tenant_fk("drafts", "conversation_id", "conversations", ondelete="CASCADE"),
        tenant_fk("drafts", "email_account_id", "email_accounts"),
        Index("ix_drafts_workspace_status", "workspace_id", "status"),
        Index("ix_drafts_workspace_lead", "workspace_id", "lead_id"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    email_account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    to_address: Mapped[str | None] = mapped_column(String(254))
    subject: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    body_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    author: Mapped[str] = mapped_column(String(10), nullable=False, default="user")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    approved_content_hash: Mapped[str | None] = mapped_column(String(64))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    # Which approved knowledge items informed an AI draft (ids only; shown in the review UI).
    facts_used: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    send_idempotency_key: Mapped[str | None] = mapped_column(String(100))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class SuppressionEntry(TenantMixin, Timestamps, Base):
    """Do-not-contact list. Checked server-side at every send path."""

    __tablename__ = "suppression_entries"
    __table_args__ = (
        UniqueConstraint("workspace_id", "email_normalized", name="uq_suppression_workspace_email"),
        check_in("reason", domain.SUPPRESSION_REASONS),
    )

    id: Mapped[uuid.UUID] = pk_column()
    email_normalized: Mapped[str] = mapped_column(String(254), nullable=False)
    reason: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str | None] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(String(300))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )


class IntegrationConnection(TenantMixin, Timestamps, Base):
    __tablename__ = "integration_connections"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_integration_connections_workspace_id_id"),
        UniqueConstraint(
            "workspace_id",
            "connector",
            "external_account_id",
            name="uq_integration_connections_account",
        ),
        check_in("status", domain.CONNECTION_STATUSES),
        tenant_fk("integration_connections", "credential_id", "credential_secrets"),
        Index("ix_integration_connections_workspace_connector", "workspace_id", "connector"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    connector: Mapped[str] = mapped_column(String(40), nullable=False)
    external_account_id: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="disconnected")
    credential_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    granted_scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    capabilities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # Non-secret settings only. Anything sensitive goes through the credential store.
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    last_health_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(60))
