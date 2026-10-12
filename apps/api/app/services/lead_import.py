"""CSV import of leads (with their companies and contacts).

One code path serves both the preview and the real import: the preview runs the import inside the request's
transaction and rolls it back, so what the preview says will happen is exactly what the import does. Nothing is
scraped or fetched; every value comes from the file, and provenance (source label and import time) is recorded.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.clock import utcnow
from app.db.models_crm import Company, Contact, ImportJob, Lead, LeadTag, Tag
from app.deps import WorkspaceContext
from app.domain import COMPANY_SIZES, LEAD_STATUSES
from app.schemas.imports import ImportMapping
from app.schemas.leads import CompanyCreate, ContactCreate
from app.schemas.text import multi_line, single_line
from app.services import crm
from app.services import leads as lead_svc
from app.services.csvio import ParsedCsv
from app.services.fit_scoring import Scorer
from app.services.normalize import key, normalize_email, normalize_phone, normalize_website

MAX_STORED_ERRORS = 1_000
TARGETS = tuple(ImportMapping.model_fields)
DEFAULT_SOURCE = "CSV import"

_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "fullname", "contact", "contactname", "person", "firstlast"),
    "email": ("email", "emailaddress", "mail", "workemail", "contactemail"),
    "role": ("role", "jobtitle", "position", "title"),
    "phone": ("phone", "phonenumber", "telephone", "tel", "mobile"),
    "company": ("company", "companyname", "organization", "organisation", "employer", "account"),
    "website": ("website", "url", "site", "domain", "companywebsite", "web"),
    "company_size": ("companysize", "size", "employees", "headcount"),
    "industry": ("industry", "sector", "vertical"),
    "location": ("location", "city", "region", "country", "place"),
    "title": ("leadtitle", "lead", "project", "opportunity", "subject", "leadname"),
    "source": ("source", "leadsource", "origin"),
    "notes": ("notes", "note", "comments", "comment", "description"),
    "budget": ("budget", "budgetsignal"),
    "tags": ("tags", "tag", "labels", "label"),
    "status": ("status", "leadstatus"),
    "next_action": ("nextaction", "nextstep"),
}
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_TAG_SPLIT = re.compile(r"[;|,]")


# ---------------------------------------------------------------- mapping
def suggest_mapping(headers: list[str]) -> dict[str, str | None]:
    """Guess which column feeds which field from the header text. Each column is used at most once."""
    folded = {h: _NON_ALNUM.sub("", h.casefold()) for h in headers if h}
    used: set[str] = set()
    mapping: dict[str, str | None] = dict.fromkeys(TARGETS)
    for target in TARGETS:
        for header, norm in folded.items():
            if header not in used and norm in _ALIASES[target]:
                mapping[target] = header
                used.add(header)
                break
    return mapping


def resolve_mapping(
    mapping: dict[str, str | None], headers: list[str]
) -> tuple[dict[str, int], str | None]:
    """Header text -> column index per target, or a problem message."""
    by_fold = {h.casefold(): i for i, h in enumerate(headers) if h}
    resolved: dict[str, int] = {}
    for target, header in mapping.items():
        if header is None or not header.strip():
            continue
        index = by_fold.get(header.strip().casefold())
        if index is None:
            return {}, f"The column “{header}” isn't in the file."
        resolved[target] = index
    if len(set(resolved.values())) != len(resolved):
        return {}, "One column is mapped to more than one field."
    if not ({"name", "email", "company"} & set(resolved)):
        return {}, "Map at least one of name, email or company."
    return resolved, None


# ---------------------------------------------------------------- cleaning
def _line(value: str, limit: int) -> str:
    cleaned = single_line(value)
    if len(cleaned) > limit:
        raise ValueError(f"Use at most {limit} characters.")
    return cleaned


def _normalize_size(value: str) -> str:
    candidate = value.strip().replace("–", "-").replace("—", "-").replace(" ", "")
    if candidate in COMPANY_SIZES:
        return candidate
    raise ValueError("Use one of: " + ", ".join(COMPANY_SIZES) + ".")


def _clean_tags(value: str) -> list[str]:
    tags: list[str] = []
    for part in _TAG_SPLIT.split(value):
        tag = single_line(part)
        if not tag:
            continue
        if len(tag) > 50:
            raise ValueError("Each tag must be at most 50 characters.")
        if tag.casefold() not in {t.casefold() for t in tags}:
            tags.append(tag)
    if len(tags) > 10:
        raise ValueError("Use at most 10 tags per row.")
    return tags


def clean_value(target: str, raw: str) -> Any:
    """Validate one cell. Raises ``ValueError`` with a message for the person fixing the file."""
    if target == "name":
        return _line(raw, 200)
    if target == "email":
        return normalize_email(raw)
    if target == "role":
        return _line(raw, 120)
    if target == "phone":
        return normalize_phone(raw)
    if target in ("company", "title"):
        return _line(raw, 200)
    if target == "website":
        return normalize_website(raw)[0]
    if target == "company_size":
        return _normalize_size(raw)
    if target == "industry" or target == "source":
        return _line(raw, 100)
    if target == "location":
        return _line(raw, 200)
    if target == "notes":
        cleaned = multi_line(raw)
        if len(cleaned) > 4000:
            raise ValueError("Use at most 4000 characters.")
        return cleaned
    if target == "budget":
        value = single_line(raw).casefold()
        if value in ("low", "medium", "high"):
            return value
        raise ValueError("Use low, medium or high.")
    if target == "tags":
        return _clean_tags(raw)
    if target == "status":
        value = single_line(raw).casefold()
        if value in LEAD_STATUSES:
            return value
        raise ValueError("Use one of: " + ", ".join(LEAD_STATUSES) + ".")
    if target == "next_action":
        return _line(raw, 300)
    raise ValueError("Unknown field.")  # pragma: no cover


@dataclass
class CleanRow:
    number: int
    values: dict[str, Any]
    issues: list[tuple[str, str, str]]  # (column header, message, raw value)


def clean_rows(parsed: ParsedCsv, resolved: dict[str, int]) -> list[CleanRow]:
    rows: list[CleanRow] = []
    for number, cells in zip(parsed.row_numbers, parsed.rows, strict=True):
        values: dict[str, Any] = {}
        issues: list[tuple[str, str, str]] = []
        for target, index in resolved.items():
            raw = cells[index]
            if not raw:
                continue
            try:
                value = clean_value(target, raw)
            except ValueError as exc:
                issues.append((parsed.headers[index], str(exc), raw[:200]))
                continue
            if value not in ("", []):
                values[target] = value
        if extra := parsed.extra_cells.get(number):
            issues.append(
                ("", f"The row has {extra} more value(s) than the header. Is a comma unquoted?", "")
            )
        if not issues and not ({"name", "email", "company"} & set(values)):
            issues.append(("", "The row needs at least a name, an email or a company.", ""))
        rows.append(CleanRow(number, values, issues))
    return rows


def derived_title(values: dict[str, Any]) -> str:
    if values.get("title"):
        return str(values["title"])
    parts = [str(values[k]) for k in ("company", "name") if values.get(k)]
    return (" – ".join(parts) if parts else str(values.get("email", "Imported lead")))[:200]


# ---------------------------------------------------------------- running
@dataclass
class RowOutcome:
    number: int
    action: str  # create | update | skip_duplicate | error
    values: dict[str, Any]
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    note: str | None = None


@dataclass
class RunResult:
    outcomes: list[RowOutcome]
    errors: list[dict[str, Any]]
    errors_truncated: bool
    created: int
    updated: int
    skipped: int
    failed: int
    suppressed: int


class _Run:
    def __init__(
        self,
        db: DbSession,
        ctx: WorkspaceContext,
        strategy: str,
        scorer: Scorer,
        filename: str,
        job: ImportJob | None,
    ) -> None:
        self.db, self.ctx, self.strategy, self.scorer = db, ctx, strategy, scorer
        self.filename, self.job = filename, job
        self.now: datetime = utcnow()
        self.companies_by_domain: dict[str, Company] = {}
        self.companies_by_name: dict[str, Company] = {}
        self.contacts_by_email: dict[str, Contact] = {}
        self.lead_by_contact: dict[uuid.UUID, Lead] = {}
        self.lead_ids_by_key: dict[tuple[str, uuid.UUID | None], uuid.UUID] = {}
        self.tags: dict[str, Tag] = {}
        self.first_row_for: dict[
            uuid.UUID, int
        ] = {}  # contact/lead ids created earlier in this file
        self.companies_cache: dict[uuid.UUID, Company] = {}

    # -- preload
    def load(self, emails: set[str]) -> None:
        wid = self.ctx.workspace_id
        companies = sorted(
            self.db.scalars(select(Company).where(Company.workspace_id == wid)),
            key=lambda c: (c.archived_at is None, c.created_at),
        )
        for c in companies:  # unarchived last, so they win name collisions
            self.companies_cache[c.id] = c
            if c.domain_normalized:
                self.companies_by_domain[c.domain_normalized] = c
            self.companies_by_name[key(c.name)] = c
        wanted = sorted(emails)
        for i in range(0, len(wanted), 500):
            for contact in self.db.scalars(
                select(Contact).where(
                    Contact.workspace_id == wid,
                    Contact.email_normalized.in_(wanted[i : i + 500]),
                )
            ):
                if contact.email_normalized:
                    self.contacts_by_email[contact.email_normalized] = contact
        if self.contacts_by_email:
            ids = [c.id for c in self.contacts_by_email.values()]
            for lead in self.db.scalars(
                select(Lead)
                .where(
                    Lead.workspace_id == wid, Lead.contact_id.in_(ids), Lead.archived_at.is_(None)
                )
                .order_by(Lead.created_at)
            ):
                if lead.contact_id:
                    self.lead_by_contact[lead.contact_id] = lead  # newest wins
        for lead_id, title, company_id in self.db.execute(
            select(Lead.id, Lead.title, Lead.company_id).where(
                Lead.workspace_id == wid, Lead.archived_at.is_(None)
            )
        ):
            self.lead_ids_by_key[(key(title), company_id)] = lead_id
        for tag in self.db.scalars(select(Tag).where(Tag.workspace_id == wid)):
            self.tags[tag.name_normalized] = tag

    # -- companies
    def match_company(self, values: dict[str, Any]) -> Company | None:
        website = values.get("website")
        if website:
            domain = normalize_website(website)[1]
            found = self.companies_by_domain.get(domain)
            if found:
                return found
        name = values.get("company")
        if name:
            found = self.companies_by_name.get(key(name))
            if found and website and found.domain_normalized:
                return None  # same name, different website: a different company
            return found
        return None

    def company_for(self, values: dict[str, Any], source: str) -> Company | None:
        existing = self.match_company(values)
        if existing is not None:
            return existing
        name = values.get("company")
        website = values.get("website")
        if not name and not website:
            return None
        company = crm.create_company(
            self.db,
            self.ctx,
            CompanyCreate(
                name=name or normalize_website(str(website))[1],
                website=website,
                industry=values.get("industry"),
                size_label=values.get("company_size"),
                location=values.get("location"),
                source=source,
            ),
            retrieved_at=self.now,
        )
        self.companies_cache[company.id] = company
        if company.domain_normalized:
            self.companies_by_domain[company.domain_normalized] = company
        self.companies_by_name[key(company.name)] = company
        return company

    # -- tags
    def apply_tags(self, lead: Lead, names: list[str]) -> None:
        if not names:
            return
        have = set(
            self.db.scalars(
                select(LeadTag.tag_id).where(
                    LeadTag.workspace_id == self.ctx.workspace_id, LeadTag.lead_id == lead.id
                )
            )
        )
        for name in names:
            tag = self.tags.get(key(name))
            if tag is None:
                tag = Tag(workspace_id=self.ctx.workspace_id, name=name, name_normalized=key(name))
                self.db.add(tag)
                self.db.flush()
                self.tags[tag.name_normalized] = tag
            if tag.id not in have:
                self.db.add(
                    LeadTag(workspace_id=self.ctx.workspace_id, lead_id=lead.id, tag_id=tag.id)
                )
                have.add(tag.id)

    # -- row handling
    def _details(self, number: int) -> dict[str, Any]:
        d: dict[str, Any] = {"file": self.filename[:100], "row": number}
        if self.job:
            d["import_id"] = str(self.job.id)
        return d

    def create_lead_for(
        self,
        values: dict[str, Any],
        number: int,
        source: str,
        contact: Contact | None,
        company: Company | None,
    ) -> Lead:
        status = values.get("status", "new")
        stage = lead_svc.stages_by_key(self.db, self.ctx).get(status)
        lead = Lead(
            workspace_id=self.ctx.workspace_id,
            company_id=company.id if company else None,
            contact_id=contact.id if contact else None,
            stage_id=stage.id if stage else None,
            title=derived_title(values),
            status=status,
            source=source,
            source_retrieved_at=self.now,
            industry=values.get("industry"),
            location=values.get("location"),
            notes=values.get("notes"),
            budget_signal=values.get("budget"),
            next_action=values.get("next_action"),
            owner_user_id=self.ctx.user.id,
            last_activity_at=self.now,
        )
        self.db.add(lead)
        self.db.flush()
        self.apply_tags(lead, values.get("tags", []))
        self.scorer.apply(lead, company)
        lead_svc.add_activity(
            self.db, self.ctx, lead, "system", "Imported from CSV",
            details=self._details(number), bump=False, when=self.now,
        )  # fmt: skip
        self.lead_ids_by_key[(key(lead.title), lead.company_id)] = lead.id
        if contact:
            self.lead_by_contact[contact.id] = lead
        return lead

    def update_existing(
        self, values: dict[str, Any], number: int, contact: Contact | None, lead: Lead | None
    ) -> None:
        company: Company | None = None
        if lead and lead.company_id:
            company = self.companies_cache.get(lead.company_id) or self.db.get(
                Company, lead.company_id
            )
        elif contact and contact.company_id:
            company = self.companies_cache.get(contact.company_id) or self.db.get(
                Company, contact.company_id
            )
        if contact:
            for src, attr in (("name", "full_name"), ("role", "role_title"), ("phone", "phone")):
                if values.get(src):
                    setattr(contact, attr, values[src])
        if company:
            for src, attr in (
                ("industry", "industry"),
                ("company_size", "size_label"),
                ("location", "location"),
            ):
                if values.get(src):
                    setattr(company, attr, values[src])
            if values.get("website") and not company.website:
                url, domain = normalize_website(values["website"])
                if domain not in self.companies_by_domain:
                    company.website, company.domain, company.domain_normalized = url, domain, domain
                    self.companies_by_domain[domain] = company
        if lead is None:
            return
        for src, attr in (
            ("industry", "industry"),
            ("location", "location"),
            ("notes", "notes"),
            ("budget", "budget_signal"),
            ("next_action", "next_action"),
        ):
            if values.get(src):
                setattr(lead, attr, values[src])
        status = values.get("status")
        if status and status != lead.status:
            stage = lead_svc.stages_by_key(self.db, self.ctx).get(status)
            lead.status = status
            lead.stage_id = stage.id if stage else lead.stage_id
            lead_svc.add_activity(
                self.db, self.ctx, lead, "stage_change", f"Moved to {status.capitalize()}",
                details={"to": status, **self._details(number)}, when=self.now,
            )  # fmt: skip
        self.apply_tags(lead, values.get("tags", []))
        self.scorer.apply(lead, company)
        lead_svc.add_activity(
            self.db, self.ctx, lead, "system", "Updated by CSV import",
            details=self._details(number), bump=False, when=self.now,
        )  # fmt: skip

    def process(self, row: CleanRow, suppressed: set[str]) -> RowOutcome:
        values = row.values
        out = RowOutcome(row.number, "create", values)
        email = values.get("email")
        if email and email in suppressed:
            out.warnings.append(
                "On your do-not-contact list: imported, but nothing will be sent to it."
            )
        source = values.get("source") or DEFAULT_SOURCE
        contact = self.contacts_by_email.get(email) if email else None
        company = self.match_company(values)
        lead: Lead | None = None
        duplicate = False
        if contact is not None:
            duplicate = True
            lead = self.lead_by_contact.get(contact.id)
            earlier = self.first_row_for.get(contact.id)
            out.note = (
                f"Same email as row {earlier} in this file."
                if earlier
                else f"A contact with {email} already exists."
            )
        elif not email:
            lead_id = self.lead_ids_by_key.get(
                (key(derived_title(values)), company.id if company else None)
            )
            if lead_id:
                duplicate = True
                lead = self.db.get(Lead, lead_id)
                earlier = self.first_row_for.get(lead_id)
                out.note = (
                    f"Same lead title and company as row {earlier} in this file."
                    if earlier
                    else "A lead with this title and company already exists."
                )
                if lead and lead.contact_id:
                    contact = self.db.get(Contact, lead.contact_id)
        if duplicate and self.strategy == "skip":
            out.action = "skip_duplicate"
            return out
        if duplicate:
            self.update_existing(values, row.number, contact, lead)
            if lead is None:  # known contact without an active lead: add one
                company = company or (
                    self.companies_cache.get(contact.company_id)
                    if contact and contact.company_id
                    else None
                )
                lead = self.create_lead_for(values, row.number, source, contact, company)
                out.note = (out.note or "") + " A new lead was added for them."
                self.first_row_for.setdefault(lead.id, row.number)
            out.action = "update"
            return out
        company = self.company_for(values, source)
        if values.get("name") or email:
            contact = crm.create_contact(
                self.db,
                self.ctx,
                ContactCreate(
                    full_name=values.get("name") or str(email).split("@")[0],
                    email=email,
                    role_title=values.get("role"),
                    phone=values.get("phone"),
                    company_id=company.id if company else None,
                    source=source,
                ),
                retrieved_at=self.now,
            )
            if email:
                self.contacts_by_email[email] = contact
            self.first_row_for[contact.id] = row.number
        lead = self.create_lead_for(values, row.number, source, contact, company)
        self.first_row_for[lead.id] = row.number
        return out


def run_import(
    db: DbSession,
    ctx: WorkspaceContext,
    parsed: ParsedCsv,
    resolved: dict[str, int],
    *,
    strategy: str,
    filename: str,
    scorer: Scorer,
    job: ImportJob | None,
) -> RunResult:
    rows = clean_rows(parsed, resolved)
    run = _Run(db, ctx, strategy, scorer, filename, job)
    emails = {r.values["email"] for r in rows if not r.issues and r.values.get("email")}
    run.load(emails)
    suppressed = crm.suppressed_among(db, ctx, emails)
    outcomes: list[RowOutcome] = []
    errors: list[dict[str, Any]] = []
    truncated = False
    counts = {"create": 0, "update": 0, "skip_duplicate": 0, "error": 0}

    def note(row: int, column: str, message: str, value: str, kind: str) -> None:
        nonlocal truncated
        if len(errors) >= MAX_STORED_ERRORS:
            truncated = True
            return
        errors.append(
            {"row": row, "column": column, "message": message, "value": value, "kind": kind}
        )

    for row in rows:
        if row.issues:
            outcome = RowOutcome(
                row.number, "error", row.values, issues=[m for _, m, _ in row.issues]
            )
            for column, message, raw in row.issues:
                note(row.number, column, message, raw, "error")
        else:
            outcome = run.process(row, suppressed)
            if outcome.action == "skip_duplicate":
                note(row.number, "", outcome.note or "Duplicate", "", "skipped")
        counts[outcome.action] += 1
        outcomes.append(outcome)
    db.flush()
    return RunResult(
        outcomes=outcomes,
        errors=errors,
        errors_truncated=truncated,
        created=counts["create"],
        updated=counts["update"],
        skipped=counts["skip_duplicate"],
        failed=counts["error"],
        suppressed=sum(1 for r in rows if not r.issues and r.values.get("email") in suppressed),
    )
