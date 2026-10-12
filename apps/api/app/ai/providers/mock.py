"""A rule-based stand-in used in development and tests, and for the evaluation fixtures.

It is NOT a model. It reads the structured ``payload`` (never the prompt), applies simple rules and returns JSON
through the same path a real provider uses, so parsing, validation, metering and fallback are all exercised.
Everything it produces is labelled (``AiMeta.is_mock``) and drafts begin with a visible marker so they cannot be sent
by accident.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from app.ai import rules
from app.ai.errors import InvalidOutput
from app.ai.providers.base import ProviderRequest, ProviderResponse

DRAFT_MARKER = (
    "[DEMO DRAFT: written by a rule-based stand-in, not a real model. Rewrite before sending.]"
)
MODEL = "mock-rules-1"

_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_FACT_WORDS = re.compile(
    r"\b(?:i (?:build|design|develop|write|help|specialise|specialize|offer|provide|work)|specializ|specialis|"
    r"years? of experience|experience (?:in|with)|case study|portfolio|my rate|rates? (?:start|are)|"
    r"hourly|per hour|day rate|built|launched|delivered)\b",
    re.I,
)


def _kind(sentence: str) -> str:
    low = sentence.lower()
    if re.search(r"\bcase study|\bbuilt\b|\blaunched\b|\bdelivered\b", low):
        return "case_study"
    if re.search(r"\brate|\bhourly|per hour|day rate|\bprice", low):
        return "pricing"
    if "portfolio" in low:
        return "portfolio"
    if re.search(
        r"\bi (?:build|design|develop|write|help|offer|provide)\b|specializ|specialis", low
    ):
        return "service"
    return "fact"


def _first_sentence(text: str, limit: int = 220) -> str:
    for part in _SENTENCE.split(text.strip()):
        part = part.strip()
        if part:
            return part[:limit]
    return ""


class MockProvider:
    name = "mock"
    is_mock = True

    def model_for(self, tier: Literal["fast", "quality"]) -> str:
        return MODEL

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        handler = getattr(self, f"_{request.task}", None)
        if handler is None:
            raise InvalidOutput("unknown_task")
        result = handler(request.payload.get("input", {}), request.payload.get("context") or {})
        text = json.dumps(result)
        return ProviderResponse(text=text, model=MODEL, input_tokens=0, output_tokens=0)

    # ------------------------------------------------------------------ tasks

    def _classify_reply(self, inp: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
        return rules.classify_by_rules(inp.get("subject"), inp.get("body", "")).model_dump()

    def _assess_lead_fit(self, inp: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        lead = {k: v for k, v in (inp.get("lead") or {}).items() if v}
        profile = ctx.get("profile") or {}
        reasons: list[dict[str, str]] = []
        gaps: list[str] = []
        searchable = " ".join(str(lead.get(k, "")) for k in ("title", "notes", "industry")).lower()

        industries = [str(i) for i in profile.get("industries") or []]
        hit = next((i for i in industries if i.lower() in searchable), None)
        if hit:
            reasons.append(
                {
                    "statement": f"The lead's field matches your industry experience ({hit}).",
                    "evidence_field": "profile.industries",
                }
            )
        services = [str(s) for s in profile.get("services") or []]
        hit = next((s for s in services if s.lower() in searchable), None)
        if hit:
            reasons.append(
                {
                    "statement": f"The lead mentions something you offer ({hit}).",
                    "evidence_field": "profile.services",
                }
            )
        if lead.get("location") and any(
            str(p).lower() in str(lead["location"]).lower()
            for p in profile.get("target_clients") or []
        ):
            reasons.append(
                {
                    "statement": "The lead's location matches a target client.",
                    "evidence_field": "location",
                }
            )
        for field, label in (
            ("industry", "industry"),
            ("company_size", "company size"),
            ("location", "location"),
        ):
            if not lead.get(field):
                gaps.append(f"The lead's {label} is not recorded.")
        if not profile.get("services") and not profile.get("industries"):
            gaps.append("Your profile has no services or industries to compare with.")

        known = [k for k in lead if k not in ("source",)]
        if len(known) < 2 or (not profile.get("services") and not profile.get("industries")):
            assessment, confidence = "unknown", 0.2
        elif len(reasons) >= 2:
            assessment, confidence = "strong", 0.6
        elif reasons:
            assessment, confidence = "possible", 0.5
        else:
            assessment, confidence = "weak", 0.4
        return {
            "assessment": assessment,
            "confidence": confidence,
            "reasons": reasons[:6],
            "gaps": gaps[:6],
        }

    def _extract_profile_facts(self, inp: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
        facts: list[dict[str, str]] = []
        seen: set[str] = set()
        for raw in _SENTENCE.split(str(inp.get("text", ""))):
            sentence = raw.strip()
            if len(sentence) < 12 or not _FACT_WORDS.search(sentence) or sentence.lower() in seen:
                continue
            seen.add(sentence.lower())
            title = " ".join(sentence.split()[:6]).rstrip(".,;:")
            facts.append(
                {
                    "kind": _kind(sentence),
                    "title": title[:120],
                    "content": sentence[:1000],
                    "source_quote": sentence[:400],
                }
            )
            if len(facts) == 20:
                break
        return {"facts": facts}

    def _draft_outreach(self, inp: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        lead = inp.get("lead") or {}
        company = lead.get("company_name")
        name = inp.get("recipient_first_name")
        facts = ctx.get("facts") or []
        profile = ctx.get("profile") or {}
        used = facts[:2]
        lines = [DRAFT_MARKER, "", f"Hi {name}," if name else "Hello,", ""]
        lines.append(
            f"I'm getting in touch about {company}." if company else "I'm getting in touch."
        )
        if used:
            lines.extend(_first_sentence(f["content"], 240) for f in used)
        elif profile.get("summary"):
            lines.append(_first_sentence(str(profile["summary"]), 240))
        elif profile.get("services"):
            lines.append("I help with " + ", ".join(str(s) for s in profile["services"][:3]) + ".")
        lines += [
            "",
            str(profile.get("preferred_cta") or "Would a short conversation be useful?"),
            "",
            "Thank you.",
        ]
        needs = ["This is a demo draft from a rule-based stand-in; rewrite it before sending."]
        if not company:
            needs.append("No company name was available.")
        if not name:
            needs.append("No recipient name was available.")
        return {
            "subject": f"A quick note for {company}" if company else "A quick introduction",
            "body": "\n".join(lines),
            "facts_used": [f["id"] for f in used],
            "needs_review": needs,
        }

    def _summarize_conversation(self, inp: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
        messages = inp.get("messages") or []
        points: list[str] = []
        questions: list[str] = []
        for m in messages:
            first = _first_sentence(str(m.get("text", "")), 160)
            if first:
                points.append(
                    f"{'They wrote' if m.get('direction') == 'inbound' else 'You wrote'}: {first}"[
                        :200
                    ]
                )
            if m.get("direction") == "inbound":
                questions += [
                    s.strip()[:200]
                    for s in _SENTENCE.split(str(m.get("text", "")))
                    if s.strip().endswith("?")
                ]
        inbound = [m for m in messages if m.get("direction") == "inbound"]
        latest = _first_sentence(str(inbound[-1].get("text", "")), 200) if inbound else ""
        summary = f"{len(messages)} message(s)."
        summary += (
            f" Their latest message begins: {latest}" if latest else " They have not replied yet."
        )
        return {
            "summary": summary[:700],
            "key_points": points[-6:],
            "open_questions": questions[-6:],
        }

    def _recommend_next_action(self, inp: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
        if inp.get("opted_out"):
            return {
                "action": "no_action",
                "rationale": "They asked not to be contacted.",
                "in_days": None,
            }
        table: dict[str, tuple[str, str, int | None]] = {
            "unsubscribe": (
                "pause_outreach",
                "They asked to stop; pause outreach and record the opt-out.",
                None,
            ),
            "interested": ("reply", "They sound interested; reply soon.", 0),
            "question": ("reply", "They asked a question; answer it.", 0),
            "referral": ("reply", "They pointed to someone else; follow that lead.", 1),
            "objection": (
                "create_follow_up_task",
                "Consider a considered reply to the objection.",
                3,
            ),
            "not_now": ("create_follow_up_task", "Timing is wrong; follow up later.", 30),
            "out_of_office": ("wait", "They are away; try again after they return.", 7),
            "irrelevant": ("no_action", "Nothing in the reply needs action.", None),
        }
        last = inp.get("last_classification")
        if last in table:
            action, why, days = table[last]
            return {"action": action, "rationale": why, "in_days": days}
        if (inp.get("days_since_last_contact") or 0) >= 7 and not inp.get("has_open_task"):
            return {
                "action": "create_follow_up_task",
                "rationale": "No contact for a week.",
                "in_days": 1,
            }
        return {"action": "wait", "rationale": "No new signal.", "in_days": 3}
