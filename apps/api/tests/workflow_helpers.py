"""Helpers for the workflow engine tests: an owner, a controllable clock, a worker you drive by hand and tiny graph builders."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.ai.providers.mock import MockProvider
from app.clock import utcnow
from app.db.models_crm import Lead
from app.db.models_email import Draft, SuppressionEntry
from app.db.models_workflow import ApprovalRequest, WorkflowRun, WorkflowStepRun
from app.db.session import get_sessionmaker
from app.workflows import engine
from app.workflows.runtime import EngineDeps, deps_from_app
from tests.ai_helpers import service
from tests.conftest import make_user
from tests.email_helpers import FakeProvider, connect_gmail, install


class Clock:
    """``now`` that only moves when a test says so (on top of the real time the API itself uses)."""

    def __init__(self) -> None:
        self.offset = timedelta(0)

    def __call__(self) -> datetime:
        return utcnow() + self.offset

    def advance(self, **kw: float) -> None:
        self.offset += timedelta(**kw)


def node(id_: str, type_: str, **config: Any) -> dict[str, Any]:
    return {"id": id_, "type": type_, "config": config}


def edge(src: str, dst: str, branch: str | None = None) -> dict[str, Any]:
    return {"id": f"{src}-{dst}-{branch or 'next'}", "source": src, "target": dst, "branch": branch}


def graph(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schemaVersion": 1, "nodes": nodes, "edges": edges}


def linear(*steps: dict[str, Any]) -> dict[str, Any]:
    """trigger(manual, lead) -> steps... -> end"""
    nodes = [node("t", "trigger", event="manual", subject="lead"), *steps, node("end", "end")]
    ids = [n["id"] for n in nodes]
    return graph(nodes, [edge(a, b) for a, b in zip(ids, ids[1:], strict=False)])


def approval_flow(*, send: bool = True) -> dict[str, Any]:
    """trigger -> draft -> approval -> (approved: send -> end | rejected: end)"""
    nodes = [
        node("t", "trigger", event="manual", subject="lead"),
        node("d", "ai_draft"),
        node("g", "approval_gate", message="Review this email", expires_hours=24),
        node("end", "end"),
        node("no", "end", reason="rejected"),
    ]
    edges = [edge("t", "d"), edge("d", "g"), edge("g", "no", "rejected")]
    if send:
        nodes.insert(3, node("s", "send_email"))
        edges += [edge("g", "s", "approved"), edge("s", "end")]
    else:
        edges += [edge("g", "end", "approved")]
    return graph(nodes, edges)


class WfEnv:
    def __init__(
        self,
        client: TestClient,
        db: DbSession,
        monkeypatch: pytest.MonkeyPatch,
        *,
        mailbox: bool = False,
        facts: bool = True,
    ) -> None:
        self.client, self.db = client, db
        self.user = make_user(client)
        self.wid: str = self.user["workspace_id"]
        self.clock = Clock()
        # The API normally starts a worker after the response; tests drive the worker themselves.
        monkeypatch.setattr("app.workflows.engine.run_worker", lambda *a, **k: None)
        monkeypatch.setattr("app.services.email_jobs.run_worker", lambda *a, **k: None)
        client.app.state.ai_provider = MockProvider()  # type: ignore[attr-defined]
        self.fake: FakeProvider | None = None
        self.account: dict[str, Any] | None = None
        if mailbox:
            self.fake = install(client)
            self.account = connect_gmail(client, self.wid, self.fake)
        if facts:
            self.add_fact()
        self._ai: Any = None

    # ------------------------------------------------------------------ api helpers
    def url(self, suffix: str) -> str:
        return f"/api/v1/workspaces/{self.wid}{suffix}"

    def add_fact(
        self, title: str = "Marketing sites", content: str = "I build marketing sites."
    ) -> None:
        res = self.client.post(
            self.url("/knowledge"),
            json={"title": title, "content": content, "kind": "service", "approve_now": True},
        )
        assert res.status_code == 201, res.text

    def lead(
        self, title: str = "Acme website", email: str | None = "sam@acme.example"
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"title": title, "company_name": "Acme Inc"}
        if email:
            body.update(contact_name="Sam Lee", contact_email=email)
        res = self.client.post(self.url("/leads"), json=body)
        assert res.status_code == 201, res.text
        return res.json()  # type: ignore[no-any-return]

    def create(
        self,
        definition: dict[str, Any],
        *,
        name: str = "Test workflow",
        activate: bool = False,
        live: bool = False,
    ) -> str:
        res = self.client.post(
            self.url("/workflows"), json={"name": name, "definition": definition}
        )
        assert res.status_code == 201, res.text
        wf_id: str = res.json()["id"]
        if activate or live:
            res = self.client.post(self.url(f"/workflows/{wf_id}/activate"), json={})
            assert res.status_code == 200, res.text
        if live:
            res = self.client.post(
                self.url(f"/workflows/{wf_id}/mode"), json={"mode": "live", "confirm": True}
            )
            assert res.status_code == 200, res.text
        return wf_id

    def start(
        self, wf_id: str, lead_id: str, *, key: str | None = None, expect: int = 201
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"subject_type": "lead", "subject_id": lead_id}
        if key:
            body["idempotency_key"] = key
        res = self.client.post(self.url(f"/workflows/{wf_id}/runs"), json=body)
        assert res.status_code == expect, res.text
        return res.json()  # type: ignore[no-any-return]

    def run(self, run_id: str) -> dict[str, Any]:
        res = self.client.get(self.url(f"/workflow-runs/{run_id}"))
        assert res.status_code == 200, res.text
        return res.json()  # type: ignore[no-any-return]

    def status(self, run_id: str) -> str:
        return str(self.run(run_id)["status"])

    def steps(self, run_id: str) -> list[tuple[str, int, str]]:
        return [(s["node_key"], s["attempt"], s["status"]) for s in self.run(run_id)["steps"]]

    def approvals(self, status: str | None = "pending") -> list[dict[str, Any]]:
        params = {"status": status or "all"}
        res = self.client.get(self.url("/approvals"), params=params)
        assert res.status_code == 200, res.text
        return res.json()["items"]  # type: ignore[no-any-return]

    def decide(
        self, approval_id: str, decision: str = "approve", expect: int = 200
    ) -> dict[str, Any]:
        res = self.client.post(
            self.url(f"/approvals/{approval_id}/decide"), json={"decision": decision}
        )
        assert res.status_code == expect, res.text
        return res.json()  # type: ignore[no-any-return]

    # ------------------------------------------------------------------ the worker
    def use_ai(self, provider: Any) -> None:
        """Run the AI nodes against ``provider`` (a scripted one, to make the AI fail on cue)."""
        self._ai = provider

    def deps(self) -> EngineDeps:
        deps = deps_from_app(self.client.app)  # type: ignore[arg-type]
        deps = replace(deps, now=self.clock)
        if self._ai is not None:
            provider = self._ai
            deps = replace(deps, ai_for=lambda wid, budget: service(provider, workspace_id=wid))
        return deps

    def work(self, limit: int = 10) -> engine.BatchStats:
        return engine.process_batch(
            get_sessionmaker(), self.deps(), limit=limit, workspace_id=uuid.UUID(self.wid)
        )

    def drain(self, rounds: int = 10) -> None:
        for _ in range(rounds):
            if not self.work().claimed:
                return

    # ------------------------------------------------------------------ database peeks
    def row(self, run_id: str) -> WorkflowRun:
        self.db.expire_all()
        row = self.db.get(WorkflowRun, uuid.UUID(run_id))
        assert row is not None
        return row

    def step_rows(self, run_id: str) -> list[WorkflowStepRun]:
        self.db.expire_all()
        return list(
            self.db.scalars(
                select(WorkflowStepRun)
                .where(WorkflowStepRun.run_id == uuid.UUID(run_id))
                .order_by(WorkflowStepRun.created_at, WorkflowStepRun.attempt)
            )
        )

    def approval_rows(self, run_id: str) -> list[ApprovalRequest]:
        self.db.expire_all()
        return list(
            self.db.scalars(
                select(ApprovalRequest).where(ApprovalRequest.run_id == uuid.UUID(run_id))
            )
        )

    def draft(self, draft_id: str) -> Draft:
        self.db.expire_all()
        row = self.db.get(Draft, uuid.UUID(draft_id))
        assert row is not None
        return row

    def lead_row(self, lead_id: str) -> Lead:
        self.db.expire_all()
        row = self.db.get(Lead, uuid.UUID(lead_id))
        assert row is not None
        return row

    def suppress(self, address: str) -> None:
        self.db.add(
            SuppressionEntry(
                workspace_id=uuid.UUID(self.wid),
                email_normalized=address,
                reason="manual",
                source="test",
            )
        )
        self.db.commit()
