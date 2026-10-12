"""CRM entities: knowledge, companies, contacts, leads, tags, activities, tasks, pipeline.

Conventions (see docs/DATA_MODEL.md): UUID primary keys, ``workspace_id`` on every table, composite
tenant foreign keys, status columns as strings guarded by CHECK constraints, soft deletion (``archived_at``)
only for records users manage and may want back (companies, contacts, leads).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
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


class PipelineStage(TenantMixin, Timestamps, Base):
    __tablename__ = "pipeline_stages"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_pipeline_stages_workspace_id_id"),
        UniqueConstraint("workspace_id", "key", name="uq_pipeline_stages_workspace_key"),
        CheckConstraint("position >= 0", name="position_non_negative"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_won: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_lost: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class KnowledgeItem(TenantMixin, Timestamps, Base):
    """A reusable fact about the freelancer. Only ``approved`` items may reach AI context."""

    __tablename__ = "knowledge_items"
    __table_args__ = (
        check_in("kind", domain.KNOWLEDGE_KINDS),
        check_in("source_type", domain.KNOWLEDGE_SOURCES),
        check_in("status", domain.KNOWLEDGE_STATUSES),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_knowledge_items_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="fact")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Provenance: where the fact came from and who vouched for it.
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    source_ref: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )


class Company(TenantMixin, Timestamps, Base):
    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_companies_workspace_id_id"),
        # Duplicate protection: one company per website domain per workspace (NULL domains are allowed).
        UniqueConstraint("workspace_id", "domain_normalized", name="uq_companies_workspace_domain"),
        Index("ix_companies_workspace_name", "workspace_id", "name"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(253))
    domain_normalized: Mapped[str | None] = mapped_column(String(253))
    website: Mapped[str | None] = mapped_column(String(500))
    industry: Mapped[str | None] = mapped_column(String(100))
    size_label: Mapped[str | None] = mapped_column(String(40))
    location: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    # Provenance for imported/enriched data (MVP Prompt 6): where from and when retrieved.
    source: Mapped[str | None] = mapped_column(String(100))
    source_retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Contact(TenantMixin, Timestamps, Base):
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_contacts_workspace_id_id"),
        UniqueConstraint("workspace_id", "email_normalized", name="uq_contacts_workspace_email"),
        tenant_fk("contacts", "company_id", "companies"),
        Index("ix_contacts_workspace_company", "workspace_id", "company_id"),
        Index("ix_contacts_workspace_name", "workspace_id", "full_name"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    company_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(254))
    email_normalized: Mapped[str | None] = mapped_column(String(254))
    role_title: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(100))
    source_retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Lead(TenantMixin, Timestamps, Base):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_leads_workspace_id_id"),
        check_in("status", domain.LEAD_STATUSES),
        CheckConstraint(
            "fit_score IS NULL OR (fit_score >= 0 AND fit_score <= 100)", name="fit_score_range"
        ),
        tenant_fk("leads", "company_id", "companies"),
        tenant_fk("leads", "contact_id", "contacts"),
        tenant_fk("leads", "stage_id", "pipeline_stages"),
        Index("ix_leads_workspace_status", "workspace_id", "status"),
        Index("ix_leads_workspace_fit", "workspace_id", "fit_score"),
        Index("ix_leads_workspace_company", "workspace_id", "company_id"),
        Index("ix_leads_workspace_contact", "workspace_id", "contact_id"),
        Index("ix_leads_workspace_last_activity", "workspace_id", "last_activity_at"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    company_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    stage_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    source: Mapped[str | None] = mapped_column(String(100))
    source_retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    industry: Mapped[str | None] = mapped_column(String(100))
    location: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    # Fit score with evidence (MVP Prompt 6). The breakdown is explanatory data, never a secret.
    fit_score: Mapped[int | None] = mapped_column(Integer)
    fit_explanation: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    next_action: Mapped[str | None] = mapped_column(String(300))
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    is_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Tag(TenantMixin, Timestamps, Base):
    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_tags_workspace_id_id"),
        UniqueConstraint("workspace_id", "name_normalized", name="uq_tags_workspace_name"),
        CheckConstraint("color IS NULL OR length(color) = 7", name="color_hex_length"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(50), nullable=False)
    color: Mapped[str | None] = mapped_column(String(7))


class LeadTag(TenantMixin, Base):
    __tablename__ = "lead_tags"
    __table_args__ = (
        PrimaryKeyConstraint("lead_id", "tag_id", name="pk_lead_tags"),
        tenant_fk("lead_tags", "lead_id", "leads", ondelete="CASCADE"),
        tenant_fk("lead_tags", "tag_id", "tags", ondelete="CASCADE"),
        Index("ix_lead_tags_workspace_tag", "workspace_id", "tag_id"),
    )

    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    tag_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class Opportunity(TenantMixin, Timestamps, Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_opportunities_workspace_id_id"),
        check_in("status", domain.OPPORTUNITY_STATUSES),
        CheckConstraint(
            "probability IS NULL OR (probability >= 0 AND probability <= 100)",
            name="probability_range",
        ),
        CheckConstraint("value_amount IS NULL OR value_amount >= 0", name="value_non_negative"),
        CheckConstraint("length(currency) = 3", name="currency_iso_length"),
        tenant_fk("opportunities", "lead_id", "leads", ondelete="CASCADE"),
        tenant_fk("opportunities", "stage_id", "pipeline_stages"),
        Index("ix_opportunities_workspace_stage", "workspace_id", "stage_id"),
        Index("ix_opportunities_workspace_lead", "workspace_id", "lead_id"),
        Index("ix_opportunities_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    stage_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="open")
    value_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    probability: Mapped[int | None] = mapped_column(Integer)
    expected_close_date: Mapped[date | None] = mapped_column(Date)
    next_action: Mapped[str | None] = mapped_column(String(300))
    loss_reason: Mapped[str | None] = mapped_column(String(300))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    is_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Activity(TenantMixin, Base):
    """Append-only timeline entry on a lead and/or opportunity."""

    __tablename__ = "activities"
    __table_args__ = (
        check_in("kind", domain.ACTIVITY_KINDS),
        CheckConstraint("lead_id IS NOT NULL OR opportunity_id IS NOT NULL", name="has_subject"),
        tenant_fk("activities", "lead_id", "leads", ondelete="CASCADE"),
        tenant_fk("activities", "opportunity_id", "opportunities", ondelete="CASCADE"),
        Index("ix_activities_workspace_lead_time", "workspace_id", "lead_id", "occurred_at"),
        Index("ix_activities_workspace_opp_time", "workspace_id", "opportunity_id", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class Task(TenantMixin, Timestamps, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        check_in("status", domain.TASK_STATUSES),
        check_in("priority", domain.TASK_PRIORITIES),
        # Retry/double-submit protection: the same client key can only create one task per workspace.
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_tasks_workspace_idempotency"),
        tenant_fk("tasks", "lead_id", "leads", ondelete="CASCADE"),
        tenant_fk("tasks", "opportunity_id", "opportunities", ondelete="CASCADE"),
        tenant_fk("tasks", "conversation_id", "conversations", ondelete="CASCADE"),
        Index("ix_tasks_workspace_status_due", "workspace_id", "status", "due_at"),
        Index("ix_tasks_workspace_assignee", "workspace_id", "assignee_user_id"),
        Index("ix_tasks_workspace_lead", "workspace_id", "lead_id"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="open")
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default="normal")
    # due_at is an instant (UTC); due_timezone remembers the zone the user meant, for DST-correct display.
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_timezone: Mapped[str | None] = mapped_column(String(64))
    remind_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_by: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    is_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
