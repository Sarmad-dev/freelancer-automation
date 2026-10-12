"""Rule-based lead fit scoring.

Deliberately simple and explainable (no model, no network): each enabled criterion looks at data the freelancer
entered, produces ``match`` / ``partial`` / ``miss`` / ``unknown`` and the evidence that decided it. Unknown
criteria are left out of the maths rather than counted as misses, the score is rounded to the nearest 5, and when
too little is known there is no number at all ("insufficient information") instead of a falsely precise one.
"""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.clock import utcnow
from app.db.models import FreelancerProfile
from app.db.models_crm import Company, FitScoringConfig, Lead
from app.deps import WorkspaceContext
from app.domain import COMPANY_SIZES
from app.schemas.fit import FitConfigIn
from app.services.profile import get_profile

EXPLANATION_VERSION = 1
BAND_STRONG = 70
BAND_POSSIBLE = 45
MIN_CONFIDENCE = 0.5
MIN_KNOWN_CRITERIA = 2
ROUND_TO = 5
EXCLUDED_CAP = 25

DEFAULT_CRITERIA: list[dict[str, Any]] = [
    {"key": "service_match", "enabled": True, "weight": 5, "keywords": []},
    {"key": "industry", "enabled": True, "weight": 3, "preferred": [], "avoid": []},
    {"key": "geography", "enabled": True, "weight": 1, "preferred": []},
    {"key": "company_size", "enabled": True, "weight": 1, "preferred": []},
    {"key": "budget", "enabled": True, "weight": 2},
]

LABELS = {
    "service_match": "Service match",
    "industry": "Industry",
    "geography": "Geography",
    "company_size": "Company size",
    "budget": "Budget signal",
}
_VALUE = {"match": 1.0, "partial": 0.5, "miss": 0.0}
_STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "into",
        "is",
        "it",
        "of",
        "on",
        "or",
        "our",
        "the",
        "their",
        "to",
        "with",
        "your",
        "service",
        "services",
        "work",
        "project",
        "projects",
    ]
)
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


