"""Behavioural tests: the database itself enforces uniqueness, tenant isolation, value ranges and cascades."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.clock import utcnow
from app.db.base import Base
from app.db.models import AuditEvent, Membership, User, Workspace
from app.db.models_crm import (
    Activity,
    Company,
    Contact,
    Lead,
    LeadTag,
    Opportunity,
    PipelineStage,
    Tag,
    Task,
)
from app.db.models_email import (
    Conversation,
    CredentialSecret,
    Draft,
    EmailAccount,
    IntegrationConnection,
    Message,
    SuppressionEntry,
)
from app.db.models_workflow import (
    ApprovalRequest,
    Notification,
    UsageRecord,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
    WorkflowRun,
    WorkflowStepRun,
    WorkflowVersion,
)
from app.seed import seed_demo
from app.services.pipeline import ensure_default_stages
from tests.conftest import reset_demo

NOW = utcnow()


def uid() -> str:
    return uuid.uuid4().hex[:10]


def build_tenant(db: DbSession) -> SimpleNamespace:
    """One user + workspace with a representative row in every entity that others can reference."""
    user = User(
        email=f"{uid()}@t.example",
        email_normalized=f"{uid()}@t.example",
        password_hash="x",
        display_name="T",
    )
    user.email_normalized = user.email.lower()
    db.add(user)
    db.flush()
    ws = Workspace(name="W")
    db.add(ws)
    db.flush()
    db.add(Membership(workspace_id=ws.id, user_id=user.id, role="owner"))
    stages = ensure_default_stages(db, ws.id)
    t = SimpleNamespace(ws=ws.id, user=user.id, stage=stages[0].id, stage2=stages[1].id)
    company = Company(
        workspace_id=ws.id,
        name="C",
        domain=f"{uid()}.example",
        domain_normalized=f"{uid()}.example",
    )
    db.add(company)
    db.flush()
    contact = Contact(
        workspace_id=ws.id,
        company_id=company.id,
        full_name="P",
        email=f"{uid()}@x.example",
        email_normalized=f"{uid()}@x.example",
    )
    tag = Tag(workspace_id=ws.id, name="T", name_normalized=f"t{uid()}")
    cred = CredentialSecret(workspace_id=ws.id, purpose="test", ciphertext=b"opaque", key_id="k")
    db.add_all([contact, tag, cred])
    db.flush()
    lead = Lead(
        workspace_id=ws.id,
        company_id=company.id,
        contact_id=contact.id,
        stage_id=t.stage,
        title="L",
    )
    db.add(lead)
    db.flush()
    opp = Opportunity(workspace_id=ws.id, lead_id=lead.id, stage_id=t.stage, title="O")
    acct = EmailAccount(
        workspace_id=ws.id,
        provider="demo",
        provider_account_id=uid(),
        email_address="a@x.example",
        status="demo",
        is_demo=True,
        credential_id=cred.id,
    )
    wf = Workflow(workspace_id=ws.id, name="WF")
    db.add_all([opp, acct, wf])
    db.flush()
    conv = Conversation(workspace_id=ws.id, email_account_id=acct.id, provider_thread_id=uid())
    ver = WorkflowVersion(workspace_id=ws.id, workflow_id=wf.id, version=1, checksum="c")
    db.add_all([conv, ver])
    db.flush()
    node = WorkflowNode(workspace_id=ws.id, version_id=ver.id, node_key="n1", type="trigger")
    draft = Draft(workspace_id=ws.id, lead_id=lead.id)
    run = WorkflowRun(
        workspace_id=ws.id,
        workflow_id=wf.id,
        version_id=ver.id,
        trigger_type="manual",
        correlation_id=uid(),
    )
    db.add_all([node, draft, run])
    db.flush()
    step = WorkflowStepRun(workspace_id=ws.id, run_id=run.id, node_key="n1")
    db.add(step)
    db.commit()
    t.__dict__.update(
        company=company.id,
        contact=contact.id,
        tag=tag.id,
        cred=cred.id,
        lead=lead.id,
        opp=opp.id,
        acct=acct.id,
        wf=wf.id,
        conv=conv.id,
        ver=ver.id,
        node=node.id,
        draft=draft.id,
        run=run.id,
        step=step.id,
    )
    return t


@pytest.fixture
def a(db: DbSession) -> SimpleNamespace:
    return build_tenant(db)


@pytest.fixture
def b(db: DbSession) -> SimpleNamespace:
    return build_tenant(db)


def rejected(db: DbSession, *objs: Any) -> None:
    # PostgreSQL reports over-long values as DataError, constraint violations as IntegrityError.
    with pytest.raises((IntegrityError, DataError)):
        db.add_all(objs)
        db.flush()
    db.rollback()


# ---------------------------------------------------------------------------------------------------
# Duplicate protection / unique provider ids
# ---------------------------------------------------------------------------------------------------
UNIQUE: dict[str, Callable[[SimpleNamespace], Callable[[], Any]]] = {
    "contact email per workspace": lambda t: (
        lambda: Contact(
            workspace_id=t.ws,
            full_name="D",
            email="dup@x.example",
            email_normalized="dup@x.example",
        )
    ),
    "company domain per workspace": lambda t: (
        lambda: Company(workspace_id=t.ws, name="D", domain_normalized="dup.example")
    ),
    "tag name per workspace": lambda t: (
        lambda: Tag(workspace_id=t.ws, name="Dup", name_normalized="dup")
    ),
    "suppression email per workspace": lambda t: (
        lambda: SuppressionEntry(
            workspace_id=t.ws, email_normalized="stop@x.example", reason="manual"
        )
    ),
    "pipeline stage key per workspace": lambda t: (
        lambda: PipelineStage(workspace_id=t.ws, key="dupstage", name="D", position=99)
    ),
    "email account provider id": lambda t: (
        lambda: EmailAccount(
            workspace_id=t.ws,
            provider="gmail",
            provider_account_id="acct-1",
            email_address="a@x.example",
            status="connected",
        )
    ),
    "integration connection account": lambda t: (
        lambda: IntegrationConnection(
            workspace_id=t.ws, connector="gmail", external_account_id="ext-1", status="connected"
        )
    ),
    "conversation thread per account": lambda t: (
        lambda: Conversation(
            workspace_id=t.ws, email_account_id=t.acct, provider_thread_id="thread-1"
        )
    ),
    "message provider id per account": lambda t: (
        lambda: Message(
            workspace_id=t.ws,
            email_account_id=t.acct,
            conversation_id=t.conv,
            provider_message_id="m-1",
            direction="inbound",
            from_address="a@x.example",
            sent_at=NOW,
        )
    ),
    "workflow version number": lambda t: (
        lambda: WorkflowVersion(workspace_id=t.ws, workflow_id=t.wf, version=7, checksum="c")
    ),
    "workflow node key per version": lambda t: (
        lambda: WorkflowNode(workspace_id=t.ws, version_id=t.ver, node_key="dupnode", type="end")
    ),
    "workflow run event (idempotency)": lambda t: (
        lambda: WorkflowRun(
            workspace_id=t.ws,
            workflow_id=t.wf,
            version_id=t.ver,
            trigger_type="webhook",
            correlation_id=uid(),
            idempotency_key="evt-1",
        )
    ),
    "step run attempt": lambda t: (
        lambda: WorkflowStepRun(workspace_id=t.ws, run_id=t.run, node_key="stepdup", attempt=1)
    ),
    "step side-effect idempotency key": lambda t: (
        lambda: WorkflowStepRun(
            workspace_id=t.ws, run_id=t.run, node_key=f"s{uid()}", idempotency_key="send-1"
        )
    ),
    "task idempotency key": lambda t: (
        lambda: Task(workspace_id=t.ws, title="T", idempotency_key="task-1")
    ),
    "draft send idempotency key": lambda t: (
        lambda: Draft(workspace_id=t.ws, send_idempotency_key="send-key-1")
    ),
    "notification dedupe per user": lambda t: (
        lambda: Notification(
            workspace_id=t.ws, user_id=t.user, kind="k", title="T", dedupe_key="dd-1"
        )
    ),
    "lead tag pair": lambda t: lambda: LeadTag(workspace_id=t.ws, lead_id=t.lead, tag_id=t.tag),
}


@pytest.mark.filterwarnings("ignore:New instance .* conflicts with persistent instance")
@pytest.mark.parametrize("name", list(UNIQUE))
def test_duplicates_are_rejected_within_a_workspace(
    db: DbSession, a: SimpleNamespace, name: str
) -> None:
    # Prime only the row under test (plus its dependencies), then try to insert it again.
    primer = UNIQUE[name](a)()
    if name == "workflow version number":
        primer.version = 7
    db.add(primer)
    db.commit()
    rejected(db, UNIQUE[name](a)())


UNIQUE_PER_TENANT = [
    "contact email per workspace",
    "company domain per workspace",
    "tag name per workspace",
    "suppression email per workspace",
    "task idempotency key",
    "draft send idempotency key",
    "pipeline stage key per workspace",
]


@pytest.mark.parametrize("name", UNIQUE_PER_TENANT)
def test_the_same_value_is_fine_in_another_workspace(
    db: DbSession, a: SimpleNamespace, b: SimpleNamespace, name: str
) -> None:
    db.add(UNIQUE[name](a)())
    db.add(UNIQUE[name](b)())
    db.commit()  # no IntegrityError: uniqueness is per workspace


def test_null_domains_and_emails_do_not_collide(db: DbSession, a: SimpleNamespace) -> None:
    db.add_all(
        [
            Company(workspace_id=a.ws, name="No domain 1"),
            Company(workspace_id=a.ws, name="No domain 2"),
            Contact(workspace_id=a.ws, full_name="No email 1"),
            Contact(workspace_id=a.ws, full_name="No email 2"),
        ]
    )
    db.commit()


# ---------------------------------------------------------------------------------------------------
# Tenant isolation enforced by composite foreign keys
# ---------------------------------------------------------------------------------------------------
CROSS: dict[str, Callable[[SimpleNamespace, SimpleNamespace], Any]] = {
    "lead -> other tenant's company": lambda a, b: Lead(
        workspace_id=a.ws, title="x", company_id=b.company
    ),
    "lead -> other tenant's contact": lambda a, b: Lead(
        workspace_id=a.ws, title="x", contact_id=b.contact
    ),
    "lead -> other tenant's stage": lambda a, b: Lead(
        workspace_id=a.ws, title="x", stage_id=b.stage
    ),
    "contact -> other tenant's company": lambda a, b: Contact(
        workspace_id=a.ws, full_name="x", company_id=b.company
    ),
    "lead_tag lead from other tenant": lambda a, b: LeadTag(
        workspace_id=a.ws, lead_id=b.lead, tag_id=a.tag
    ),
    "lead_tag tag from other tenant": lambda a, b: LeadTag(
        workspace_id=a.ws, lead_id=a.lead, tag_id=b.tag
    ),
    "opportunity -> other tenant's lead": lambda a, b: Opportunity(
        workspace_id=a.ws, lead_id=b.lead, stage_id=a.stage, title="x"
    ),
    "opportunity -> other tenant's stage": lambda a, b: Opportunity(
        workspace_id=a.ws, lead_id=a.lead, stage_id=b.stage, title="x"
    ),
    "activity -> other tenant's lead": lambda a, b: Activity(
        workspace_id=a.ws, lead_id=b.lead, kind="note", summary="x"
    ),
    "task -> other tenant's lead": lambda a, b: Task(workspace_id=a.ws, title="x", lead_id=b.lead),
    "task -> other tenant's opportunity": lambda a, b: Task(
        workspace_id=a.ws, title="x", opportunity_id=b.opp
    ),
    "task -> other tenant's conversation": lambda a, b: Task(
        workspace_id=a.ws, title="x", conversation_id=b.conv
    ),
    "email account -> other tenant's credential": lambda a, b: EmailAccount(
        workspace_id=a.ws,
        provider="gmail",
        provider_account_id=uid(),
        email_address="x@x.example",
        credential_id=b.cred,
    ),
    "integration -> other tenant's credential": lambda a, b: IntegrationConnection(
        workspace_id=a.ws, connector="gmail", external_account_id=uid(), credential_id=b.cred
    ),
    "conversation -> other tenant's account": lambda a, b: Conversation(
        workspace_id=a.ws, email_account_id=b.acct, provider_thread_id=uid()
    ),
    "conversation -> other tenant's lead": lambda a, b: Conversation(
        workspace_id=a.ws, email_account_id=a.acct, provider_thread_id=uid(), lead_id=b.lead
    ),
    "conversation -> other tenant's contact": lambda a, b: Conversation(
        workspace_id=a.ws, email_account_id=a.acct, provider_thread_id=uid(), contact_id=b.contact
    ),
    "message -> other tenant's conversation": lambda a, b: Message(
        workspace_id=a.ws,
        email_account_id=a.acct,
        conversation_id=b.conv,
        provider_message_id=uid(),
        direction="inbound",
        from_address="x@x.example",
        sent_at=NOW,
    ),
    "message -> other tenant's account": lambda a, b: Message(
        workspace_id=a.ws,
        email_account_id=b.acct,
        conversation_id=a.conv,
        provider_message_id=uid(),
        direction="inbound",
        from_address="x@x.example",
        sent_at=NOW,
    ),
    "draft -> other tenant's lead": lambda a, b: Draft(workspace_id=a.ws, lead_id=b.lead),
    "draft -> other tenant's conversation": lambda a, b: Draft(
        workspace_id=a.ws, conversation_id=b.conv
    ),
    "draft -> other tenant's account": lambda a, b: Draft(
        workspace_id=a.ws, email_account_id=b.acct
    ),
    "workflow version -> other tenant's workflow": lambda a, b: WorkflowVersion(
        workspace_id=a.ws, workflow_id=b.wf, version=9, checksum="c"
    ),
    "workflow node -> other tenant's version": lambda a, b: WorkflowNode(
        workspace_id=a.ws, version_id=b.ver, node_key="x", type="end"
    ),
    "workflow run -> other tenant's workflow": lambda a, b: WorkflowRun(
        workspace_id=a.ws,
        workflow_id=b.wf,
        version_id=a.ver,
        trigger_type="m",
        correlation_id=uid(),
    ),
    "workflow run -> other tenant's version": lambda a, b: WorkflowRun(
        workspace_id=a.ws,
        workflow_id=a.wf,
        version_id=b.ver,
        trigger_type="m",
        correlation_id=uid(),
    ),
    "step run -> other tenant's run": lambda a, b: WorkflowStepRun(
        workspace_id=a.ws, run_id=b.run, node_key="x"
    ),
    "approval -> other tenant's run": lambda a, b: ApprovalRequest(
        workspace_id=a.ws, run_id=b.run, kind="k", payload_hash="h"
    ),
    "approval -> other tenant's step run": lambda a, b: ApprovalRequest(
        workspace_id=a.ws, step_run_id=b.step, kind="k", payload_hash="h"
    ),
    "approval -> other tenant's draft": lambda a, b: ApprovalRequest(
        workspace_id=a.ws, draft_id=b.draft, kind="k", payload_hash="h"
    ),
}


@pytest.mark.parametrize("name", list(CROSS))
def test_database_refuses_cross_tenant_references(
    db: DbSession, a: SimpleNamespace, b: SimpleNamespace, name: str
) -> None:
    rejected(db, CROSS[name](a, b))


@pytest.mark.parametrize(
    "name", ["lead -> own company", "task -> own lead", "draft -> own conversation"]
)
def test_same_tenant_references_are_accepted(db: DbSession, a: SimpleNamespace, name: str) -> None:
    obj = {
        "lead -> own company": Lead(
            workspace_id=a.ws,
            title="ok",
            company_id=a.company,
            contact_id=a.contact,
            stage_id=a.stage,
        ),
        "task -> own lead": Task(
            workspace_id=a.ws,
            title="ok",
            lead_id=a.lead,
            opportunity_id=a.opp,
            conversation_id=a.conv,
        ),
        "draft -> own conversation": Draft(
            workspace_id=a.ws, conversation_id=a.conv, lead_id=a.lead, email_account_id=a.acct
        ),
    }[name]
    db.add(obj)
    db.commit()


def test_optional_relations_may_be_null(db: DbSession, a: SimpleNamespace) -> None:
    db.add_all(
        [
            Lead(workspace_id=a.ws, title="loose"),
            Contact(workspace_id=a.ws, full_name="loose"),
            Task(workspace_id=a.ws, title="loose"),
            Draft(workspace_id=a.ws),
        ]
    )
    db.commit()


def test_workflow_run_version_must_belong_to_the_runs_workflow(
    db: DbSession, a: SimpleNamespace
) -> None:
    other_wf = Workflow(workspace_id=a.ws, name="Other")
    db.add(other_wf)
    db.flush()
    other_ver = WorkflowVersion(workspace_id=a.ws, workflow_id=other_wf.id, version=1, checksum="c")
    db.add(other_ver)
    db.commit()
    # Same tenant, but version belongs to a different workflow: rejected.
    rejected(
        db,
        WorkflowRun(
            workspace_id=a.ws,
            workflow_id=a.wf,
            version_id=other_ver.id,
            trigger_type="m",
            correlation_id=uid(),
        ),
    )


def test_workflow_edges_must_connect_nodes_of_the_same_version(
    db: DbSession, a: SimpleNamespace
) -> None:
    ver2 = WorkflowVersion(workspace_id=a.ws, workflow_id=a.wf, version=2, checksum="c2")
    db.add(ver2)
    db.flush()
    db.add(WorkflowNode(workspace_id=a.ws, version_id=ver2.id, node_key="other", type="end"))
    db.commit()
    rejected(
        db,
        WorkflowEdge(
            workspace_id=a.ws, version_id=a.ver, edge_key="bad", source_key="n1", target_key="other"
        ),
    )
    rejected(
        db,
        WorkflowEdge(
            workspace_id=a.ws,
            version_id=a.ver,
            edge_key="bad2",
            source_key="missing",
            target_key="n1",
        ),
    )
    db.add(
        WorkflowEdge(
            workspace_id=a.ws, version_id=a.ver, edge_key="ok", source_key="n1", target_key="n1"
        )
    )
    db.commit()


# ---------------------------------------------------------------------------------------------------
# Value constraints
# ---------------------------------------------------------------------------------------------------
BAD_VALUES: dict[str, Callable[[SimpleNamespace], Any]] = {
    "lead status": lambda t: Lead(workspace_id=t.ws, title="x", status="bogus"),
    "lead fit score > 100": lambda t: Lead(workspace_id=t.ws, title="x", fit_score=101),
    "lead fit score < 0": lambda t: Lead(workspace_id=t.ws, title="x", fit_score=-1),
    "task status": lambda t: Task(workspace_id=t.ws, title="x", status="bogus"),
    "task priority": lambda t: Task(workspace_id=t.ws, title="x", priority="urgent!!"),
    "opportunity probability": lambda t: Opportunity(
        workspace_id=t.ws, lead_id=t.lead, stage_id=t.stage, title="x", probability=150
    ),
    "opportunity negative value": lambda t: Opportunity(
        workspace_id=t.ws, lead_id=t.lead, stage_id=t.stage, title="x", value_amount=Decimal("-1")
    ),
    "opportunity currency": lambda t: Opportunity(
        workspace_id=t.ws, lead_id=t.lead, stage_id=t.stage, title="x", currency="DOLLARS"
    ),
    "opportunity status": lambda t: Opportunity(
        workspace_id=t.ws, lead_id=t.lead, stage_id=t.stage, title="x", status="maybe"
    ),
    "activity kind": lambda t: Activity(
        workspace_id=t.ws, lead_id=t.lead, kind="gossip", summary="x"
    ),
    "activity without subject": lambda t: Activity(workspace_id=t.ws, kind="note", summary="x"),
    "tag colour length": lambda t: Tag(
        workspace_id=t.ws, name="x", name_normalized=uid(), color="red"
    ),
    "membership role": lambda t: Membership(workspace_id=t.ws, user_id=t.user, role="superuser"),
    "email provider": lambda t: EmailAccount(
        workspace_id=t.ws, provider="aol", provider_account_id=uid(), email_address="x@x.example"
    ),
    "email account status": lambda t: EmailAccount(
        workspace_id=t.ws,
        provider="demo",
        provider_account_id=uid(),
        email_address="x@x.example",
        status="great",
    ),
    "message direction": lambda t: Message(
        workspace_id=t.ws,
        email_account_id=t.acct,
        conversation_id=t.conv,
        provider_message_id=uid(),
        direction="sideways",
        from_address="x@x.example",
        sent_at=NOW,
    ),
    "message delivery state": lambda t: Message(
        workspace_id=t.ws,
        email_account_id=t.acct,
        conversation_id=t.conv,
        provider_message_id=uid(),
        direction="inbound",
        delivery_state="delivered!",
        from_address="x@x.example",
        sent_at=NOW,
    ),
    "conversation classification": lambda t: Conversation(
        workspace_id=t.ws, email_account_id=t.acct, provider_thread_id=uid(), classification="spam"
    ),
    "conversation confidence": lambda t: Conversation(
        workspace_id=t.ws,
        email_account_id=t.acct,
        provider_thread_id=uid(),
        classification="interested",
        classification_confidence=1.5,
    ),
    "draft status": lambda t: Draft(workspace_id=t.ws, status="sent!"),
    "suppression reason": lambda t: SuppressionEntry(
        workspace_id=t.ws, email_normalized=uid(), reason="felt like it"
    ),
    "knowledge status": lambda t: __import__(
        "app.db.models_crm", fromlist=["KnowledgeItem"]
    ).KnowledgeItem(workspace_id=t.ws, title="x", content="x", status="trusted"),
    "workflow status": lambda t: Workflow(workspace_id=t.ws, name="x", status="running"),
    "workflow mode": lambda t: Workflow(workspace_id=t.ws, name="x", mode="yolo"),
    "run status": lambda t: WorkflowRun(
        workspace_id=t.ws,
        workflow_id=t.wf,
        version_id=t.ver,
        trigger_type="m",
        correlation_id=uid(),
        status="done-ish",
    ),
    "step attempt": lambda t: WorkflowStepRun(
        workspace_id=t.ws, run_id=t.run, node_key="x", attempt=0
    ),
    "approval status": lambda t: ApprovalRequest(
        workspace_id=t.ws, kind="k", payload_hash="h", status="yes"
    ),
    "usage negative tokens": lambda t: UsageRecord(
        workspace_id=t.ws, kind="ai_request", input_tokens=-5
    ),
    "workflow version zero": lambda t: WorkflowVersion(
        workspace_id=t.ws, workflow_id=t.wf, version=0, checksum="c"
    ),
}


@pytest.mark.parametrize("name", list(BAD_VALUES))
def test_invalid_values_are_rejected_by_the_database(
    db: DbSession, a: SimpleNamespace, name: str
) -> None:
    rejected(db, BAD_VALUES[name](a))


def test_money_keeps_exact_decimal_precision(db: DbSession, a: SimpleNamespace) -> None:
    o = Opportunity(
        workspace_id=a.ws,
        lead_id=a.lead,
        stage_id=a.stage,
        title="money",
        value_amount=Decimal("1234567.89"),
        currency="EUR",
        probability=100,
    )
    db.add(o)
    db.commit()
    db.expire_all()
    assert db.get(Opportunity, o.id).value_amount == Decimal("1234567.89")  # type: ignore[union-attr]


def test_timestamps_roundtrip_as_utc_instants(db: DbSession, a: SimpleNamespace) -> None:
    due = NOW + timedelta(days=1)
    t = Task(workspace_id=a.ws, title="tz", due_at=due, due_timezone="Pacific/Auckland")
    db.add(t)
    db.commit()
    db.expire_all()
    got = db.get(Task, t.id)
    assert got is not None and got.due_timezone == "Pacific/Auckland"
    assert abs((got.due_at.replace(tzinfo=None) - due.replace(tzinfo=None)).total_seconds()) < 1  # type: ignore[union-attr]


# ---------------------------------------------------------------------------------------------------
# Delete behaviour (retention/deletion rules are documented in docs/DATA_MODEL.md)
# ---------------------------------------------------------------------------------------------------
def test_referenced_stage_and_company_cannot_be_deleted(db: DbSession, a: SimpleNamespace) -> None:
    stage = db.get(PipelineStage, a.stage)
    company = db.get(Company, a.company)
    with pytest.raises(IntegrityError):
        db.delete(stage)
        db.flush()
    db.rollback()
    with pytest.raises(IntegrityError):
        db.delete(company)
        db.flush()
    db.rollback()


def test_deleting_a_lead_erases_its_dependents_but_not_shared_records(
    db: DbSession, a: SimpleNamespace
) -> None:
    db.add_all(
        [
            LeadTag(workspace_id=a.ws, lead_id=a.lead, tag_id=a.tag),
            Activity(workspace_id=a.ws, lead_id=a.lead, kind="note", summary="n"),
            Task(workspace_id=a.ws, title="t", lead_id=a.lead),
        ]
    )
    db.commit()
    db.delete(db.get(Lead, a.lead))
    db.commit()
    for model in (LeadTag, Activity, Opportunity, Draft):
        assert (
            db.scalar(select(func.count()).select_from(model).where(model.lead_id == a.lead)) == 0
        )  # type: ignore[attr-defined]
    assert db.scalar(select(func.count()).select_from(Task).where(Task.lead_id == a.lead)) == 0
    assert db.get(Company, a.company) is not None and db.get(Tag, a.tag) is not None


def test_deleting_a_tag_only_removes_the_links(db: DbSession, a: SimpleNamespace) -> None:
    db.add(LeadTag(workspace_id=a.ws, lead_id=a.lead, tag_id=a.tag))
    db.commit()
    db.delete(db.get(Tag, a.tag))
    db.commit()
    assert db.get(Lead, a.lead) is not None
    assert db.scalar(select(func.count()).select_from(LeadTag).where(LeadTag.tag_id == a.tag)) == 0


def test_deleting_a_workspace_deletes_all_of_its_data_and_nothing_else(
    db: DbSession, a: SimpleNamespace, b: SimpleNamespace
) -> None:
    reset_demo(db)
    created, seeded_ws = seed_demo(db)
    db.commit()
    assert created and seeded_ws is not None
    tenant_tables = [t for t in Base.metadata.sorted_tables if "workspace_id" in t.c]

    def rows(table: Any, ws: uuid.UUID) -> int:
        return (
            db.scalar(select(func.count()).select_from(table).where(table.c.workspace_id == ws))
            or 0
        )

    audit_event = AuditEvent(workspace_id=seeded_ws, action="test.event")
    db.add(audit_event)
    db.commit()
    # The demo workspace populates (nearly) every tenant table, so this test covers every cascade.
    # The only exception: the demo mailbox is not a real account, so the seed stores no credentials
    # (cascade for credential_secrets is covered by the fixture workspaces below).
    empty = [t.name for t in tenant_tables if rows(t, seeded_ws) == 0]
    assert empty == ["credential_secrets"], (
        f"seed should exercise every tenant table; empty: {empty}"
    )
    assert rows(Base.metadata.tables["credential_secrets"], a.ws) == 1
    others_before = {t.name: (rows(t, a.ws), rows(t, b.ws)) for t in tenant_tables}

    db.delete(db.get(Workspace, seeded_ws))
    db.commit()
    # And a plain workspace with a credential cascades its secret too.
    db.delete(db.get(Workspace, b.ws))
    db.commit()
    assert rows(Base.metadata.tables["credential_secrets"], b.ws) == 0
    others_before = {name: (counts[0], 0) for name, counts in others_before.items()}

    leftovers = {
        t.name: rows(t, seeded_ws)
        for t in tenant_tables
        if t.name != "audit_events" and rows(t, seeded_ws)
    }
    assert leftovers == {}
    db.expire_all()
    # The audit trail outlives the workspace, detached from it (SET NULL).
    assert db.get(AuditEvent, audit_event.id).workspace_id is None  # type: ignore[union-attr]
    # Other tenants are untouched.
    assert {t.name: (rows(t, a.ws), rows(t, b.ws)) for t in tenant_tables} == others_before
    assert (
        db.scalar(select(User).where(User.email_normalized == "demo@freelancer-os.example"))
        is not None
    )
