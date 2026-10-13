from __future__ import annotations

import re
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import String, func, select
from sqlalchemy.orm import Session as DbSession

from app.cli import main
from app.config import get_settings
from app.db.base import Base
from app.db.models_crm import Company, Lead, Tag
from app.db.models_email import Draft
from app.db.models_workflow import ApprovalRequest, WorkflowNode, WorkflowRun, WorkflowVersion
from app.seed import DEMO_EMAIL, DEMO_PASSWORD, seed_demo
from app.services.workflows import definition_checksum
from tests.conftest import reset_demo


@pytest.fixture
def demo(db: DbSession) -> uuid.UUID:
    reset_demo(db)
    created, ws = seed_demo(db)
    db.commit()
    assert created and ws is not None
    return ws


def test_seed_is_idempotent(db: DbSession, demo: uuid.UUID) -> None:
    counts = {
        t.name: db.scalar(select(func.count()).select_from(t)) for t in Base.metadata.sorted_tables
    }
    created, ws = seed_demo(db)
    db.commit()
    assert (created, ws) == (False, demo)
    assert counts == {
        t.name: db.scalar(select(func.count()).select_from(t)) for t in Base.metadata.sorted_tables
    }


def test_everything_in_the_seed_is_clearly_fictional(db: DbSession, demo: uuid.UUID) -> None:
    """No address or domain can belong to a real person: only reserved .example names, and every row that
    has an is_sample flag is marked as sample data."""
    email_like = re.compile(r"[\w.+-]+@([\w.-]+)")
    for table in Base.metadata.sorted_tables:
        if "workspace_id" not in table.c:
            continue
        rows = db.execute(select(table).where(table.c.workspace_id == demo)).mappings().all()
        for row in rows:
            for name, value in row.items():
                if isinstance(table.c[name].type, String) and isinstance(value, str):
                    for domain in email_like.findall(value):
                        assert domain.endswith(".example"), (
                            f"{table.name}.{name} has a non-.example address: {value}"
                        )
                if name in ("domain", "domain_normalized", "website") and value:
                    assert ".example" in value, f"{table.name}.{name}={value}"
                if name == "is_sample":
                    assert value is True, f"{table.name} row is not flagged is_sample"
    names = [c.name for c in db.scalars(select(Company).where(Company.workspace_id == demo))]
    assert names and all("(fictional)" in n for n in names)


