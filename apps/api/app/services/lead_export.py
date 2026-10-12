"""CSV export of leads (the caller has already checked authorisation and applied the filters)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db.models_crm import Company, Contact, Lead
from app.deps import WorkspaceContext
from app.services import leads as lead_svc
from app.services.csvio import to_csv

MAX_EXPORT_ROWS = 10_000
HEADER = [
    "title",
    "status",
    "stage",
    "fit_score",
    "fit_band",
    "company",
    "website",
    "contact_name",
    "email",
    "role",
    "phone",
    "do_not_contact",
    "industry",
    "location",
    "source",
    "tags",
    "budget",
    "next_action",
    "next_action_at",
    "notes",
    "created_at",
    "archived",
]


def export_csv(db: DbSession, ctx: WorkspaceContext, leads: Sequence[Lead]) -> str:
    outs = lead_svc.lead_outs(db, ctx, leads)
    company_ids = {lead.company_id for lead in leads if lead.company_id}
    contact_ids = {lead.contact_id for lead in leads if lead.contact_id}
    companies: dict[uuid.UUID, Company] = (
        {
            c.id: c
            for c in db.scalars(
                select(Company).where(
                    Company.workspace_id == ctx.workspace_id, Company.id.in_(company_ids)
                )
            )
        }
        if company_ids
        else {}
    )
    contacts: dict[uuid.UUID, Contact] = (
        {
            c.id: c
            for c in db.scalars(
                select(Contact).where(
                    Contact.workspace_id == ctx.workspace_id, Contact.id.in_(contact_ids)
                )
            )
        }
        if contact_ids
        else {}
    )
    rows: list[list[object]] = []
    for lead, out in zip(leads, outs, strict=True):
        company = companies.get(lead.company_id) if lead.company_id else None
        contact = contacts.get(lead.contact_id) if lead.contact_id else None
        rows.append(
            [
                out.title,
                out.status,
                out.stage.name if out.stage else "",
                "" if out.fit_score is None else out.fit_score,
                out.fit_band or "",
                company.name if company else "",
                company.website if company and company.website else "",
                contact.full_name if contact else "",
                contact.email if contact and contact.email else "",
                contact.role_title if contact and contact.role_title else "",
                contact.phone if contact and contact.phone else "",
                "yes" if out.do_not_contact else "",
                out.industry or "",
                out.location or "",
                out.source or "",
                "; ".join(t.name for t in out.tags),
                out.budget_signal or "",
                out.next_action or "",
                out.next_action_at.isoformat() if out.next_action_at else "",
                out.notes or "",
                out.created_at.isoformat(),
                "yes" if out.archived_at else "",
            ]
        )
    return to_csv(HEADER, rows)
