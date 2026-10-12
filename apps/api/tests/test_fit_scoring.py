from __future__ import annotations

import copy
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db.models import AuditEvent
from app.schemas.fit import FitExplanation
from app.services.fit_scoring import (
    BAND_POSSIBLE,
    BAND_STRONG,
    DEFAULT_CRITERIA,
    EXCLUDED_CAP,
    LeadFacts,
    ProfileFacts,
    band_for,
    phrase_in,
    score,
    stems,
)
from tests.conftest import add_member, make_user, second_client

PROFILE = ProfileFacts(
    services=("Web development", "Accessibility audits"),
    skills=("TypeScript", "React"),
    industries=("SaaS", "Fintech"),
    excluded_customers=("Gambling operators",),
    version=1,
)


def facts(**kw: Any) -> LeadFacts:
    base: dict[str, Any] = {
        "title": "Project",
        "notes": None,
        "industry": None,
        "location": None,
        "budget_signal": None,
        "company_name": None,
        "company_notes": None,
        "company_industry": None,
        "company_location": None,
        "company_size": None,
    }
    return LeadFacts(**{**base, **kw})


def criteria(**overrides: dict[str, Any]) -> list[dict[str, Any]]:
    out = copy.deepcopy(DEFAULT_CRITERIA)
    for c in out:
        c.update(overrides.get(c["key"], {}))
    return out


def run(
    lead: LeadFacts, crit: list[dict[str, Any]] | None = None, profile: ProfileFacts = PROFILE
) -> dict[str, Any]:
    return score(lead, profile, crit or criteria(), config_version=1)


def outcome(result: dict[str, Any], key: str) -> str:
    return next(c["outcome"] for c in result["criteria"] if c["key"] == key)


class TestTextMatching:
    @pytest.mark.parametrize(
        ("phrase", "text", "expected"),
        [
            ("Web development", "We need web development help", True),
            ("Web development", "web and development of an app", True),  # words, not exact phrase
            ("Web development", "A website rebuild", False),  # 'web' is not 'website'
            ("accessibility audits", "Accessibility audit needed", True),  # light stemming
            ("React", "React.js developers", True),
            ("AI", "maintain our chair", False),  # never a substring match
            ("UX", "ux research", True),
            ("and the", "anything", False),  # only stop words: nothing to match
            ("", "anything", False),
            ("Design", "designers wanted", True),
        ],
    )
    def test_phrases_match_whole_words_with_light_stemming(
        self, phrase: str, text: str, expected: bool
    ) -> None:
        assert phrase_in(phrase, stems(text)) is expected


