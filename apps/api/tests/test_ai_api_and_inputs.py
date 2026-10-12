"""AI status endpoint, workspace-scoped input builders, the evaluation fixtures and migration 0006."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.ai import inputs
from app.ai.errors import ProviderTimeout
from app.ai.evals import CASES, run_evals
from app.ai.providers.mock import MockProvider
from app.ai.schemas import ClassifyReplyInput, RecommendNextActionInput
from app.ai.service import AiLimits
from app.db.models import Membership, User, Workspace
from app.db.models_email import Conversation, EmailAccount, Message
from app.deps import WorkspaceContext
from app.errors import AppError
from tests.ai_helpers import ScriptedProvider, service
from tests.conftest import add_member, make_user, second_client


def surl(wid: str) -> str:
    return f"/api/v1/workspaces/{wid}/ai/status"


def ctx_for(db: DbSession, wid: str, email: str) -> WorkspaceContext:
    user = db.scalar(select(User).where(User.email_normalized == email.lower()))
    ws = db.get(Workspace, uuid.UUID(wid))
    membership = db.scalar(
        select(Membership).where(Membership.workspace_id == ws.id, Membership.user_id == user.id)
    )  # type: ignore[union-attr]
    return WorkspaceContext(user=user, workspace=ws, membership=membership)  # type: ignore[arg-type]


# ----------------------------------------------------------------------------- status endpoint


def test_status_reports_the_demo_provider_honestly_and_never_a_secret(client: TestClient) -> None:
    u = make_user(client)
    res = client.get(surl(u["workspace_id"]))
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["provider"], body["available"], body["is_mock"]) == ("mock", True, True)
    assert "not a real model" in body["label"]
    assert body["model"] == "mock-rules-1" and body["rate_limit_per_minute"] == 30
    assert {t["task"] for t in body["tasks"]} == {
        "classify_reply", "assess_lead_fit", "extract_profile_facts",
        "draft_outreach", "summarize_conversation", "recommend_next_action",
    }  # fmt: skip
    assert all(t["prompt_version"] for t in body["tasks"])
    assert body["usage"] == {
        "window_hours": 24,
        "calls": 0,
        "failures": 0,
        "mock_calls": 0,
        "average_latency_ms": None,
    }
    assert "secret" not in res.text.lower() and "base_url" not in res.text.lower()


def test_status_counts_this_workspaces_recent_calls_only(client: TestClient) -> None:
    a = make_user(client)
    ws = uuid.UUID(a["workspace_id"])
    service(MockProvider(), workspace_id=ws, meter=True).classify_reply(
        ClassifyReplyInput(body="Sounds great")
    )
    failing = service(
        ScriptedProvider(ProviderTimeout()),
        workspace_id=ws,
        meter=True,
        limits=AiLimits(max_attempts=1),
    )
    failing.recommend_next_action(RecommendNextActionInput())
    usage = client.get(surl(a["workspace_id"])).json()["usage"]
    assert (usage["calls"], usage["failures"], usage["mock_calls"]) == (2, 1, 1)
    assert usage["average_latency_ms"] is not None
    other = second_client(client)
    b = make_user(other)
    assert other.get(surl(b["workspace_id"])).json()["usage"]["calls"] == 0


def test_status_is_readable_by_members_and_hidden_from_outsiders(
    client: TestClient, db: DbSession
) -> None:
    owner = make_user(client)
    outsider = second_client(client)
    make_user(outsider)
    assert outsider.get(surl(owner["workspace_id"])).status_code == 404
    member = second_client(client)
    m = make_user(member)
    add_member(db, owner["workspace_id"], m["me"]["user"]["id"])
    assert member.get(surl(owner["workspace_id"])).status_code == 200
    anonymous = second_client(client)
    anonymous.cookies.clear()
    assert anonymous.get(surl(owner["workspace_id"])).status_code == 401


def test_status_reports_disabled_and_gateway_providers(client: TestClient) -> None:
    from app.ai.providers.disabled import DisabledProvider
    from app.ai.providers.gateway import GatewayProvider

    u = make_user(client)
    client.app.state.ai_provider = DisabledProvider()  # type: ignore[attr-defined]
    body = client.get(surl(u["workspace_id"])).json()
    assert (body["provider"], body["available"], body["is_mock"], body["model"]) == (
        "disabled",
        False,
        False,
        None,
    )
    client.app.state.ai_provider = GatewayProvider(  # type: ignore[attr-defined]
        base_url="https://g.example",
        api_key="super-secret-key-value",
        model="big",
        fast_model="small",
    )
    res = client.get(surl(u["workspace_id"]))
    assert res.json()["model"] == "big" and res.json()["fast_model"] == "small"
    assert "super-secret-key-value" not in res.text


# ----------------------------------------------------------------------------- input builders


def test_lead_inputs_carry_no_contact_details_and_only_the_first_name(
    client: TestClient, db: DbSession
) -> None:
    u = make_user(client)
    wid = u["workspace_id"]
    company = client.post(
        f"/api/v1/workspaces/{wid}/companies",
        json={
            "name": "Example Clinic",
            "industry": "Healthcare",
            "location": "Berlin",
            "size_label": "11-50",
        },
    ).json()
    contact = client.post(
        f"/api/v1/workspaces/{wid}/contacts",
        json={
            "full_name": "Dana Whitfield",
            "email": "dana@clinic.example",
            "phone": "+49 30 1234567",
            "company_id": company["id"],
        },
    ).json()
    lead = client.post(
        f"/api/v1/workspaces/{wid}/leads",
        json={
            "title": "Site redesign",
            "company_id": company["id"],
            "contact_id": contact["id"],
            "notes": "Warm intro",
        },
    ).json()
    ctx = ctx_for(db, wid, u["email"])
    facts = inputs.lead_facts(db, ctx, uuid.UUID(lead["id"]))
    assert (facts.company_name, facts.industry, facts.location, facts.company_size) == (
        "Example Clinic",
        "Healthcare",
        "Berlin",
        "11-50",
    )
    target, first = inputs.draft_target(db, ctx, uuid.UUID(lead["id"]))
    assert first == "Dana" and target.company_name == "Example Clinic"
    dumped = facts.model_dump_json() + target.model_dump_json() + (first or "")
    assert (
        "dana@clinic.example" not in dumped
        and "1234567" not in dumped
        and "Whitfield" not in dumped
    )


def test_inputs_refuse_other_workspaces_records(client: TestClient, db: DbSession) -> None:
    a = make_user(client)
    other = second_client(client)
    b = make_user(other)
    lead_b = other.post(
        f"/api/v1/workspaces/{b['workspace_id']}/leads", json={"title": "B's lead"}
    ).json()
    ctx_a = ctx_for(db, a["workspace_id"], a["email"])
    with pytest.raises(AppError) as exc:
        inputs.lead_facts(db, ctx_a, uuid.UUID(lead_b["id"]))
    assert exc.value.status_code == 404
    with pytest.raises(AppError) as exc2:
        inputs.draft_target(db, ctx_a, uuid.UUID(lead_b["id"]))
    assert exc2.value.status_code == 404


def test_conversation_input_is_newest_first_limited_oldest_first_and_scoped(
    client: TestClient, db: DbSession
) -> None:
    a = make_user(client)
    other = second_client(client)
    b = make_user(other)
    ws = uuid.UUID(a["workspace_id"])
    acct = EmailAccount(
        workspace_id=ws,
        provider="demo",
        provider_account_id=uuid.uuid4().hex,
        email_address="me@x.example",
        status="demo",
        is_demo=True,
    )
    db.add(acct)
    db.flush()
    conv = Conversation(
        workspace_id=ws,
        email_account_id=acct.id,
        provider_thread_id=uuid.uuid4().hex,
        subject="Hello",
    )
    db.add(conv)
    db.flush()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(5):
        db.add(
            Message(
                workspace_id=ws,
                email_account_id=acct.id,
                conversation_id=conv.id,
                provider_message_id=f"m{i}",
                direction="inbound" if i % 2 else "outbound",
                from_address="private@x.example",
                to_addresses=["other@x.example"],
                snippet=f"message {i}",
                sent_at=start + timedelta(hours=i),
            )
        )
    db.commit()
    ctx = ctx_for(db, a["workspace_id"], a["email"])
    got = inputs.conversation_messages(db, ctx, conv.id, limit=3)
    assert [m.text for m in got] == ["message 2", "message 3", "message 4"]
    assert [m.direction for m in got] == ["outbound", "inbound", "outbound"]
    assert "private@x.example" not in "".join(m.model_dump_json() for m in got)
    ctx_b = ctx_for(db, b["workspace_id"], b["email"])
    with pytest.raises(AppError) as exc:
        inputs.conversation_messages(db, ctx_b, conv.id)
    assert exc.value.status_code == 404


# ----------------------------------------------------------------------------- evaluation fixtures


def test_the_demo_provider_passes_every_evaluation_case() -> None:
    report = run_evals(MockProvider())
    failures = [(r.id, r.reason) for r in report.results if not r.passed]
    assert failures == [] and report.total == len(CASES) >= 18 and report.is_mock
    assert set(report.by_task()) == {
        "classify_reply", "assess_lead_fit", "extract_profile_facts",
        "draft_outreach", "summarize_conversation", "recommend_next_action",
    }  # fmt: skip


def test_evaluations_catch_a_provider_that_ignores_the_rules() -> None:
    always_interested = ScriptedProvider(
        {"category": "interested", "confidence": 0.99, "rationale": "x"}
    )
    report = run_evals(always_interested)
    failed = {r.id for r in report.results if not r.passed}
    assert {"classify-question", "classify-objection", "classify-not-now"} <= failed
    assert "classify-injection-optout" not in failed  # the opt-out guard still protects the person


def test_evaluation_reports_failures_instead_of_crashing() -> None:
    class Exploding(ScriptedProvider):
        def complete(self, request):  # type: ignore[no-untyped-def]
            raise MemoryError("boom")

    report = run_evals(Exploding("x"))
    assert report.total == len(CASES) and report.passed < report.total


def test_cli_ai_eval_runs_and_exits_zero_with_the_demo_provider(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.cli import main

    assert main(["ai-eval"]) == 0
    out = capsys.readouterr().out
    assert "rule-based demo stand-in" in out and f"Total: {len(CASES)}/{len(CASES)}" in out


# ----------------------------------------------------------------------------- migration 0006


def test_0006_adds_and_removes_the_usage_columns() -> None:
    from sqlalchemy import inspect

    from app.db.session import get_engine
    from tests.test_migrations import at_revision

    def columns() -> set[str]:
        return {c["name"] for c in inspect(get_engine()).get_columns("usage_records")}

    assert {"error_code", "prompt_version"} <= columns()
    with at_revision("0005"):
        assert not ({"error_code", "prompt_version"} & columns())
        assert {
            "kind",
            "task_type",
            "latency_ms",
            "success",
        } <= columns()  # nothing else was touched
    assert {"error_code", "prompt_version"} <= columns()
