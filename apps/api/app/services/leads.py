"""Leads: creation and editing rules, pipeline-stage association, activity timeline, tags and serialisation."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from app.clock import utcnow
from app.db.models_crm import (
    Activity,
    Company,
    Contact,
    Lead,
    LeadTag,
    PipelineStage,
    Tag,
)
from app.deps import WorkspaceContext
from app.domain import LEAD_STATUSES
from app.errors import AppError
from app.schemas.leads import (
    CompanyRef,
    ContactCreate,
    ContactRef,
    LeadCreate,
    LeadDetail,
    LeadOut,
    LeadPatch,
    StageRef,
    TagRef,
)
from app.services import crm
from app.services.fit_scoring import Scorer
from app.services.pipeline import ensure_default_stages

# Changing any of these changes the score, so it is recomputed.
SCORING_FIELDS = frozenset(
    {"title", "notes", "industry", "location", "budget_signal", "company_id"}
)
SOURCE_MANUAL = "manual"


# ---------------------------------------------------------------- stages
def stages_by_key(db: DbSession, ctx: WorkspaceContext) -> dict[str, PipelineStage]:
    stages = list(
        db.scalars(select(PipelineStage).where(PipelineStage.workspace_id == ctx.workspace_id))
    )
    if not stages:  # workspaces created before stages existed
        stages = ensure_default_stages(db, ctx.workspace_id)
    return {s.key: s for s in stages}


# ---------------------------------------------------------------- activities
def add_activity(
    db: DbSession,
    ctx: WorkspaceContext,
    lead: Lead,
    kind: str,
    summary: str,
    *,
    body: str | None = None,
    details: dict[str, Any] | None = None,
    actor: bool = True,
    bump: bool = True,
    when: datetime | None = None,
    opportunity_id: uuid.UUID | None = None,
) -> Activity:
    now = when or utcnow()
    activity = Activity(
        workspace_id=ctx.workspace_id,
        lead_id=lead.id,
        opportunity_id=opportunity_id,
        actor_user_id=ctx.user.id if actor else None,
        kind=kind,
        summary=summary[:500],
        body=body,
        details=details or {},
        occurred_at=now,
    )
    db.add(activity)
    if bump:
        lead.last_activity_at = now
    return activity


# ---------------------------------------------------------------- tags
def require_tags(
    db: DbSession, ctx: WorkspaceContext, tag_ids: Sequence[uuid.UUID], field: str
) -> list[Tag]:
    unique = list(dict.fromkeys(tag_ids))
    if not unique:
        return []
    tags = list(
        db.scalars(select(Tag).where(Tag.workspace_id == ctx.workspace_id, Tag.id.in_(unique)))
    )
    if len(tags) != len(unique):
        raise AppError(
            422, "validation_error", "Some fields are invalid.", fields={field: "Tag not found."}
        )
    return tags


def set_tags(
    db: DbSession, ctx: WorkspaceContext, lead: Lead, tag_ids: Sequence[uuid.UUID]
) -> None:
    wanted = {t.id for t in require_tags(db, ctx, tag_ids, "tag_ids")}
    have = set(
        db.scalars(
            select(LeadTag.tag_id).where(
                LeadTag.workspace_id == ctx.workspace_id, LeadTag.lead_id == lead.id
            )
        )
    )
    if have - wanted:
        db.execute(
            delete(LeadTag).where(
                LeadTag.workspace_id == ctx.workspace_id,
                LeadTag.lead_id == lead.id,
                LeadTag.tag_id.in_(have - wanted),
            )
        )
    for tag_id in wanted - have:
        db.add(LeadTag(workspace_id=ctx.workspace_id, lead_id=lead.id, tag_id=tag_id))
    db.flush()


def bulk_tags(
    db: DbSession,
    ctx: WorkspaceContext,
    lead_ids: Sequence[uuid.UUID],
    add: Sequence[uuid.UUID],
    remove: Sequence[uuid.UUID],
) -> tuple[int, int, int]:
    """Add/remove tags on many leads. Returns ``(leads, tags_added, tags_removed)``."""
    ids = list(dict.fromkeys(lead_ids))
    found = set(
        db.scalars(select(Lead.id).where(Lead.workspace_id == ctx.workspace_id, Lead.id.in_(ids)))
    )
    if found != set(ids):
        raise AppError(404, "lead_not_found", "One or more leads were not found.")
    require_tags(db, ctx, add, "add_tag_ids")
    require_tags(db, ctx, remove, "remove_tag_ids")
    existing = {
        (row[0], row[1])
        for row in db.execute(
            select(LeadTag.lead_id, LeadTag.tag_id).where(
                LeadTag.workspace_id == ctx.workspace_id, LeadTag.lead_id.in_(ids)
            )
        )
    }
    added = 0
    for lead_id in ids:
        for tag_id in dict.fromkeys(add):
            if (lead_id, tag_id) not in existing:
                db.add(LeadTag(workspace_id=ctx.workspace_id, lead_id=lead_id, tag_id=tag_id))
                added += 1
    removed = 0
    for lead_id in ids:
        for tag_id in dict.fromkeys(remove):
            if (lead_id, tag_id) in existing:
                removed += 1
    if remove:
        db.execute(
            delete(LeadTag).where(
                LeadTag.workspace_id == ctx.workspace_id,
                LeadTag.lead_id.in_(ids),
                LeadTag.tag_id.in_(list(remove)),
            )
        )
    db.flush()
    return len(ids), added, removed


# ---------------------------------------------------------------- create / update
def _status_stage(db: DbSession, ctx: WorkspaceContext, status: str) -> PipelineStage | None:
    return stages_by_key(db, ctx).get(status)


def resolve_company_and_contact(
    db: DbSession, ctx: WorkspaceContext, body: LeadCreate
) -> tuple[Company | None, Contact | None]:
    company: Company | None = None
    contact: Contact | None = None
    if body.company_id:
        company = crm.require_company(db, ctx, body.company_id)
    elif body.company_name or body.company_website:
        company, _ = crm.find_or_create_company(
            db,
            ctx,
            name=body.company_name,
            website=body.company_website,
            source=body.source or SOURCE_MANUAL,
        )
    if body.contact_id:
        contact = crm.require_contact(db, ctx, body.contact_id)
    elif body.contact_email or body.contact_name:
        if body.contact_email:
            contact = crm.contact_by_email(db, ctx, body.contact_email)
        if contact is None:
            if not body.contact_name:
                raise AppError(
                    422,
                    "validation_error",
                    "Some fields are invalid.",
                    fields={"contact_name": "Enter the contact's name."},
                )
            contact = crm.create_contact(
                db,
                ctx,
                ContactCreate(
                    full_name=body.contact_name,
                    email=body.contact_email,
                    company_id=company.id if company else None,
                    source=body.source or SOURCE_MANUAL,
                ),
            )
    if company is None and contact is not None and contact.company_id:
        company = db.get(Company, contact.company_id)
    return company, contact


def create_lead(db: DbSession, ctx: WorkspaceContext, body: LeadCreate, scorer: Scorer) -> Lead:
    company, contact = resolve_company_and_contact(db, ctx, body)
    tags = require_tags(db, ctx, body.tag_ids, "tag_ids")
    stage = _status_stage(db, ctx, body.status)
    now = utcnow()
    lead = Lead(
        workspace_id=ctx.workspace_id,
        company_id=company.id if company else None,
        contact_id=contact.id if contact else None,
        stage_id=stage.id if stage else None,
        title=body.title,
        status=body.status,
        source=body.source or SOURCE_MANUAL,
        industry=body.industry,
        location=body.location,
        notes=body.notes,
        budget_signal=body.budget_signal,
        next_action=body.next_action,
        next_action_at=body.next_action_at,
        owner_user_id=ctx.user.id,
        last_activity_at=now,
    )
    db.add(lead)
    db.flush()
    for tag in tags:
        db.add(LeadTag(workspace_id=ctx.workspace_id, lead_id=lead.id, tag_id=tag.id))
    scorer.apply(lead, company)
    add_activity(
        db, ctx, lead, "system", "Lead created", details={"source": lead.source}, bump=False
    )
    db.flush()
    return lead


def _check_status_stage(
    db: DbSession, ctx: WorkspaceContext, lead: Lead, changes: dict[str, Any]
) -> tuple[str, uuid.UUID | None]:
    """Resolve the status/stage pair after a patch. A stage named like a status drives the status."""
    status = changes.get("status", lead.status)
    stage_id = lead.stage_id
    if changes.get("stage_id") is not None:
        stage = db.scalar(
            select(PipelineStage).where(
                PipelineStage.workspace_id == ctx.workspace_id,
                PipelineStage.id == changes["stage_id"],
            )
        )
        if stage is None:
            raise crm.invalid_ref("stage_id", "Stage")
        if stage.key in LEAD_STATUSES:
            if "status" in changes and changes["status"] != stage.key:
                raise AppError(
                    422,
                    "validation_error",
                    "Some fields are invalid.",
                    fields={"status": "Doesn't match the chosen stage."},
                )
            status = stage.key
        stage_id = stage.id
    elif "status" in changes and changes["status"] != lead.status:
        stage = _status_stage(db, ctx, changes["status"])
        stage_id = stage.id if stage else None
    return status, stage_id


def update_lead(
    db: DbSession, ctx: WorkspaceContext, lead: Lead, body: LeadPatch, scorer: Scorer
) -> list[str]:
    crm.ensure_editable(lead.archived_at, "lead")
    changes = body.model_dump(exclude_unset=True)
    for required in ("title", "status"):
        if required in changes and changes[required] is None:
            changes.pop(required)
    if "company_id" in changes and changes["company_id"] is not None:
        crm.require_company(db, ctx, changes["company_id"])
    if "contact_id" in changes and changes["contact_id"] is not None:
        crm.require_contact(db, ctx, changes["contact_id"])

    old_status, old_stage = lead.status, lead.stage_id
    status, stage_id = _check_status_stage(db, ctx, lead, changes)
    changes.pop("stage_id", None)
    changes.pop("status", None)
    changed = [name for name, value in changes.items() if getattr(lead, name) != value]
    for name, value in changes.items():
        setattr(lead, name, value)
    if status != old_status or stage_id != old_stage:
        stages = {s.id: s for s in stages_by_key(db, ctx).values()}
        lead.status, lead.stage_id = status, stage_id
        old_key = stages[old_stage].key if old_stage in stages else old_status
        new_key = stages[stage_id].key if stage_id in stages else status
        changed.append("status" if status != old_status else "stage_id")
        add_activity(
            db,
            ctx,
            lead,
            "stage_change",
            f"Moved to {stages[stage_id].name if stage_id in stages else status.capitalize()}",
            details={"from": old_key, "to": new_key},
        )
    if SCORING_FIELDS & set(changed):
        company = db.get(Company, lead.company_id) if lead.company_id else None
        scorer.apply(lead, company)
    db.flush()
    return sorted(set(changed))


# ---------------------------------------------------------------- serialisation
def _band(lead: Lead) -> str | None:
    e = lead.fit_explanation
    if isinstance(e, dict) and e.get("version") == 1:
        band = e.get("band")
        return band if isinstance(band, str) else None
    return None


def lead_outs(db: DbSession, ctx: WorkspaceContext, leads: Sequence[Lead]) -> list[LeadOut]:
    if not leads:
        return []
    ids = [lead.id for lead in leads]
    stages = {s.id: s for s in stages_by_key(db, ctx).values()}
    company_ids = {lead.company_id for lead in leads if lead.company_id}
    contact_ids = {lead.contact_id for lead in leads if lead.contact_id}
    companies = (
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
    contacts = (
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
    tags: dict[uuid.UUID, list[TagRef]] = {}
    for lead_id, tag in db.execute(
        select(LeadTag.lead_id, Tag)
        .join(Tag, (Tag.workspace_id == LeadTag.workspace_id) & (Tag.id == LeadTag.tag_id))
        .where(LeadTag.workspace_id == ctx.workspace_id, LeadTag.lead_id.in_(ids))
        .order_by(Tag.name_normalized)
    ):
        tags.setdefault(lead_id, []).append(TagRef(id=tag.id, name=tag.name, color=tag.color))
    blocked = crm.suppressed_among(db, ctx, (c.email_normalized for c in contacts.values()))
    out: list[LeadOut] = []
    for lead in leads:
        stage = stages.get(lead.stage_id) if lead.stage_id else None
        company = companies.get(lead.company_id) if lead.company_id else None
        contact = contacts.get(lead.contact_id) if lead.contact_id else None
        out.append(
            LeadOut(
                id=lead.id,
                title=lead.title,
                status=lead.status,
                stage=StageRef(id=stage.id, key=stage.key, name=stage.name) if stage else None,
                company=CompanyRef(id=company.id, name=company.name) if company else None,
                contact=ContactRef(id=contact.id, full_name=contact.full_name, email=contact.email)
                if contact
                else None,
                source=lead.source,
                source_retrieved_at=lead.source_retrieved_at,
                industry=lead.industry,
                location=lead.location,
                notes=lead.notes,
                budget_signal=lead.budget_signal,
                fit_score=lead.fit_score,
                fit_band=_band(lead),
                fit_scored_at=lead.fit_scored_at,
                next_action=lead.next_action,
                next_action_at=lead.next_action_at,
                last_activity_at=lead.last_activity_at,
                is_sample=lead.is_sample,
                archived_at=lead.archived_at,
                tags=tags.get(lead.id, []),
                do_not_contact=bool(
                    contact and contact.email_normalized and contact.email_normalized in blocked
                ),
                created_at=lead.created_at,
                updated_at=lead.updated_at,
            )
        )
    return out


def lead_detail(db: DbSession, ctx: WorkspaceContext, lead: Lead, scorer: Scorer) -> LeadDetail:
    base = lead_outs(db, ctx, [lead])[0]
    return LeadDetail(
        **base.model_dump(),
        fit_explanation=lead.fit_explanation if _band(lead) else None,
        fit_stale=scorer.is_stale(lead),
    )