class TestCriteria:
    def test_service_match_uses_profile_services_and_user_keywords(self) -> None:
        r = run(facts(title="Landing page", notes="web development for us"))
        assert outcome(r, "service_match") == "match"
        ev = next(c for c in r["criteria"] if c["key"] == "service_match")["evidence"]
        assert ev and ev[0]["field"] == "Lead notes" and ev[0]["value"] == "Web development"
        by_keyword = run(
            facts(title="Landing page redesign"),
            criteria(service_match={"keywords": ["landing page"]}),
        )
        assert outcome(by_keyword, "service_match") == "match"

    def test_a_skill_alone_is_only_a_partial_match(self) -> None:
        r = run(facts(title="We use TypeScript heavily"))
        assert outcome(r, "service_match") == "partial"

    def test_no_overlap_is_a_miss_with_an_honest_caveat(self) -> None:
        r = run(facts(title="Logo illustration"))
        c = next(c for c in r["criteria"] if c["key"] == "service_match")
        assert c["outcome"] == "miss" and "keyword" in c["reason"].lower()

    def test_no_text_or_nothing_to_compare_is_unknown_not_a_miss(self) -> None:
        assert outcome(run(facts(title="   ")), "service_match") == "unknown"
        empty = ProfileFacts((), (), (), (), 1)
        assert outcome(run(facts(title="Anything"), profile=empty), "service_match") == "unknown"

    def test_industry_prefers_config_then_profile_and_honours_the_avoid_list(self) -> None:
        assert outcome(run(facts(industry="B2B SaaS")), "industry") == "match"  # profile industries
        assert outcome(run(facts(industry="Retail")), "industry") == "miss"
        configured = criteria(industry={"preferred": ["Retail"]})
        assert outcome(run(facts(industry="Retail"), configured), "industry") == "match"
        avoided = criteria(industry={"preferred": ["Retail"], "avoid": ["retail"]})
        r = run(facts(industry="Retail"), avoided)
        assert outcome(r, "industry") == "miss"  # avoid beats prefer
        assert outcome(run(facts()), "industry") == "unknown"
        no_pref = ProfileFacts(("Web",), (), (), (), 1)
        assert outcome(run(facts(industry="Retail"), profile=no_pref), "industry") == "unknown"

    def test_company_industry_is_used_when_the_lead_has_none(self) -> None:
        r = run(facts(company_industry="Fintech"))
        c = next(c for c in r["criteria"] if c["key"] == "industry")
        assert c["outcome"] == "match" and c["evidence"][0]["field"] == "Company industry"

    def test_geography_needs_a_preference_and_a_location(self) -> None:
        pref = criteria(geography={"preferred": ["Germany", "Remote"]})
        assert outcome(run(facts(location="Berlin, Germany"), pref), "geography") == "match"
        assert outcome(run(facts(location="Remote (US)"), pref), "geography") == "match"
        assert outcome(run(facts(location="Tokyo"), pref), "geography") == "miss"
        assert outcome(run(facts(), pref), "geography") == "unknown"
        assert outcome(run(facts(location="Tokyo")), "geography") == "unknown"  # no preference set
        assert outcome(run(facts(company_location="Germany"), pref), "geography") == "match"

    def test_company_size_matches_exactly_or_by_neighbour(self) -> None:
        pref = criteria(company_size={"preferred": ["11-50"]})
        assert outcome(run(facts(company_size="11-50"), pref), "company_size") == "match"
        assert outcome(run(facts(company_size="2-10"), pref), "company_size") == "partial"
        assert outcome(run(facts(company_size="51-200"), pref), "company_size") == "partial"
        assert outcome(run(facts(company_size="1000+"), pref), "company_size") == "miss"
        assert outcome(run(facts(), pref), "company_size") == "unknown"
        assert outcome(run(facts(company_size="11-50")), "company_size") == "unknown"

    @pytest.mark.parametrize(
        ("signal", "expected"),
        [("high", "match"), ("medium", "partial"), ("low", "miss"), (None, "unknown")],
    )
    def test_budget_reflects_only_what_the_user_recorded(
        self, signal: str | None, expected: str
    ) -> None:
        r = run(facts(budget_signal=signal))
        assert outcome(r, "budget") == expected
        if signal:
            ev = next(c for c in r["criteria"] if c["key"] == "budget")["evidence"]
            assert "set by you" in ev[0]["field"]


