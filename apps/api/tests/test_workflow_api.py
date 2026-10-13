"""The workflow API: catalogue, validation, versions, switching on, modes, limits, isolation, audit and the worker command."""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db.models import AuditEvent
from app.workflows.engine import run_worker as real_run_worker
from tests.conftest import add_member, make_user, second_client
from tests.workflow_helpers import WfEnv, approval_flow, edge, graph, linear, node

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


@pytest.fixture
def env(client: TestClient, db: DbSession, monkeypatch: pytest.MonkeyPatch) -> WfEnv:
    return WfEnv(client, db, monkeypatch)


def wf_url(env: WfEnv, suffix: str = "") -> str:
    return env.url(f"/workflows{suffix}")


# ----------------------------------------------------------------------------- catalogue and validation


def test_the_catalogue_describes_every_node_with_its_settings_and_ports(env: WfEnv) -> None:
    res = env.client.get(wf_url(env, "/catalog"))
    assert res.status_code == 200
    body = res.json()
    types = {n["type"]: n for n in body["nodes"]}
    assert len(types) == 12
    assert types["condition"]["ports"] == ["true", "false"]
    assert types["approval_gate"]["ports"] == ["approved", "rejected"]
    assert types["end"]["ports"] == []
    assert types["send_email"]["side_effect"] is True and types["notify"]["side_effect"] is False
    assert "event" in types["trigger"]["config_schema"]["properties"]
    assert {f["field"] for f in body["condition_fields"]} >= {
        "fit.rating",
        "classification.category",
        "lead.score",
    }
    assert body["trigger_events"] == ["manual", "lead_created", "reply_received", "follow_up_due"]
    assert body["max_nodes"] == 50


def test_validate_reports_problems_without_saving_anything(env: WfEnv) -> None:
    bad = graph([node("t", "trigger", event="manual")], [])
    res = env.client.post(wf_url(env, "/validate"), json={"definition": bad})
    assert res.status_code == 200
    body = res.json()
    assert body["valid"] is False
    assert {"missing_end", "unhandled_branch"} <= {i["code"] for i in body["issues"]}
    assert env.client.get(wf_url(env)).json()["total"] == 0
    good = env.client.post(
        wf_url(env, "/validate"), json={"definition": linear(node("n", "notify", title="x"))}
    )
    assert good.json() == {"valid": True, "issues": [], "trigger_event": "manual"}


def test_a_malformed_definition_is_refused_before_it_gets_anywhere(env: WfEnv) -> None:
    for bad in (
        {"nodes": [{"id": "has space", "type": "end"}], "edges": []},
        {"nodes": [{"type": "end"}], "edges": []},
        {"nodes": [], "edges": [], "surprise": 1},
        {"schemaVersion": 2, "nodes": [], "edges": []},
        {"nodes": [{"id": f"n{i}", "type": "end"} for i in range(51)], "edges": []},
    ):
        res = env.client.post(wf_url(env, "/validate"), json={"definition": bad})
        assert res.status_code == 422, bad


# ----------------------------------------------------------------------------- workflows and versions


