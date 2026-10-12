"""Builds model inputs from stored records: workspace-scoped, minimal, no contact details.

A lead's company, industry and notes go in; its email address, phone number and other contacts' details do not.
Callers pass these to ``AiService`` together with an ``AiContext`` from ``app.services.ai_context.build_context``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.schemas import ConversationMessage, DraftLead, LeadFacts
from app.api.scoping import get_scoped_or_404
from app.db.models_crm import Company, Contact, Lead
from app.db.models_email import Conversation, Message
from app.deps import WorkspaceContext


def _company(db: Session, ctx: WorkspaceContext, company_id: uuid.UUID | None) -> Company | None:
    if company_id is None:
        return None
    return db.scalar(
        select(Company).where(Company.id == company_id, Company.workspace_id == ctx.workspace_id)
    )


def lead_facts(db: Session, ctx: WorkspaceContext, lead_id: uuid.UUID) -> LeadFacts:
    lead = get_scoped_or_404(
        db, Lead, ctx, lead_id, code="lead_not_found", message="Lead not found."
    )
    company = _company(db, ctx, lead.company_id)
    return LeadFacts(
        title=lead.title,
        company_name=company.name if company else None,
        industry=lead.industry or (company.industry if company else None),
        company_size=company.size_label if company else None,
        location=lead.location or (company.location if company else None),
        budget_signal=lead.budget_signal,
        source=lead.source,
        notes=lead.notes,
    )


def draft_target(
    db: Session, ctx: WorkspaceContext, lead_id: uuid.UUID
) -> tuple[DraftLead, str | None]:
    """The lead as a drafter may see it, and the contact's FIRST name (never the full name or address)."""
    lead = get_scoped_or_404(
        db, Lead, ctx, lead_id, code="lead_not_found", message="Lead not found."
    )
    company = _company(db, ctx, lead.company_id)
    first_name: str | None = None
    if lead.contact_id is not None:
        contact = db.scalar(
            select(Contact).where(
                Contact.id == lead.contact_id, Contact.workspace_id == ctx.workspace_id
            )
        )
        if contact and contact.full_name.strip():
            first_name = contact.full_name.split()[0][:60]
    return (
        DraftLead(
            title=lead.title,
            company_name=company.name if company else None,
            industry=lead.industry or (company.industry if company else None),
            location=lead.location or (company.location if company else None),
            notes=lead.notes,
        ),
        first_name,
    )


def conversation_messages(
    db: Session, ctx: WorkspaceContext, conversation_id: uuid.UUID, limit: int = 10
) -> list[ConversationMessage]:
    """The newest ``limit`` messages, oldest first, as short snippets with no addresses."""
    conversation = get_scoped_or_404(
        db,
        Conversation,
        ctx,
        conversation_id,
        code="conversation_not_found",
        message="Conversation not found.",
    )
    rows = db.scalars(
        select(Message)
        .where(Message.workspace_id == ctx.workspace_id, Message.conversation_id == conversation.id)
        .order_by(Message.sent_at.desc(), Message.id)
        .limit(max(1, min(limit, 20)))
    ).all()
    return [
        ConversationMessage(
            direction="inbound" if m.direction == "inbound" else "outbound",
            sent_at=m.sent_at,
            subject=m.subject,
            text=m.snippet or "",
        )
        for m in reversed(rows)
    ]