class TestTheScore:
    def test_a_full_match_is_strong_and_rounded_to_five(self) -> None:
        r = run(
            facts(
                title="Web development",
                industry="SaaS",
                budget_signal="high",
                location="Remote",
                company_size="11-50",
            ),
            criteria(geography={"preferred": ["Remote"]}, company_size={"preferred": ["11-50"]}),
        )
        assert r["score"] == 100 and r["band"] == "strong" and r["confidence"] == 1.0
        assert r["capped"] is False and r["warnings"] == []

    def test_scores_are_multiples_of_five_and_use_only_known_criteria(self) -> None:
        # service match (5) + budget partial (2 of 2 known weight 7): 100 * (5 + 1) / 7 = 85.7 -> 85
        r = run(facts(title="Web development", budget_signal="medium"))
        assert r["known_weight"] == 7 and r["total_weight"] == 12
        assert r["score"] == 85 and r["score"] % 5 == 0

    def test_unknown_criteria_are_excluded_not_counted_as_misses(self) -> None:
        known_only = run(facts(title="Web development", industry="SaaS"))
        assert known_only["score"] == 100  # the other three are unknown and carry no weight
        assert [c["outcome"] for c in known_only["criteria"]].count("unknown") == 3

    def test_too_little_information_means_no_number(self) -> None:
        only_one = run(facts(title="Logo illustration"))  # a single known criterion (a miss)
        assert only_one["score"] is None and only_one["band"] == "insufficient"
        assert "not enough information" in only_one["summary"].lower()
        two_but_light = run(
            facts(title="Web development", budget_signal="low"),
            criteria(service_match={"weight": 1}, budget={"weight": 1}, industry={"weight": 10}),
        )
        assert two_but_light["confidence"] < 0.5 and two_but_light["score"] is None

    def test_weights_change_the_outcome(self) -> None:
        lead = facts(title="Web development", budget_signal="low")
        service_heavy = run(lead, criteria(service_match={"weight": 10}, budget={"weight": 1}))
        budget_heavy = run(lead, criteria(service_match={"weight": 1}, budget={"weight": 10}))
        assert service_heavy["score"] > budget_heavy["score"]

    def test_disabled_criteria_are_ignored_entirely(self) -> None:
        r = run(
            facts(title="Web development", budget_signal="low"), criteria(budget={"enabled": False})
        )
        assert "budget" not in {c["key"] for c in r["criteria"]}
        assert r["total_weight"] == 5 + 3 + 1 + 1

    def test_clients_you_do_not_take_cap_the_score_and_say_so(self) -> None:
        lead = facts(
            title="Web development",
            industry="SaaS",
            notes="Online gambling operator",
            budget_signal="high",
        )
        r = run(lead)
        assert r["capped"] is True and r["score"] == EXCLUDED_CAP and r["band"] == "weak"
        assert r["warnings"] and "gambling" in r["warnings"][0].lower()
        assert "limited to" in r["summary"].lower()

    def test_the_cap_does_not_raise_a_low_score(self) -> None:
        lead = facts(
            title="Logo illustration",
            industry="Retail",
            notes="gambling operator",
            budget_signal="low",
        )
        r = run(lead)
        assert r["score"] == 0 and r["capped"] is False and r["warnings"]

    @pytest.mark.parametrize(
        ("value", "band"),
        [
            (None, "insufficient"),
            (0, "weak"),
            (BAND_POSSIBLE - 5, "weak"),
            (BAND_POSSIBLE, "possible"),
            (BAND_STRONG - 5, "possible"),
            (BAND_STRONG, "strong"),
            (100, "strong"),
        ],
    )
    def test_band_thresholds(self, value: int | None, band: str) -> None:
        assert band_for(value) == band

    def test_scoring_is_deterministic_and_matches_the_published_schema(self) -> None:
        lead = facts(title="Web development", industry="SaaS", budget_signal="medium")
        a, b = run(lead), run(lead)
        a.pop("computed_at"), b.pop("computed_at")
        assert a == b
        parsed = FitExplanation.model_validate({**run(lead)})
        assert parsed.config_version == 1 and parsed.profile_version == 1

    def test_every_matched_criterion_cites_evidence(self) -> None:
        r = run(
            facts(
                title="Web development",
                industry="SaaS",
                budget_signal="high",
                location="Remote",
                company_size="11-50",
            ),
            criteria(geography={"preferred": ["Remote"]}, company_size={"preferred": ["11-50"]}),
        )
        for c in r["criteria"]:
            assert c["outcome"] == "match" and c["evidence"], c["key"]