def test_create_save_versions_and_activate_only_valid_ones(env: WfEnv) -> None:
    res = env.client.post(wf_url(env), json={"name": "  Follow-ups  ", "description": "d"})
    assert res.status_code == 201
    wf = res.json()
    assert wf["name"] == "Follow-ups" and wf["status"] == "draft" and wf["mode"] == "test"
    assert wf["latest"] is None and wf["versions"] == [] and wf["latest_version"] is None
    wid = wf["id"]
    broken = env.client.post(
        wf_url(env, f"/{wid}/versions"),
        json={"definition": graph([node("t", "trigger", event="manual")], []), "note": "wip"},
    )
    assert broken.status_code == 201
    v1 = broken.json()
    assert v1["version"] == 1 and v1["valid"] is False and v1["issues"]
    # work in progress can be saved, but it cannot be switched on or run
    assert env.client.post(wf_url(env, f"/{wid}/activate"), json={}).status_code == 409
    lead = env.lead()
    res = env.client.post(
        wf_url(env, f"/{wid}/runs"), json={"subject_type": "lead", "subject_id": lead["id"]}
    )
    assert res.status_code == 409 and res.json()["error"]["code"] == "workflow_invalid"
    good = env.client.post(
        wf_url(env, f"/{wid}/versions"), json={"definition": linear(node("n", "notify", title="x"))}
    )
    assert good.json()["version"] == 2 and good.json()["valid"] is True
    activated = env.client.post(wf_url(env, f"/{wid}/activate"), json={})
    assert activated.status_code == 200
    body = activated.json()
    assert (
        body["status"] == "active"
        and body["active_version"] == 2
        and body["trigger_event"] == "manual"
    )
    assert body["mode"] == "test"  # switching on does not mean going live
    assert [v["version"] for v in body["versions"]] == [2, 1] and [
        v["active"] for v in body["versions"]
    ] == [True, False]
    assert env.client.post(wf_url(env, f"/{wid}/activate"), json={"version": 1}).status_code == 409
    assert env.client.post(wf_url(env, f"/{wid}/activate"), json={"version": 9}).status_code == 404
    got = env.client.get(wf_url(env, f"/{wid}/versions/1")).json()
    assert got["version"] == 1 and got["definition"]["nodes"][0]["id"] == "t"


def test_saved_versions_are_immutable_snapshots(env: WfEnv) -> None:
    first = linear(node("n", "notify", title="one"))
    wid = env.create(first)
    second = linear(node("n", "notify", title="two"))
    assert (
        env.client.post(wf_url(env, f"/{wid}/versions"), json={"definition": second}).status_code
        == 201
    )
    v1 = env.client.get(wf_url(env, f"/{wid}/versions/1")).json()["definition"]
    v2 = env.client.get(wf_url(env, f"/{wid}/versions/2")).json()["definition"]
    assert next(n for n in v1["nodes"] if n["id"] == "n")["config"]["title"] == "one"
    assert next(n for n in v2["nodes"] if n["id"] == "n")["config"]["title"] == "two"
    assert (
        env.client.put(wf_url(env, f"/{wid}/versions/1"), json={"definition": second}).status_code
        == 405
    )


def test_going_live_needs_an_active_workflow_and_an_explicit_confirmation(env: WfEnv) -> None:
    wid = env.create(linear(node("n", "notify", title="x")))
    live = {"mode": "live", "confirm": True}
    res = env.client.post(wf_url(env, f"/{wid}/mode"), json=live)
    assert res.status_code == 409 and res.json()["error"]["code"] == "workflow_not_active"
    env.client.post(wf_url(env, f"/{wid}/activate"), json={})
    res = env.client.post(wf_url(env, f"/{wid}/mode"), json={"mode": "live"})
    assert res.status_code == 422 and res.json()["error"]["code"] == "confirmation_required"
    assert env.client.get(wf_url(env, f"/{wid}")).json()["mode"] == "test"
    assert env.client.post(wf_url(env, f"/{wid}/mode"), json=live).json()["mode"] == "live"
    assert (
        env.client.post(wf_url(env, f"/{wid}/mode"), json={"mode": "test"}).json()["mode"] == "test"
    )


def test_a_workflow_that_is_not_switched_on_only_runs_in_test_mode(env: WfEnv) -> None:
    wid = env.create(linear(node("n", "notify", title="x")))
    started = env.start(wid, env.lead()["id"])
    assert started["run"]["mode"] == "test"
    pause_before = env.client.post(wf_url(env, f"/{wid}/pause"))
    assert pause_before.status_code == 409  # nothing to pause: it was never switched on


def test_pausing_stops_new_event_runs_but_not_the_ones_in_progress(env: WfEnv) -> None:
    wid = env.create(linear(node("w", "delay", amount=1, unit="hours")), activate=True)
    running = env.start(wid, env.lead()["id"])["run"]["id"]
    env.drain()
    assert env.client.post(wf_url(env, f"/{wid}/pause")).json()["status"] == "paused"
    env.clock.advance(hours=2)
    env.drain()
    assert env.status(running) == "succeeded"  # the run already in progress finished


