"""Freelancer profile: reading, partial updates with optimistic concurrency, completeness and the
public-facing summary preview. Everything shown comes from fields the freelancer entered; nothing is
generated or inferred."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session as DbSession

from app.clock import utcnow
from app.db.models import FreelancerProfile
from app.deps import WorkspaceContext
from app.errors import AppError
from app.schemas.profile import (
    Completeness,
    MissingField,
    ProfileOut,
    ProfilePatch,
    ProfileSummary,
    SummarySection,
)

FIELD_LABELS: dict[str, str] = {
    "role_title": "Role",
    "summary": "Summary",
    "services": "Services",
    "skills": "Skills",
    "industries": "Industries",
    "differentiators": "What sets you apart",
    "excluded_customers": "Clients you don't take",
    "target_clients": "Ideal clients",
    "portfolio_urls": "Portfolio links",
    "years_experience": "Years of experience",
    "experience_summary": "Experience highlights",
    "pricing_guidance": "Pricing guidance",
    "preferred_cta": "Preferred call to action",
    "tone": "Tone of voice",
}
# Needed for useful drafts; the rest improves them. Missing items are flagged, never guessed.
NEEDED = ("role_title", "services", "target_clients", "tone")
RECOMMENDED = (
    "skills",
    "differentiators",
    "preferred_cta",
    "portfolio_urls",
    "years_experience",
    "pricing_guidance",
)
# Never shown in the public summary.
PRIVATE_FIELDS = (
    "pricing_guidance",
    "excluded_customers",
    "tone_notes",
    "business_goal",
    "business_goal_notes",
)
_TEXT_FIELDS = {
    "role_title",
    "summary",
    "target_clients",
    "experience_summary",
    "pricing_guidance",
    "preferred_cta",
    "tone_notes",
    "business_goal_notes",
}


def get_profile(db: DbSession, ctx: WorkspaceContext) -> FreelancerProfile:
    profile = db.scalar(
        select(FreelancerProfile).where(FreelancerProfile.workspace_id == ctx.workspace_id)
    )
    if profile is None:  # accounts created before profiles existed, or tests
        profile = FreelancerProfile(workspace_id=ctx.workspace_id)
        db.add(profile)
        db.flush()
    return profile


def is_filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str | list):
        return len(value) > 0
    return True


def completeness(profile: FreelancerProfile) -> Completeness:
    missing = [
        MissingField(field=f, label=FIELD_LABELS[f], importance="needed")
        for f in NEEDED
        if not is_filled(getattr(profile, f))
    ] + [
        MissingField(field=f, label=FIELD_LABELS[f], importance="recommended")
        for f in RECOMMENDED
        if not is_filled(getattr(profile, f))
    ]
    total = len(NEEDED) + len(RECOMMENDED)
    return Completeness(filled=total - len(missing), total=total, missing=missing)


def to_out(profile: FreelancerProfile, ctx: WorkspaceContext) -> ProfileOut:
    data = {c: getattr(profile, c) for c in ProfileOut.model_fields if hasattr(profile, c)}
    return ProfileOut(**data, timezone=ctx.workspace.timezone, completeness=completeness(profile))


def apply_patch(
    db: DbSession, ctx: WorkspaceContext, patch: ProfilePatch
) -> tuple[FreelancerProfile, list[str]]:
    """Apply a partial update. Returns the profile and the names of the fields that really changed.

    No change => no new version. A stale ``expected_version`` is a 409; the write itself is a
    compare-and-set on ``version`` so two concurrent saves cannot silently overwrite each other.
    """
    profile = get_profile(db, ctx)
    data = patch.model_dump(exclude_unset=True)
    expected = data.pop("expected_version", None)
    if expected is not None and expected != profile.version:
        raise AppError(
            409,
            "stale_version",
            "Your profile changed since you opened it. Reload to see the latest version.",
        )

    changes: dict[str, Any] = {}
    for field, value in data.items():
        if field in _TEXT_FIELDS and value == "":
            value = None
        if field in (
            "services",
            "skills",
            "industries",
            "differentiators",
            "excluded_customers",
            "portfolio_urls",
        ):
            value = list(value or [])
        if getattr(profile, field) != value:
            changes[field] = value
    if not changes:
        return profile, []

    result = db.execute(
        update(FreelancerProfile)
        .where(
            FreelancerProfile.id == profile.id,
            FreelancerProfile.workspace_id == ctx.workspace_id,
            FreelancerProfile.version == profile.version,
        )
        .values(**changes, version=profile.version + 1, updated_at=utcnow())
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        raise AppError(
            409,
            "stale_version",
            "Your profile was changed by another request. Reload and try again.",
        )
    db.expire(profile)
    return profile, sorted(changes)


def build_summary(profile: FreelancerProfile) -> ProfileSummary:
    """Compose the public-facing professional summary from entered fields only.

    Rules: nothing is invented, rephrased or inferred. Empty fields are left out and listed under
    ``omitted`` so the freelancer can fill them in. Private fields never appear.
    """
    sections: list[SummarySection] = []

    def add(title: str, items: list[str]) -> None:
        if items:
            sections.append(SummarySection(title=title, items=items))

    add("Services", list(profile.services))
    add("Skills", list(profile.skills))
    add("Industries", list(profile.industries))
    if profile.target_clients:
        add("Who I work with", [profile.target_clients])
    add("What sets me apart", list(profile.differentiators))
    experience: list[str] = []
    if profile.years_experience is not None:
        experience.append(f"{profile.years_experience} years of experience")
    if profile.experience_summary:
        experience.append(profile.experience_summary)
    add("Experience", experience)
    if profile.preferred_cta:
        add("Get in touch", [profile.preferred_cta])

    omitted = [
        MissingField(
            field=f, label=FIELD_LABELS[f], importance="needed" if f in NEEDED else "recommended"
        )
        for f in (*NEEDED, *RECOMMENDED)
        if f not in PRIVATE_FIELDS and not is_filled(getattr(profile, f))
    ]
    return ProfileSummary(
        headline=profile.role_title or None,
        intro=profile.summary or None,
        sections=sections,
        links=list(profile.portfolio_urls),
        omitted=omitted,
        profile_version=profile.version,
        private_fields_excluded=[
            FIELD_LABELS.get(f, f) for f in PRIVATE_FIELDS if f in FIELD_LABELS
        ],
    )
