"""Companies and contacts: validation, duplicate protection, find-or-create and serialisation."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.db.models_crm import Company, Contact, Lead
from app.db.models_email import SuppressionEntry
from app.deps import WorkspaceContext
from app.errors import AppError
from app.schemas.leads import (
    CompanyCreate,
    CompanyOut,
    CompanyPatch,
    ContactCreate,
    ContactOut,
    ContactPatch,
)
from app.services.normalize import key, normalize_email, normalize_website


# ---------------------------------------------------------------- errors / lookups
def not_found(what: str) -> AppError:
    return AppError(404, f"{what}_not_found", f"{what.capitalize()} not found.")


def invalid_ref(field: str, what: str) -> AppError:
    return AppError(
        422, "validation_error", "Some fields are invalid.", fields={field: f"{what} not found."}
    )


def require_company(
    db: DbSession, ctx: WorkspaceContext, company_id: uuid.UUID, field: str = "company_id"
) -> Company:
    company = db.scalar(
        select(Company).where(Company.workspace_id == ctx.workspace_id, Company.id == company_id)
    )
    if company is None:
        raise invalid_ref(field, "Company")
    return company


def require_contact(
    db: DbSession, ctx: WorkspaceContext, contact_id: uuid.UUID, field: str = "contact_id"
) -> Contact:
    contact = db.scalar(
        select(Contact).where(Contact.workspace_id == ctx.workspace_id, Contact.id == contact_id)
    )
    if contact is None:
        raise invalid_ref(field, "Contact")
    return contact


def company_by_domain(db: DbSession, ctx: WorkspaceContext, domain: str) -> Company | None:
    return db.scalar(
        select(Company).where(
            Company.workspace_id == ctx.workspace_id, Company.domain_normalized == domain
        )
    )


def company_by_name(db: DbSession, ctx: WorkspaceContext, name: str) -> Company | None:
    return db.scalar(
        select(Company)
        .where(Company.workspace_id == ctx.workspace_id, func.lower(Company.name) == key(name))
        .order_by(Company.archived_at.is_not(None), Company.created_at)
        .limit(1)
    )


def contact_by_email(db: DbSession, ctx: WorkspaceContext, email: str) -> Contact | None:
    return db.scalar(
        select(Contact).where(
            Contact.workspace_id == ctx.workspace_id, Contact.email_normalized == email
        )
    )


def _duplicate_company() -> AppError:
    return AppError(
        409,
        "company_exists",
        "A company with this website already exists.",
        fields={"website": "A company with this website already exists."},
    )


def _duplicate_contact() -> AppError:
    return AppError(
        409,
        "contact_exists",
        "A contact with this email already exists.",
        fields={"email": "A contact with this email already exists."},
    )


def ensure_editable(archived_at: datetime | None, what: str) -> None:
    if archived_at is not None:
        raise AppError(409, f"{what}_archived", f"This {what} is archived. Restore it to edit it.")


# ---------------------------------------------------------------- companies
def create_company(
    db: DbSession,
    ctx: WorkspaceContext,
    body: CompanyCreate,
    *,
    retrieved_at: datetime | None = None,
) -> Company:
    domain = normalize_website(body.website)[1] if body.website else None
    if domain and company_by_domain(db, ctx, domain):
        raise _duplicate_company()
    company = Company(
        workspace_id=ctx.workspace_id,
        name=body.name,
        website=body.website,
        domain=domain,
        domain_normalized=domain,
        industry=body.industry,
        size_label=body.size_label,
        location=body.location,
        notes=body.notes,
        source=body.source or "manual",
        source_retrieved_at=retrieved_at,
    )
    db.add(company)
    try:
        db.flush()
    except IntegrityError as exc:  # a concurrent request created the same domain
        db.rollback()
        raise _duplicate_company() from exc
    return company


def update_company(
    db: DbSession, ctx: WorkspaceContext, company: Company, body: CompanyPatch
) -> list[str]:
    ensure_editable(company.archived_at, "company")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("name") is None:
        changes.pop("name", None)
    if "website" in changes:
        website = changes.pop("website")
        domain = normalize_website(website)[1] if website else None
        if domain and domain != company.domain_normalized:
            other = company_by_domain(db, ctx, domain)
            if other and other.id != company.id:
                raise _duplicate_company()
        company.website, company.domain, company.domain_normalized = website, domain, domain
    for field, value in changes.items():
        setattr(company, field, value)
    fields = sorted(set(body.model_fields_set))
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise _duplicate_company() from exc
    return fields


def find_or_create_company(
    db: DbSession,
    ctx: WorkspaceContext,
    *,
    name: str | None,
    website: str | None,
    source: str | None,
    retrieved_at: datetime | None = None,
    industry: str | None = None,
    size_label: str | None = None,
    location: str | None = None,
) -> tuple[Company | None, bool]:
    """Match an existing company by website domain, then by exact (case-insensitive) name; else create one."""
    domain = normalize_website(website)[1] if website else None
    existing = company_by_domain(db, ctx, domain) if domain else None
    if existing is None and name:
        existing = company_by_name(db, ctx, name)
        if (
            existing
            and domain
            and existing.domain_normalized
            and existing.domain_normalized != domain
        ):
            existing = None  # same name, different website: a different company
    if existing is not None:
        return existing, False
    if not name and domain:
        name = domain
    if not name:
        return None, False
    body = CompanyCreate(
        name=name,
        website=website,
        industry=industry,
        size_label=size_label,
        location=location,
        source=source,
    )
    return create_company(db, ctx, body, retrieved_at=retrieved_at), True


# ---------------------------------------------------------------- contacts
def create_contact(
    db: DbSession,
    ctx: WorkspaceContext,
    body: ContactCreate,
    *,
    retrieved_at: datetime | None = None,
) -> Contact:
    if body.company_id:
        require_company(db, ctx, body.company_id)
    if body.email and contact_by_email(db, ctx, body.email):
        raise _duplicate_contact()
    contact = Contact(
        workspace_id=ctx.workspace_id,
        company_id=body.company_id,
        full_name=body.full_name,
        email=body.email,
        email_normalized=body.email,
        role_title=body.role_title,
        phone=body.phone,
        notes=body.notes,
        source=body.source or "manual",
        source_retrieved_at=retrieved_at,
    )
    db.add(contact)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise _duplicate_contact() from exc
    return contact


def update_contact(
    db: DbSession, ctx: WorkspaceContext, contact: Contact, body: ContactPatch
) -> list[str]:
    ensure_editable(contact.archived_at, "contact")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("full_name") is None:
        changes.pop("full_name", None)
    if "company_id" in changes and changes["company_id"] is not None:
        require_company(db, ctx, changes["company_id"])
    if "email" in changes:
        email = changes.pop("email")
        if email and email != contact.email_normalized:
            other = contact_by_email(db, ctx, email)
            if other and other.id != contact.id:
                raise _duplicate_contact()
        contact.email = email
        contact.email_normalized = email
    for field, value in changes.items():
        setattr(contact, field, value)
    fields = sorted(set(body.model_fields_set))
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise _duplicate_contact() from exc
    return fields


def parse_email(raw: str) -> str:
    return normalize_email(raw)


# ---------------------------------------------------------------- suppression
def suppressed_among(
    db: DbSession, ctx: WorkspaceContext, emails: Iterable[str | None]
) -> set[str]:
    wanted = {e for e in emails if e}
    if not wanted:
        return set()
    found: set[str] = set()
    ordered = sorted(wanted)
    for i in range(0, len(ordered), 500):
        chunk = ordered[i : i + 500]
        found.update(
            db.scalars(
                select(SuppressionEntry.email_normalized).where(
                    SuppressionEntry.workspace_id == ctx.workspace_id,
                    SuppressionEntry.email_normalized.in_(chunk),
                )
            )
        )
    return found


# ---------------------------------------------------------------- serialisation
def _counts(
    db: DbSession, ctx: WorkspaceContext, column: Any, model: Any, ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not ids:
        return {}
    rows = db.execute(
        select(column, func.count())
        .where(model.workspace_id == ctx.workspace_id, column.in_(ids), model.archived_at.is_(None))
        .group_by(column)
    ).all()
    return {row[0]: int(row[1]) for row in rows}


def company_outs(
    db: DbSession, ctx: WorkspaceContext, companies: Sequence[Company]
) -> list[CompanyOut]:
    ids = [c.id for c in companies]
    leads = _counts(db, ctx, Lead.company_id, Lead, ids)
    contacts = _counts(db, ctx, Contact.company_id, Contact, ids)
    return [
        CompanyOut(
            id=c.id,
            name=c.name,
            domain=c.domain,
            website=c.website,
            industry=c.industry,
            size_label=c.size_label,
            location=c.location,
            notes=c.notes,
            source=c.source,
            source_retrieved_at=c.source_retrieved_at,
            is_sample=c.is_sample,
            archived_at=c.archived_at,
            created_at=c.created_at,
            updated_at=c.updated_at,
            lead_count=leads.get(c.id, 0),
            contact_count=contacts.get(c.id, 0),
        )
        for c in companies
    ]


def contact_outs(
    db: DbSession, ctx: WorkspaceContext, contacts: Sequence[Contact]
) -> list[ContactOut]:
    company_ids = {c.company_id for c in contacts if c.company_id}
    names: dict[uuid.UUID, str] = {}
    if company_ids:
        names = {
            row[0]: row[1]
            for row in db.execute(
                select(Company.id, Company.name).where(
                    Company.workspace_id == ctx.workspace_id, Company.id.in_(company_ids)
                )
            )
        }
    leads = _counts(db, ctx, Lead.contact_id, Lead, [c.id for c in contacts])
    blocked = suppressed_among(db, ctx, (c.email_normalized for c in contacts))
    return [
        ContactOut(
            id=c.id,
            full_name=c.full_name,
            email=c.email,
            role_title=c.role_title,
            phone=c.phone,
            company_id=c.company_id,
            company_name=names.get(c.company_id) if c.company_id else None,
            notes=c.notes,
            source=c.source,
            source_retrieved_at=c.source_retrieved_at,
            is_sample=c.is_sample,
            archived_at=c.archived_at,
            do_not_contact=bool(c.email_normalized and c.email_normalized in blocked),
            lead_count=leads.get(c.id, 0),
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in contacts
    ]