def test_an_archived_workflow_cannot_run_or_change(env: WfEnv) -> None:
    wid = env.create(linear(node("n", "notify", title="x")), activate=True)
    assert env.client.post(wf_url(env, f"/{wid}/archive")).json()["status"] == "archived"
    lead = env.lead()
    res = env.client.post(
        wf_url(env, f"/{wid}/runs"), json={"subject_type": "lead", "subject_id": lead["id"]}
    )
    assert res.status_code == 409 and res.json()["error"]["code"] == "workflow_archived"
    res = env.client.post(
        wf_url(env, f"/{wid}/versions"), json={"definition": linear(node("n", "notify", title="y"))}
    )
    assert res.status_code == 409
    assert env.client.get(wf_url(env)).json()["total"] == 0
    assert env.client.get(wf_url(env), params={"status": "archived"}).json()["total"] == 1


def test_a_run_needs_the_right_kind_of_subject(env: WfEnv) -> None:
    lead = env.lead()
    reply = graph(
        [
            node("t", "trigger", event="reply_received"),
            node("n", "notify", title="x"),
            node("end", "end"),
        ],
        [edge("t", "n"), edge("n", "end")],
    )
    wid = env.create(reply)
    res = env.client.post(
        wf_url(env, f"/{wid}/runs"), json={"subject_type": "lead", "subject_id": lead["id"]}
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == "wrong_subject"
    res = env.client.post(
        wf_url(env, f"/{wid}/runs"),
        json={"subject_type": "conversation", "subject_id": str(uuid.uuid4())},
    )
    assert res.status_code == 404


# ----------------------------------------------------------------------------- limits


def test_workspace_limits_are_enforced(env: WfEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "workflow_max_workflows", 2)
    env.create(linear(node("n", "notify", title="a")), name="one")
    env.create(linear(node("n", "notify", title="b")), name="two")
    res = env.client.post(wf_url(env), json={"name": "three"})
    assert res.status_code == 409 and res.json()["error"]["code"] == "workflow_limit_reached"

    monkeypatch.setattr(settings, "workflow_max_active_runs", 1)
    wid = env.client.get(wf_url(env)).json()["items"][0]["id"]
    env.client.post(
        wf_url(env, f"/{wid}/versions"),
        json={"definition": linear(node("w", "delay", amount=1, unit="hours"))},
    )
    env.start(wid, env.lead("A", "a@x.example")["id"])
    res = env.client.post(
        wf_url(env, f"/{wid}/runs"),
        json={"subject_type": "lead", "subject_id": env.lead("B", "b@x.example")["id"]},
    )
    assert res.status_code == 429 and res.json()["error"]["code"] == "workflow_limit_reached"
    monkeypatch.setattr(settings, "workflow_max_active_runs", 50)
    monkeypatch.setattr(settings, "workflow_max_runs_per_day", 1)
    res = env.client.post(
        wf_url(env, f"/{wid}/runs"),
        json={"subject_type": "lead", "subject_id": env.lead("C", "c@x.example")["id"]},
    )
    assert res.status_code == 429


# ----------------------------------------------------------------------------- isolation and permissions


def test_nothing_leaks_between_workspaces(
    env: WfEnv, client: TestClient, db: DbSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    wid = env.create(approval_flow(send=False), activate=True)
    lead = env.lead()
    run_id = env.start(wid, lead["id"])["run"]["id"]
    env.drain()
    approval = env.approvals()[0]
    stranger_client = second_client(client)
    stranger = WfEnv(stranger_client, db, monkeypatch)
    base = f"/api/v1/workspaces/{stranger.wid}"
    for path in (f"/workflows/{wid}", f"/workflow-runs/{run_id}", f"/approvals/{approval['id']}"):
        assert stranger_client.get(base + path).status_code == 404
    assert (
        stranger_client.post(
            f"{base}/approvals/{approval['id']}/decide", json={"decision": "approve"}
        ).status_code
        == 404
    )
    assert stranger_client.post(f"{base}/workflow-runs/{run_id}/cancel").status_code == 404
    # the stranger cannot even name another workspace
    other = f"/api/v1/workspaces/{env.wid}"
    assert stranger_client.get(f"{other}/workflows").status_code == 404
    # nor start their own workflow on someone else's lead
    own = stranger.create(linear(node("n", "notify", title="x")))
    res = stranger_client.post(
        f"{base}/workflows/{own}/runs", json={"subject_type": "lead", "subject_id": lead["id"]}
    )
    assert res.status_code == 404
    assert stranger_client.get(f"{base}/workflow-runs").json()["total"] == 0
    assert stranger_client.get(f"{base}/approvals", params={"status": "all"}).json()["total"] == 0


def test_members_can_look_but_not_change(env: WfEnv, client: TestClient, db: DbSession) -> None:
    wid = env.create(linear(node("n", "notify", title="x")), activate=True)
    run_id = env.start(wid, env.lead()["id"])["run"]["id"]
    other = second_client(client)
    member = make_user(other, name="Member")
    me = member["me"]
    add_member(db, env.wid, (me.get("user") or me)["id"])
    base = f"/api/v1/workspaces/{env.wid}"
    for path in (
        "/workflows",
        "/workflows/catalog",
        f"/workflows/{wid}",
        f"/workflow-runs/{run_id}",
        "/approvals",
    ):
        assert other.get(base + path).status_code == 200, path
    assert (
        other.post(
            f"{base}/workflows/validate",
            json={"definition": linear(node("n", "notify", title="x"))},
        ).status_code
        == 200
    )
    writes = [
        ("post", "/workflows", {"name": "x"}),
        ("patch", f"/workflows/{wid}", {"name": "y"}),
        (
            "post",
            f"/workflows/{wid}/versions",
            {"definition": linear(node("n", "notify", title="x"))},
        ),
        ("post", f"/workflows/{wid}/activate", {}),
        ("post", f"/workflows/{wid}/pause", None),
        ("post", f"/workflows/{wid}/archive", None),
        ("post", f"/workflows/{wid}/mode", {"mode": "live", "confirm": True}),
        (
            "post",
            f"/workflows/{wid}/runs",
            {"subject_type": "lead", "subject_id": str(uuid.uuid4())},
        ),
        ("post", f"/workflow-runs/{run_id}/cancel", None),
        ("post", f"/workflow-runs/{run_id}/retry", None),
    ]
    for method, path, body in writes:
        res = getattr(other, method)(base + path, **({"json": body} if body is not None else {}))
        assert res.status_code == 403, (method, path, res.text)


# ----------------------------------------------------------------------------- what is (not) stored and logged


def test_runs_never_store_message_text_or_addresses(
    client: TestClient, db: DbSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = WfEnv(client, db, monkeypatch, mailbox=True)
    lead = env.lead(email="private.person@secret-domain.example")
    wid = env.create(approval_flow(), activate=True, live=True)
    run_id = env.start(wid, lead["id"])["run"]["id"]
    env.drain()
    approval = env.approvals()[0]
    env.decide(approval["id"], "approve")
    env.drain()
    draft = env.draft(approval["draft_id"])
    blob = json.dumps(
        [env.run(run_id), env.approvals(None), env.client.get(env.url("/workflow-runs")).json()],
        default=str,
    )
    assert "secret-domain.example" not in blob and "private.person" not in blob
    assert draft.body_text[:40] not in blob and draft.subject not in blob
    # nor do the stored step rows and approvals
    stored = json.dumps(
        [(s.input_summary, s.output_summary, s.error_summary) for s in env.step_rows(run_id)]
        + [(a.proposed_payload, a.decision_note) for a in env.approval_rows(run_id)]
        + [env.row(run_id).context, env.row(run_id).trigger_payload],
        default=str,
    )
    assert (
        "secret-domain.example" not in stored
        and draft.subject not in stored
        and draft.body_text[:40] not in stored
    )
    # and the audit trail only has ids, states and reason codes
    env.db.expire_all()
    events = env.db.scalars(
        select(AuditEvent).where(
            AuditEvent.workspace_id == uuid.UUID(env.wid), AuditEvent.action.like("workflow.%")
        )
    ).all()
    actions = {e.action for e in events}
    assert {
        "workflow.created",
        "workflow.activated",
        "workflow.mode_changed",
        "workflow.run_started",
        "workflow.approval_decided",
        "workflow.run_finished",
    } <= actions
    assert "secret-domain.example" not in json.dumps([e.details for e in events], default=str)


def test_step_summaries_are_reduced_to_short_scalars() -> None:
    from app.workflows.runtime import safe_summary

    out = safe_summary(
        {
            "ok": True,
            "n": 3,
            "text": "x" * 500 + "\nsecond line\x00",
            "nested": {"a": 1},
            "obj": object(),
            "many": list(range(50)),
            "nothing": None,
            "k" * 100: "v",
        }
    )
    assert out["ok"] is True and out["n"] == 3 and out["nothing"] is None
    assert len(out["text"]) == 120 and "\n" not in out["text"] and "\x00" not in out["text"]
    assert out["nested"] is None and out["obj"] is None
    assert len(out["many"]) == 10
    assert all(len(k) <= 40 for k in out)


# ----------------------------------------------------------------------------- the worker command, migration and seed


def test_the_worker_command_runs_due_runs(
    env: WfEnv, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from app import cli

    monkeypatch.setattr(
        "app.workflows.engine.run_worker", real_run_worker
    )  # the fixture switches it off
    wid = env.create(linear(node("n", "notify", title="from the cli")))
    run_id = env.start(wid, env.lead()["id"])["run"]["id"]
    assert cli.main(["process-workflows"]) == 0
    assert env.status(run_id) == "succeeded"
    assert "claimed=" in capsys.readouterr().out


def test_the_seeded_starter_workflow_is_valid(db: DbSession) -> None:
    from sqlalchemy import select

    from app.db.models_workflow import Workflow, WorkflowVersion
    from app.seed import seed_demo
    from app.services.workflow_defs import definition_of
    from app.workflows.validate import validate_definition
    from tests.conftest import reset_demo

    reset_demo(db)
    created, wid = seed_demo(db)
    db.commit()
    assert created
    wf = db.scalar(select(Workflow).where(Workflow.workspace_id == wid))
    assert wf is not None and wf.status == "draft" and wf.mode == "test"
    version = db.scalar(select(WorkflowVersion).where(WorkflowVersion.workflow_id == wf.id))
    assert version is not None and version.valid and version.trigger_event == "lead_created"
    assert validate_definition(definition_of(db, version)).valid
    reset_demo(db)


def test_migration_0009_adds_and_removes_the_engine_columns() -> None:
    from sqlalchemy import inspect

    from app.db.session import get_engine
    from tests.test_migrations import at_revision

    def cols(table: str) -> set[str]:
        return {c["name"] for c in inspect(get_engine()).get_columns(table)}

    run_cols = {
        "subject_type",
        "subject_id",
        "current_node_key",
        "context",
        "steps_taken",
        "attempt_floor",
        "locked_until",
        "lock_token",
        "cancel_requested_at",
        "started_by_user_id",
    }
    assert run_cols <= cols("workflow_runs") and {"valid", "issues", "trigger_event"} <= cols(
        "workflow_versions"
    )
    assert "port" in cols("workflow_step_runs") and "trigger_event" in cols("workflows")
    with at_revision("0008"):
        assert not (run_cols & cols("workflow_runs")) and "valid" not in cols("workflow_versions")
        assert "port" not in cols("workflow_step_runs") and "trigger_event" not in cols("workflows")
        assert {"correlation_id", "wake_at"} <= cols("workflow_runs")  # nothing else was touched
    assert run_cols <= cols("workflow_runs")