# ---------------------------------------------------------------- text matching
def _stem(word: str) -> str:
    for suffix in ("ing", "ers", "ies", "er", "es", "ed", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def stems(text: str) -> set[str]:
    return {_stem(w) for w in _WORD.findall(text.casefold())}


def _phrase_stems(phrase: str) -> set[str]:
    return {_stem(w) for w in _WORD.findall(phrase.casefold()) if w not in _STOP}


def phrase_in(phrase: str, text_stems: set[str]) -> bool:
    """Every significant word of ``phrase`` appears (whole word, light stemming) in the text."""
    need = _phrase_stems(phrase)
    return bool(need) and need <= text_stems


# ---------------------------------------------------------------- inputs
@dataclass(frozen=True)
class ProfileFacts:
    services: tuple[str, ...]
    skills: tuple[str, ...]
    industries: tuple[str, ...]
    excluded_customers: tuple[str, ...]
    version: int


@dataclass(frozen=True)
class LeadFacts:
    title: str
    notes: str | None
    industry: str | None
    location: str | None
    budget_signal: str | None
    company_name: str | None
    company_notes: str | None
    company_industry: str | None
    company_location: str | None
    company_size: str | None


def profile_facts(profile: FreelancerProfile) -> ProfileFacts:
    return ProfileFacts(
        services=tuple(profile.services or []),
        skills=tuple(profile.skills or []),
        industries=tuple(profile.industries or []),
        excluded_customers=tuple(profile.excluded_customers or []),
        version=profile.version,
    )


def lead_facts(lead: Lead, company: Company | None) -> LeadFacts:
    return LeadFacts(
        title=lead.title,
        notes=lead.notes,
        industry=lead.industry,
        location=lead.location,
        budget_signal=lead.budget_signal,
        company_name=company.name if company else None,
        company_notes=company.notes if company else None,
        company_industry=company.industry if company else None,
        company_location=company.location if company else None,
        company_size=company.size_label if company else None,
    )


# ---------------------------------------------------------------- criteria
def _result(
    key: str,
    weight: int,
    outcome: str,
    reason: str,
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": LABELS[key],
        "weight": weight,
        "outcome": outcome,
        "points": weight * _VALUE.get(outcome, 0.0),
        "reason": reason,
        "evidence": evidence or [],
    }


def _text_fields(lead: LeadFacts) -> list[tuple[str, str]]:
    fields = [
        ("Lead title", lead.title),
        ("Lead notes", lead.notes or ""),
        ("Company notes", lead.company_notes or ""),
    ]
    return [(label, text) for label, text in fields if text.strip()]


def _service_match(c: dict[str, Any], lead: LeadFacts, profile: ProfileFacts) -> dict[str, Any]:
    w = c["weight"]
    fields = [(label, stems(text)) for label, text in _text_fields(lead)]
    wanted = [*profile.services, *c.get("keywords", [])]
    if not fields:
        return _result("service_match", w, "unknown", "The lead has no title or notes to compare.")
    if not wanted and not profile.skills:
        return _result(
            "service_match",
            w,
            "unknown",
            "Add services to your profile or keywords here so leads can be compared.",
        )
    hits = [
        {"field": label, "value": phrase, "note": "matches a service or keyword you listed"}
        for phrase in wanted
        for label, text_stems in fields
        if phrase_in(phrase, text_stems)
    ]
    if hits:
        return _result("service_match", w, "match", "The lead mentions work you offer.", hits[:5])
    skill_hits = [
        {"field": label, "value": skill, "note": "matches a skill in your profile"}
        for skill in profile.skills
        for label, text_stems in fields
        if phrase_in(skill, text_stems)
    ]
    if skill_hits:
        return _result(
            "service_match",
            w,
            "partial",
            "Only one of your skills is mentioned, not a service you sell.",
            skill_hits[:5],
        )
    return _result(
        "service_match",
        w,
        "miss",
        "Nothing in the lead's text matches your services, keywords or skills. "
        "Keyword matching can't read between the lines: add keywords if this is a false miss.",
    )


def _any_phrase(value: str, phrases: list[str] | tuple[str, ...]) -> str | None:
    value_stems = stems(value)
    return next((p for p in phrases if phrase_in(p, value_stems)), None)


def _industry(c: dict[str, Any], lead: LeadFacts, profile: ProfileFacts) -> dict[str, Any]:
    w = c["weight"]
    if lead.industry:
        value, field = lead.industry, "Lead industry"
    elif lead.company_industry:
        value, field = lead.company_industry, "Company industry"
    else:
        return _result("industry", w, "unknown", "No industry is recorded for this lead.")
    evidence = [{"field": field, "value": value}]
    avoided = _any_phrase(value, c.get("avoid", []))
    if avoided:
        evidence.append({"field": "Your avoid list", "value": avoided})
        return _result("industry", w, "miss", "This industry is on your avoid list.", evidence)
    preferred = c.get("preferred") or list(profile.industries)
    if not preferred:
        return _result(
            "industry",
            w,
            "unknown",
            "No preferred industries are set here or in your profile.",
            evidence,
        )
    matched = _any_phrase(value, preferred)
    if matched:
        evidence.append({"field": "Your preferred industries", "value": matched})
        return _result("industry", w, "match", "An industry you prefer.", evidence)
    return _result("industry", w, "miss", "Not one of your preferred industries.", evidence)


def _geography(c: dict[str, Any], lead: LeadFacts) -> dict[str, Any]:
    w = c["weight"]
    value = lead.location or lead.company_location
    field = "Lead location" if lead.location else "Company location"
    if not value:
        return _result("geography", w, "unknown", "No location is recorded for this lead.")
    preferred = c.get("preferred", [])
    if not preferred:
        return _result(
            "geography",
            w,
            "unknown",
            "No preferred places are set.",
            [{"field": field, "value": value}],
        )
    matched = _any_phrase(value, preferred)
    evidence = [{"field": field, "value": value}]
    if matched:
        evidence.append({"field": "Your preferred places", "value": matched})
        return _result("geography", w, "match", "A place you prefer.", evidence)
    return _result("geography", w, "miss", "Not one of your preferred places.", evidence)


def _company_size(c: dict[str, Any], lead: LeadFacts) -> dict[str, Any]:
    w = c["weight"]
    size = lead.company_size
    if not size or size not in COMPANY_SIZES:
        return _result("company_size", w, "unknown", "No company size is recorded.")
    preferred = [p for p in c.get("preferred", []) if p in COMPANY_SIZES]
    evidence = [{"field": "Company size", "value": size}]
    if not preferred:
        return _result(
            "company_size", w, "unknown", "No preferred company sizes are set.", evidence
        )
    if size in preferred:
        return _result("company_size", w, "match", "A company size you prefer.", evidence)
    index = COMPANY_SIZES.index(size)
    if any(abs(COMPANY_SIZES.index(p) - index) == 1 for p in preferred):
        return _result("company_size", w, "partial", "Next to a size you prefer.", evidence)
    return _result("company_size", w, "miss", "Not a size you prefer.", evidence)


def _budget(c: dict[str, Any], lead: LeadFacts) -> dict[str, Any]:
    w = c["weight"]
    signal = lead.budget_signal
    if signal is None:
        return _result("budget", w, "unknown", "You haven't recorded a budget signal.")
    evidence = [{"field": "Budget signal (set by you)", "value": signal}]
    outcome = {"high": "match", "medium": "partial", "low": "miss"}[signal]
    return _result("budget", w, outcome, f"You marked the budget as {signal}.", evidence)


def _excluded(lead: LeadFacts, profile: ProfileFacts) -> list[str]:
    haystack = " ".join(
        t
        for t in (
            lead.title,
            lead.notes,
            lead.industry,
            lead.company_name,
            lead.company_notes,
            lead.company_industry,
        )
        if t
    )
    found = _any_phrase_all(haystack, profile.excluded_customers)
    return [f"Mentions “{p}”, a client type you said you don't take." for p in found]


def _any_phrase_all(text: str, phrases: tuple[str, ...]) -> list[str]:
    text_stems = stems(text)
    return [p for p in phrases if phrase_in(p, text_stems)]


# ---------------------------------------------------------------- scoring
def band_for(score: int | None) -> str:
    if score is None:
        return "insufficient"
    if score >= BAND_STRONG:
        return "strong"
    if score >= BAND_POSSIBLE:
        return "possible"
    return "weak"


def _round(raw: float) -> int:
    return int(math.floor(raw / ROUND_TO + 0.5) * ROUND_TO)


def _summary(
    results: list[dict[str, Any]], known: int, total: int, band: str, capped: bool = False
) -> str:
    def names(outcomes: tuple[str, ...]) -> str:
        return ", ".join(r["label"].lower() for r in results if r["outcome"] in outcomes)

    if band == "insufficient":
        missing = names(("unknown",))
        return f"Not enough information to score yet. Still unknown: {missing or 'everything'}."
    parts = [f"Based on {known} of {len(results)} criteria."]
    if good := names(("match",)):
        parts.append(f"Matches: {good}.")
    if mixed := names(("partial",)):
        parts.append(f"Partly: {mixed}.")
    if bad := names(("miss",)):
        parts.append(f"Doesn't match: {bad}.")
    if unknown := names(("unknown",)):
        parts.append(f"Unknown: {unknown}.")
    if capped:
        parts.append(f"Limited to {EXCLUDED_CAP} because it mentions a client type you don't take.")
    return " ".join(parts)


def score(
    lead: LeadFacts,
    profile: ProfileFacts,
    criteria: list[dict[str, Any]],
    *,
    config_version: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for c in criteria:
        if not c.get("enabled", True):
            continue
        key = c["key"]
        if key == "service_match":
            results.append(_service_match(c, lead, profile))
        elif key == "industry":
            results.append(_industry(c, lead, profile))
        elif key == "geography":
            results.append(_geography(c, lead))
        elif key == "company_size":
            results.append(_company_size(c, lead))
        elif key == "budget":
            results.append(_budget(c, lead))
    total = sum(r["weight"] for r in results)
    known_results = [r for r in results if r["outcome"] != "unknown"]
    known_weight = sum(r["weight"] for r in known_results)
    confidence = known_weight / total if total else 0.0

    value: int | None = None
    if len(known_results) >= MIN_KNOWN_CRITERIA and confidence >= MIN_CONFIDENCE:
        value = _round(100 * sum(r["points"] for r in known_results) / known_weight)
    warnings = _excluded(lead, profile)
    capped = False
    if warnings and value is not None and value > EXCLUDED_CAP:
        value, capped = EXCLUDED_CAP, True
    band = band_for(value)
    return {
        "version": EXPLANATION_VERSION,
        "method": "rules",
        "computed_at": (now or utcnow()).isoformat(),
        "config_version": config_version,
        "profile_version": profile.version,
        "score": value,
        "band": band,
        "confidence": round(confidence, 2),
        "known_weight": known_weight,
        "total_weight": total,
        "capped": capped,
        "summary": _summary(results, len(known_results), len(results), band, capped),
        "warnings": warnings,
        "criteria": results,
    }


# ---------------------------------------------------------------- persistence
def current_config(
    db: DbSession, ctx: WorkspaceContext
) -> tuple[int, list[dict[str, Any]], datetime | None]:
    """``(version, criteria, updated_at)``; version 0 means the built-in defaults were never saved."""
    row = db.scalar(
        select(FitScoringConfig).where(FitScoringConfig.workspace_id == ctx.workspace_id)
    )
    if row is None:
        return 0, [dict(c) for c in DEFAULT_CRITERIA], None
    return row.version, list(row.criteria), row.updated_at


@dataclass(frozen=True)
class Scorer:
    """Config and profile loaded once, so many leads (imports, rescoring) cost no extra queries."""

    profile: ProfileFacts
    criteria: list[dict[str, Any]]
    config_version: int

    @classmethod
    def load(cls, db: DbSession, ctx: WorkspaceContext) -> Scorer:
        version, criteria, _ = current_config(db, ctx)
        return cls(profile_facts(get_profile(db, ctx)), criteria, version)

    def apply(self, lead: Lead, company: Company | None) -> None:
        explanation = score(
            lead_facts(lead, company),
            self.profile,
            self.criteria,
            config_version=self.config_version,
        )
        lead.fit_score = explanation["score"]
        lead.fit_explanation = explanation
        lead.fit_scored_at = utcnow()

    def is_stale(self, lead: Lead) -> bool:
        e = lead.fit_explanation
        if not isinstance(e, dict) or e.get("version") != EXPLANATION_VERSION:
            return lead.fit_explanation is not None
        return (
            e.get("config_version") != self.config_version
            or e.get("profile_version") != self.profile.version
        )


def save_config(
    db: DbSession, ctx: WorkspaceContext, body: FitConfigIn
) -> tuple[FitScoringConfig, bool]:
    """Persist the criteria. Returns ``(row, changed)``; the version only moves when something changed."""
    criteria = [c.model_dump(mode="json") for c in body.criteria]
    order = {k: i for i, k in enumerate(LABELS)}
    criteria.sort(key=lambda c: order[c["key"]])
    row = db.scalar(
        select(FitScoringConfig).where(FitScoringConfig.workspace_id == ctx.workspace_id)
    )
    if row is None:
        row = FitScoringConfig(
            workspace_id=ctx.workspace_id,
            version=1,
            criteria=criteria,
            updated_by_user_id=ctx.user.id,
        )
        db.add(row)
        db.flush()
        return row, True
    if row.criteria == criteria:
        return row, False
    row.version += 1
    row.criteria = criteria
    row.updated_by_user_id = ctx.user.id
    db.flush()
    return row, True


def rescore_all(db: DbSession, ctx: WorkspaceContext, scorer: Scorer | None = None) -> int:
    scorer = scorer or Scorer.load(db, ctx)
    companies: dict[uuid.UUID, Company] = {}
    count = 0
    leads = db.scalars(
        select(Lead).where(Lead.workspace_id == ctx.workspace_id, Lead.archived_at.is_(None))
    )
    for lead in leads:
        company = None
        if lead.company_id:
            company = companies.get(lead.company_id)
            if company is None:
                company = db.get(Company, lead.company_id)
                if company:
                    companies[company.id] = company
        scorer.apply(lead, company)
        count += 1
    db.flush()
    return count