def test_demo_account_matches_the_documented_credentials(
    client: TestClient, demo: uuid.UUID
) -> None:
    res = client.post("/api/v1/auth/sign-in", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    assert res.status_code == 200
    ws = res.json()["workspaces"][0]
    assert (
        ws["id"] == str(demo) and ws["demo_mode"] is True and ws["onboarding_status"] == "completed"
    )
    tags = client.get(f"/api/v1/workspaces/{demo}/tags").json()
    assert {t["name"] for t in tags["items"]} == {"Priority", "SaaS", "Warm intro"}
    stages = client.get(f"/api/v1/workspaces/{demo}/pipeline/stages").json()
    assert stages["total"] == 8


def test_seed_content_is_realistic_and_internally_consistent(
    db: DbSession, demo: uuid.UUID
) -> None:
    leads = db.scalars(select(Lead).where(Lead.workspace_id == demo)).all()
    assert len(leads) == 5 and all(ld.fit_explanation for ld in leads)
    assert all(ld.fit_score is None or 0 <= ld.fit_score <= 100 for ld in leads)
    assert {ld.status for ld in leads} >= {"new", "replied", "qualified"}
    # Scores come from the real rules and show the whole range, including "not enough information".
    bands = {ld.fit_explanation["band"] for ld in leads}  # type: ignore[index]
    assert bands == {"strong", "weak", "insufficient"}
    by_title = {ld.title: ld for ld in leads}
    inbound = by_title["Inbound inquiry (fictional)"]
    assert inbound.fit_score is None and inbound.fit_explanation["band"] == "insufficient"  # type: ignore[index]
    gambling = by_title["Tailspin Co (fictional) website rebuild"]
    assert gambling.fit_explanation["capped"] is True and gambling.fit_score == 25  # type: ignore[index]
    assert all(ld.fit_explanation["config_version"] == 1 for ld in leads)  # type: ignore[index]
    assert all(ld.is_sample and ld.source == "seed" for ld in leads)
    # The pending approval is bound to the exact draft content (approval must be re-requested if it changes).
    approval = db.scalar(select(ApprovalRequest).where(ApprovalRequest.workspace_id == demo))
    draft = db.get(Draft, approval.draft_id)  # type: ignore[union-attr]
    assert approval.status == "pending" and approval.payload_hash == draft.content_hash  # type: ignore[union-attr]
    # The workflow starter is draft + test mode, the run is pinned to a version of its own workflow.
    run = db.scalar(select(WorkflowRun).where(WorkflowRun.workspace_id == demo))
    version = db.get(WorkflowVersion, run.version_id)  # type: ignore[union-attr]
    assert version.workflow_id == run.workflow_id and run.mode == "test"  # type: ignore[union-attr]
    nodes = db.scalars(select(WorkflowNode).where(WorkflowNode.version_id == version.id)).all()  # type: ignore[union-attr]
    assert {n.type for n in nodes} >= {"trigger", "approval_gate", "send_email"}


def test_workflow_checksum_is_order_independent_and_content_sensitive() -> None:
    n = [{"key": "a", "type": "trigger", "config": {}}, {"key": "b", "type": "end", "config": {}}]
    e = [{"key": "e1", "source": "a", "target": "b"}]
    assert definition_checksum(n, e) == definition_checksum(list(reversed(n)), e)
    assert definition_checksum(n, e) != definition_checksum(n, [])
    changed = [{**n[0], "config": {"x": 1}}, n[1]]
    assert definition_checksum(changed, e) != definition_checksum(n, e)


@pytest.mark.parametrize("env", ["production", "staging"])
def test_cli_seed_refuses_outside_development_and_test(
    monkeypatch: pytest.MonkeyPatch, env: str, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(get_settings(), "app_env", env)
    before = None
    assert main(["seed"]) == 1
    assert "Refusing" in capsys.readouterr().err
    assert before is None


def test_cli_seed_creates_then_reports_nothing_to_do(
    db: DbSession, capsys: pytest.CaptureFixture[str]
) -> None:
    reset_demo(db)
    assert main(["seed"]) == 0
    assert "Demo data created" in capsys.readouterr().out
    assert main(["seed"]) == 0
    assert "Demo data already present" in capsys.readouterr().out
    assert db.scalar(select(func.count()).select_from(Tag)) > 0  # type: ignore[operator]


def test_demo_profile_and_knowledge_cover_every_review_state(
    client: TestClient, demo: uuid.UUID
) -> None:
    client.post("/api/v1/auth/sign-in", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    profile = client.get(f"/api/v1/workspaces/{demo}/profile").json()
    assert (
        profile["pricing_guidance"]
        and profile["excluded_customers"]
        and profile["differentiators"]
        and profile["preferred_cta"]
    )
    assert profile["completeness"]["missing"] == [] and "fictional" in profile["role_title"].lower()
    assert client.get(f"/api/v1/workspaces/{demo}/knowledge/stats").json() == {
        "draft": 1,
        "pending_review": 1,
        "approved": 3,
        "rejected": 1,
        "in_use": 2,
        "disabled": 1,
    }
    ctx = client.get(f"/api/v1/workspaces/{demo}/ai-context").json()
    assert sorted(f["title"] for f in ctx["facts"]) == ["Accessibility focus", "Performance audits"]
    assert ctx["excluded_counts"] == {"pending_review": 1, "draft": 1, "rejected": 1, "disabled": 1}
    extracted = client.get(
        f"/api/v1/workspaces/{demo}/knowledge", params={"source_type": "extracted"}
    ).json()
    assert {i["status"] for i in extracted["items"]} == {"pending_review", "rejected"}
    assert all(i["source_ref"] == "Demo resume.pdf (fictional)" for i in extracted["items"])


def test_demo_pipeline_and_tasks_cover_the_interesting_states(
    db: DbSession, demo: uuid.UUID
) -> None:
    from app.db.models_crm import Opportunity, PipelineStage, Task

    stages = {
        s.id: s for s in db.scalars(select(PipelineStage).where(PipelineStage.workspace_id == demo))
    }
    opps = db.scalars(select(Opportunity).where(Opportunity.workspace_id == demo)).all()
    assert {o.status for o in opps} == {"open", "lost"} and {o.currency for o in opps} == {
        "USD",
        "EUR",
    }
    assert any(
        o.probability is None and o.status == "open" for o in opps
    )  # a probability is never guessed
    lost = next(o for o in opps if o.status == "lost")
    assert stages[lost.stage_id].is_lost and lost.loss_reason and lost.closed_at
    assert all(not stages[o.stage_id].is_lost for o in opps if o.status == "open")
    tasks = db.scalars(select(Task).where(Task.workspace_id == demo)).all()
    assert {t.status for t in tasks} == {"open", "done"} and any(t.due_at is None for t in tasks)
    assert all(t.is_sample for t in tasks) and all(
        t.completed_at for t in tasks if t.status == "done"
    )
    assert any(t.opportunity_id for t in tasks)