class TestConfigApi:
    def url(self, wid: str, suffix: str = "") -> str:
        return f"/api/v1/workspaces/{wid}/fit-scoring{suffix}"

    def body(self, **overrides: dict[str, Any]) -> dict[str, Any]:
        return {"criteria": criteria(**overrides)}

    def test_defaults_are_shown_until_something_is_saved(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        got = client.get(self.url(wid)).json()
        assert got["version"] == 0 and got["updated_at"] is None
        assert [c["key"] for c in got["criteria"]] == [
            "service_match",
            "industry",
            "geography",
            "company_size",
            "budget",
        ]

    def test_saving_bumps_the_version_only_when_something_changed(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        first = client.put(
            self.url(wid), json=self.body(geography={"preferred": ["Remote"]})
        ).json()
        assert first["version"] == 1
        same = client.put(self.url(wid), json=self.body(geography={"preferred": ["Remote"]})).json()
        assert same["version"] == 1 and same["rescored"] is None
        changed = client.put(
            self.url(wid), json=self.body(geography={"preferred": ["Remote", "UK"]})
        ).json()
        assert changed["version"] == 2
        assert client.get(self.url(wid)).json()["criteria"][2]["preferred"] == ["Remote", "UK"]

    def test_saving_recomputes_active_leads_unless_told_not_to(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        client.patch(
            f"/api/v1/workspaces/{wid}/profile",
            json={"services": ["Web development"], "industries": ["SaaS"]},
        )
        made = client.post(
            f"/api/v1/workspaces/{wid}/leads",
            json={
                "title": "Web development",
                "industry": "SaaS",
                "location": "Tokyo",
                "budget_signal": "high",
            },
        ).json()
        before = made["fit_score"]
        res = client.put(
            self.url(wid), json=self.body(geography={"preferred": ["Remote"], "weight": 10})
        ).json()
        assert res["rescored"] == 1
        after = client.get(f"/api/v1/workspaces/{wid}/leads/{made['id']}").json()
        assert after["fit_score"] < before and after["fit_stale"] is False
        assert after["fit_explanation"]["config_version"] == 1
        # Without rescoring, existing scores are flagged stale instead of silently kept.
        client.put(
            self.url(wid), json={**self.body(geography={"preferred": ["Tokyo"]}), "rescore": False}
        )
        stale = client.get(f"/api/v1/workspaces/{wid}/leads/{made['id']}").json()
        assert stale["fit_stale"] is True
        assert client.post(self.url(wid, "/rescore")).json() == {"rescored": 1}
        assert (
            client.get(f"/api/v1/workspaces/{wid}/leads/{made['id']}").json()["fit_stale"] is False
        )

    def test_archived_leads_are_not_rescored(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        made = client.post(f"/api/v1/workspaces/{wid}/leads", json={"title": "x"}).json()
        client.post(f"/api/v1/workspaces/{wid}/leads/{made['id']}/archive")
        assert client.post(self.url(wid, "/rescore")).json() == {"rescored": 0}

    def test_stale_expected_version_is_a_conflict(self, client: TestClient) -> None:
        wid = make_user(client)["workspace_id"]
        client.put(self.url(wid), json=self.body(geography={"preferred": ["A"]}))
        res = client.put(
            self.url(wid), json={**self.body(geography={"preferred": ["B"]}), "expected_version": 0}
        )
        assert res.status_code == 409 and res.json()["error"]["code"] == "stale_version"
        ok = client.put(
            self.url(wid), json={**self.body(geography={"preferred": ["B"]}), "expected_version": 1}
        )
        assert ok.status_code == 200

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda c: c[:-1],  # a criterion missing
            lambda c: [*c, c[0]],  # a duplicate
            lambda c: [{**x, "enabled": False} for x in c],  # all switched off
            lambda c: [{**c[0], "weight": 0}, *c[1:]],
            lambda c: [{**c[0], "weight": 11}, *c[1:]],
            lambda c: [{**c[0], "unknown": 1}, *c[1:]],
            lambda c: [{**c[0], "key": "vibes"}, *c[1:]],
            lambda c: [{**c[0], "keywords": ["x" * 81]}, *c[1:]],
            lambda c: [{**c[0], "keywords": ["a\x00b"]}, *c[1:]],
            lambda c: [c[0], {**c[1], "preferred": ["x"] * 41}, *c[2:]],
            lambda c: [*c[:4], {**c[4], "preferred": ["gigantic"]}],
        ],
    )
    def test_invalid_criteria_are_rejected(self, client: TestClient, mutate: Any) -> None:
        wid = make_user(client)["workspace_id"]
        res = client.put(self.url(wid), json={"criteria": mutate(criteria())})
        assert res.status_code == 422, res.text
        assert client.get(self.url(wid)).json()["version"] == 0

    def test_criteria_are_scoped_per_workspace_and_owner_only(
        self, client: TestClient, db: DbSession
    ) -> None:
        other = second_client(client)
        a, b = make_user(client), make_user(other)
        client.put(self.url(a["workspace_id"]), json=self.body(geography={"preferred": ["Mine"]}))
        assert other.get(self.url(b["workspace_id"])).json()["version"] == 0
        assert other.get(self.url(a["workspace_id"])).status_code == 404
        assert other.put(self.url(a["workspace_id"]), json=self.body()).status_code == 404
        assert other.post(self.url(a["workspace_id"], "/rescore")).status_code == 404
        add_member(db, a["workspace_id"], b["me"]["user"]["id"])
        assert other.get(self.url(a["workspace_id"])).status_code == 200
        assert other.put(self.url(a["workspace_id"]), json=self.body()).status_code == 403
        assert other.post(self.url(a["workspace_id"], "/rescore")).status_code == 403

    def test_changes_are_audited_without_the_criteria_text(
        self, client: TestClient, db: DbSession
    ) -> None:
        wid = make_user(client)["workspace_id"]
        client.put(self.url(wid), json=self.body(geography={"preferred": ["Top secret place"]}))
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.workspace_id == uuid.UUID(wid))
        ).all()
        assert "fit_scoring.updated" in {e.action for e in events}
        assert "secret" not in " ".join(str(e.details) for e in events)
