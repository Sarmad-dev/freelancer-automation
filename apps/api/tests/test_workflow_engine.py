"""The execution engine: running graphs, branching, approvals, delays, retries, duplicates, cancellation and recovery."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DbSession

from tests.workflow_helpers import (
    WfEnv,
    approval_flow,
    edge,
    graph,
    linear,
    node,
)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


@pytest.fixture
def env(client: TestClient, db: DbSession, monkeypatch: pytest.MonkeyPatch) -> WfEnv:
    return WfEnv(client, db, monkeypatch)


# ----------------------------------------------------------------------------- a simple run


def test_a_run_walks_the_graph_and_records_every_step(env: WfEnv) -> None:
    lead = env.lead()
    wf = env.create(
        linear(
            node("task", "create_task", title="Call {lead_title}", due_in_days=2),
            node("note", "notify", title="Done for {company_name}"),
        )
    )
    started = env.start(wf, lead["id"])
    run_id = started["run"]["id"]
    assert started["created"] and started["run"]["status"] == "queued"
    assert env.work().claimed == 1
    run = env.run(run_id)
    assert run["status"] == "succeeded" and run["finished_at"] and run["error_category"] is None
    assert [(s["node_key"], s["status"], s["port"]) for s in run["steps"]] == [
        ("t", "succeeded", "next"),
        ("task", "succeeded", "next"),
        ("note", "succeeded", "next"),
        ("end", "succeeded", None),
    ]
    assert all(s["started_at"] and s["finished_at"] and s["attempt"] == 1 for s in run["steps"])
    task_out = next(s for s in run["steps"] if s["node_key"] == "task")["output_summary"]
    assert task_out["created"] is True
    # the task and the notification exist, rendered from the allow-listed placeholders
    tasks = env.client.get(env.url("/tasks")).json()["items"]
    assert [t["title"] for t in tasks] == ["Call Acme website"]
    assert tasks[0]["created_by"] == "workflow" and tasks[0]["lead"]["id"] == lead["id"]
    assert run["correlation_id"] and run["version"] == 1 and run["mode"] == "test"


def test_a_run_is_pinned_to_the_version_it_started_with(env: WfEnv) -> None:
    lead = env.lead()
    wf = env.create(linear(node("n", "notify", title="from version one")), activate=True)
    run_id = env.start(wf, lead["id"])["run"]["id"]
    v2 = linear(node("n", "notify", title="from version two"), node("m", "notify", title="extra"))
    assert (
        env.client.post(env.url(f"/workflows/{wf}/versions"), json={"definition": v2}).status_code
        == 201
    )
    assert env.client.post(env.url(f"/workflows/{wf}/activate"), json={}).status_code == 200
    env.drain()
    run = env.run(run_id)
    assert run["version"] == 1 and run["status"] == "succeeded"
    assert [s["node_key"] for s in run["steps"]] == [
        "t",
        "n",
        "end",
    ]  # version two's extra step never ran
    later = env.start(wf, env.lead("Other lead", "o@acme.example")["id"])["run"]
    assert later["version"] == 2


# ----------------------------------------------------------------------------- branching


def branch_flow(field: str = "lead.has_contact_email") -> dict:  # type: ignore[type-arg]
    return graph(
        [
            node("t", "trigger", event="manual", subject="lead"),
            node("c", "condition", field=field, op="is_true"),
            node("yes", "notify", title="has email"),
            node("done", "end", reason="emailed"),
            node("no", "create_task", title="Find an email for {lead_title}"),
            node("stop", "end", reason="no email"),
        ],
        [
            edge("t", "c"),
            edge("c", "yes", "true"),
            edge("c", "no", "false"),
            edge("yes", "done"),
            edge("no", "stop"),
        ],
    )


def test_a_condition_sends_the_run_down_exactly_one_branch(env: WfEnv) -> None:
    wf = env.create(branch_flow())
    with_email = env.start(wf, env.lead("Has email", "a@acme.example")["id"])["run"]["id"]
    without = env.start(wf, env.lead("No email", None)["id"])["run"]["id"]
    env.drain()
    yes = env.run(with_email)
    no = env.run(without)
    assert [s["node_key"] for s in yes["steps"]] == ["t", "c", "yes", "done"]
    assert [s["node_key"] for s in no["steps"]] == ["t", "c", "no", "stop"]
    assert next(s for s in yes["steps"] if s["node_key"] == "c")["port"] == "true"
    assert next(s for s in no["steps"] if s["node_key"] == "c")["port"] == "false"
    assert next(s for s in no["steps"] if s["node_key"] == "c")["output_summary"]["result"] is False
    assert yes["status"] == no["status"] == "succeeded"


def test_an_end_node_can_finish_a_run_as_a_failure(env: WfEnv) -> None:
    definition = graph(
        [
            node("t", "trigger", event="manual", subject="lead"),
            node("e", "end", outcome="failure", reason="Not a fit"),
        ],
        [edge("t", "e")],
    )
    wf = env.create(definition)
    run_id = env.start(wf, env.lead()["id"])["run"]["id"]
    env.drain()
    run = env.run(run_id)
    assert run["status"] == "failed" and run["error_category"] == "ended_as_failure"
    assert run["error_summary"] == "Not a fit"
    # an ending the workflow chose is not an error to retry
    assert env.client.post(env.url(f"/workflow-runs/{run_id}/retry")).status_code == 409


# ----------------------------------------------------------------------------- AI steps


def test_ai_steps_record_what_they_found_and_a_condition_can_use_it(env: WfEnv) -> None:
    definition = graph(
        [
            node("t", "trigger", event="manual", subject="lead"),
            node("fit", "ai_assess_fit"),
            node(
                "c",
                "condition",
                field="fit.rating",
                op="in",
                value=["strong", "possible", "weak", "unknown"],
            ),
            node("n", "notify", title="Fit: {fit_rating}"),
            node("end", "end"),
            node("other", "end"),
        ],
        [
            edge("t", "fit"),
            edge("fit", "c"),
            edge("c", "n", "true"),
            edge("c", "other", "false"),
            edge("n", "end"),
        ],
    )
    wf = env.create(definition)
    run_id = env.start(wf, env.lead()["id"])["run"]["id"]
    env.drain()
    run = env.run(run_id)
    assert run["status"] == "succeeded", run["error_summary"]
    out = next(s for s in run["steps"] if s["node_key"] == "fit")["output_summary"]
    assert out["assessment"] in ("strong", "possible", "weak", "unknown") and out["demo_ai"] is True
    assert run["context"]["fit"]["rating"] == out["assessment"]
    notes = env.client.get(env.url("/notifications")).json()["items"]
    assert any(n["title"].startswith("Fit: ") and n["title"] != "Fit: " for n in notes)


# ----------------------------------------------------------------------------- approval: the durable pause


@pytest.fixture
def mail(client: TestClient, db: DbSession, monkeypatch: pytest.MonkeyPatch) -> WfEnv:
    return WfEnv(client, db, monkeypatch, mailbox=True)


def start_to_approval(
    env: WfEnv, *, live: bool, lead_title: str = "Acme website"
) -> tuple[str, str, dict]:  # type: ignore[type-arg]
    lead = env.lead(lead_title)
    wf = env.create(approval_flow(), activate=True, live=live)
    run_id = env.start(wf, lead["id"])["run"]["id"]
    env.drain()
    return wf, run_id, lead


def test_an_approval_gate_pauses_the_run_durably_and_nothing_is_sent_meanwhile(mail: WfEnv) -> None:
    _wf, run_id, _lead = start_to_approval(mail, live=True)
    run = mail.run(run_id)
    assert run["status"] == "waiting_approval" and run["current_node_key"] == "g"
    assert [(s["node_key"], s["status"]) for s in run["steps"]] == [
        ("t", "succeeded"),
        ("d", "succeeded"),
        ("g", "waiting"),
    ]
    (approval,) = mail.approvals()
    assert (
        approval["run_id"] == run_id
        and approval["status"] == "pending"
        and approval["kind"] == "send_email"
    )
    assert approval["mode"] == "live" and approval["draft_id"] and approval["expires_at"]
    assert mail.draft(approval["draft_id"]).status == "pending_approval"
    # time passing, workers running again and again: still waiting, nothing sent
    for _ in range(3):
        mail.clock.advance(hours=1)
        assert mail.work().claimed == 0
    assert mail.status(run_id) == "waiting_approval"
    assert mail.fake is not None and mail.fake.sent == []


def test_an_approval_resumes_the_run_and_the_approved_text_is_sent_exactly_once(
    mail: WfEnv,
) -> None:
    _wf, run_id, _lead = start_to_approval(mail, live=True)
    (approval,) = mail.approvals()
    decided = mail.decide(approval["id"], "approve")
    assert decided["status"] == "approved" and decided["decided_at"]
    assert mail.status(run_id) == "queued"  # the decision made the run due; the worker continues it
    mail.drain()
    run = mail.run(run_id)
    assert run["status"] == "succeeded", run["error_summary"]
    assert [s["node_key"] for s in run["steps"]] == ["t", "d", "g", "s", "end"]
    assert mail.fake is not None and len(mail.fake.sent) == 1
    sent = mail.fake.sent[0]
    draft = mail.draft(approval["draft_id"])
    assert (
        draft.status == "sent"
        and sent.subject == draft.subject
        and sent.body_text == draft.body_text
    )
    assert (
        next(s for s in run["steps"] if s["node_key"] == "s")["output_summary"]["delivery_state"]
        == "sent"
    )
    # running the worker again changes nothing
    mail.drain()
    assert len(mail.fake.sent) == 1


def test_test_mode_runs_everything_except_the_real_send(mail: WfEnv) -> None:
    _wf, run_id, _lead = start_to_approval(mail, live=False)
    (approval,) = mail.approvals()
    assert approval["mode"] == "test"
    mail.decide(approval["id"], "approve")
    mail.drain()
    run = mail.run(run_id)
    assert run["status"] == "succeeded"
    out = next(s for s in run["steps"] if s["node_key"] == "s")["output_summary"]
    assert out["simulated"] is True
    assert mail.fake is not None and mail.fake.sent == []
    assert mail.draft(approval["draft_id"]).status == "approved"  # approved, but never sent


def test_a_rejection_takes_the_rejected_branch_and_frees_the_draft(mail: WfEnv) -> None:
    _wf, run_id, _lead = start_to_approval(mail, live=True)
    (approval,) = mail.approvals()
    mail.decide(approval["id"], "reject")
    mail.drain()
    run = mail.run(run_id)
    assert run["status"] == "succeeded"
    assert [s["node_key"] for s in run["steps"]] == ["t", "d", "g", "no"]
    assert next(s for s in run["steps"] if s["node_key"] == "g")["port"] == "rejected"
    assert mail.fake is not None and mail.fake.sent == []
    assert mail.draft(approval["draft_id"]).status == "draft"


def test_an_approval_that_is_not_decided_in_time_expires_and_takes_the_rejected_branch(
    mail: WfEnv,
) -> None:
    _wf, run_id, _lead = start_to_approval(mail, live=True)
    mail.clock.advance(hours=25)
    stats = mail.work()
    assert (
        stats.approvals_expired >= 1
    )  # (the worker serves every workspace; tests share one database)
    mail.drain()
    run = mail.run(run_id)
    assert run["status"] == "succeeded" and [s["node_key"] for s in run["steps"]][-1] == "no"
    assert [a["status"] for a in mail.approvals(None)] == ["expired"]
    # it cannot be approved afterwards
    approval_id = mail.approvals("expired")[0]["id"]
    mail.decide(approval_id, "approve", expect=409)
    assert mail.fake is not None and mail.fake.sent == []


def test_editing_the_draft_voids_the_approval_and_the_run_stops_instead_of_sending_unseen_text(
    mail: WfEnv,
) -> None:
    _wf, run_id, _lead = start_to_approval(mail, live=True)
    (approval,) = mail.approvals()
    res = mail.client.patch(
        mail.url(f"/drafts/{approval['draft_id']}"),
        json={"body_text": "A completely different message."},
    )
    assert res.status_code == 200, res.text
    assert mail.approvals(None)[0]["status"] == "invalidated"
    mail.decide(approval["id"], "approve", expect=409)
    mail.drain()
    run = mail.run(run_id)
    assert run["status"] == "failed" and run["error_category"] == "approval_invalidated"
    assert mail.fake is not None and mail.fake.sent == []
    # a person can retry: a fresh approval is requested for the new text, and approving that sends the new text
    assert mail.client.post(mail.url(f"/workflow-runs/{run_id}/retry")).status_code == 200
    mail.drain()
    assert mail.status(run_id) == "waiting_approval"
    new = mail.approvals()[0]
    assert new["id"] != approval["id"]
    mail.decide(new["id"], "approve")
    mail.drain()
    assert mail.status(run_id) == "succeeded"
    assert [m.body_text for m in mail.fake.sent] == ["A completely different message."]


def test_only_the_owner_decides_and_members_can_only_look(
    client: TestClient, db: DbSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.conftest import add_member, make_user, second_client

    env = WfEnv(client, db, monkeypatch, mailbox=True)
    _wf, run_id, _lead = start_to_approval(env, live=True)
    (approval,) = env.approvals()
    other = second_client(client)
    member = make_user(other, name="Member")
    add_member(
        db, env.wid, member["me"]["user"]["id"] if "user" in member["me"] else member["me"]["id"]
    )
    base = f"/api/v1/workspaces/{env.wid}"
    assert other.get(f"{base}/approvals").status_code == 200
    assert other.get(f"{base}/workflow-runs/{run_id}").status_code == 200
    assert (
        other.post(
            f"{base}/approvals/{approval['id']}/decide", json={"decision": "approve"}
        ).status_code
        == 403
    )
    assert other.post(f"{base}/workflow-runs/{run_id}/cancel").status_code == 403
    assert other.post(f"{base}/workflow-runs/{run_id}/retry").status_code == 403
    assert env.status(run_id) == "waiting_approval"


def test_a_contact_who_opted_out_after_approval_is_never_sent_to(mail: WfEnv) -> None:
    _wf, run_id, _lead = start_to_approval(mail, live=True)
    (approval,) = mail.approvals()
    mail.decide(approval["id"], "approve")
    mail.suppress("sam@acme.example")  # they unsubscribe between the approval and the send
    mail.drain()
    run = mail.run(run_id)
    assert run["status"] == "failed" and run["error_category"] == "suppressed"
    assert mail.fake is not None and mail.fake.sent == []
    assert mail.draft(approval["draft_id"]).status == "approved"


def test_a_suppressed_contact_gets_no_draft_at_all(mail: WfEnv) -> None:
    mail.suppress("sam@acme.example")
    lead = mail.lead("Opted out", "sam@acme.example")
    wf = mail.create(approval_flow(), activate=True)
    run_id = mail.start(wf, lead["id"])["run"]["id"]
    mail.drain()
    run = mail.run(run_id)
    assert run["status"] == "failed" and run["error_category"] == "suppressed"
    assert mail.approvals(None) == []


# ----------------------------------------------------------------------------- delays


def test_a_delay_waits_in_the_database_and_resumes_when_it_is_due(env: WfEnv) -> None:
    definition = linear(
        node("before", "notify", title="before"),
        node("w", "delay", amount=2, unit="hours"),
        node("after", "notify", title="after"),
    )
    wf = env.create(definition)
    run_id = env.start(wf, env.lead()["id"])["run"]["id"]
    env.drain()
    run = env.run(run_id)
    assert run["status"] == "waiting_delay" and run["current_node_key"] == "w" and run["wake_at"]
    assert [(s["node_key"], s["status"]) for s in run["steps"]][-1] == ("w", "waiting")
    # not due: workers come and go, nothing is claimed, nothing is held open
    env.clock.advance(minutes=119)
    assert env.work().claimed == 0
    assert env.status(run_id) == "waiting_delay"
    env.clock.advance(minutes=2)
    assert env.work().claimed == 1
    run = env.run(run_id)
    assert run["status"] == "succeeded"
    assert [s["node_key"] for s in run["steps"]] == ["t", "before", "w", "after", "end"]
    assert next(s for s in run["steps"] if s["node_key"] == "w")["status"] == "succeeded"
    titles = [n["title"] for n in env.client.get(env.url("/notifications")).json()["items"]]
    assert titles.count("after") == 1


def test_a_delay_survives_a_restart_because_it_is_only_rows(env: WfEnv) -> None:
    wf = env.create(
        linear(node("w", "delay", amount=1, unit="days"), node("n", "notify", title="later"))
    )
    run_id = env.start(wf, env.lead()["id"])["run"]["id"]
    env.drain()
    env.client.app.state.ai_provider = None  # (nothing in memory matters)
    first = env.deps()
    env.clock.advance(days=1, minutes=1)
    from app.db.session import get_sessionmaker
    from app.workflows import engine
    import uuid

    stats = engine.process_batch(
        get_sessionmaker(), first, workspace_id=uuid.UUID(env.wid)
    )  # a brand-new "process"
    assert stats.claimed == 1 and env.status(run_id) == "succeeded"


# ----------------------------------------------------------------------------- retries


ASSESS_OK = {
    "assessment": "possible",
    "confidence": 0.6,
    "reasons": [{"statement": "The lead is a website project.", "evidence_field": "title"}],
    "gaps": [],
}


def assess_flow() -> dict:  # type: ignore[type-arg]
    return linear(node("fit", "ai_assess_fit"))


def test_a_retryable_failure_is_retried_with_backoff_and_then_succeeds(env: WfEnv) -> None:
    from app.ai.errors import ProviderTimeout
    from tests.ai_helpers import ScriptedProvider

    provider = ScriptedProvider(ProviderTimeout(), ProviderTimeout(), ASSESS_OK)
    env.use_ai(provider)
    run_id = env.start(env.create(assess_flow()), env.lead()["id"])["run"]["id"]
    env.drain()
    run = env.run(run_id)
    assert run["status"] == "queued" and run["wake_at"]  # waiting out the backoff, not failed
    first = next(s for s in run["steps"] if s["node_key"] == "fit")
    assert (first["attempt"], first["status"], first["error_category"]) == (
        1,
        "failed",
        "ai_unavailable",
    )
    assert first["next_attempt_at"]
    assert env.work().claimed == 0  # too early: the backoff has not passed
    env.clock.advance(seconds=31)
    env.drain()
    run = env.run(run_id)
    assert run["status"] == "succeeded"
    assert [
        (s["node_key"], s["attempt"], s["status"]) for s in run["steps"] if s["node_key"] == "fit"
    ] == [
        ("fit", 1, "failed"),
        ("fit", 2, "succeeded"),
    ]


def test_retries_stop_at_the_nodes_attempt_limit_and_a_person_can_retry_by_hand(env: WfEnv) -> None:
    from app.ai.errors import ProviderTimeout
    from tests.ai_helpers import ScriptedProvider

    provider = ScriptedProvider(ProviderTimeout())  # always failing
    env.use_ai(provider)
    definition = linear(node("fit", "ai_assess_fit", max_attempts=2))
    run_id = env.start(env.create(definition), env.lead()["id"])["run"]["id"]
    for _ in range(4):
        env.drain()
        env.clock.advance(minutes=15)
    run = env.run(run_id)
    assert run["status"] == "failed" and run["error_category"] == "ai_unavailable"
    assert [(s["attempt"], s["status"]) for s in run["steps"] if s["node_key"] == "fit"] == [
        (1, "failed"),
        (2, "failed"),
    ]
    calls = provider.calls
    env.clock.advance(hours=3)
    env.drain()
    assert provider.calls == calls  # failed means failed: nothing keeps trying
    # the service recovers; a person presses retry
    env.use_ai(ScriptedProvider(ASSESS_OK))
    res = env.client.post(env.url(f"/workflow-runs/{run_id}/retry"))
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "queued"
    env.drain()
    run = env.run(run_id)
    assert run["status"] == "succeeded"
    assert [(s["attempt"], s["status"]) for s in run["steps"] if s["node_key"] == "fit"] == [
        (1, "failed"),
        (2, "failed"),
        (3, "succeeded"),
    ]
    assert (
        env.client.post(env.url(f"/workflow-runs/{run_id}/retry")).status_code == 409
    )  # nothing failed any more


def test_a_failure_that_cannot_succeed_is_not_retried(env: WfEnv) -> None:
    lead = env.lead(email=None)  # nobody to write to
    wf = env.create(linear(node("d", "ai_draft")))
    run_id = env.start(wf, lead["id"])["run"]["id"]
    env.drain()
    run = env.run(run_id)
    assert run["status"] == "failed" and run["error_category"] == "missing_data"
    assert [(s["node_key"], s["attempt"]) for s in run["steps"] if s["status"] == "failed"] == [
        ("d", 1)
    ]
    assert "@" not in str(run)  # failures carry fixed text, never addresses or message content


def test_an_unsafe_ai_answer_is_an_ai_invalid_output_failure_that_retries_then_stops(
    env: WfEnv,
) -> None:
    from tests.ai_helpers import ScriptedProvider

    env.use_ai(ScriptedProvider("this is not json"))
    wf = env.create(linear(node("fit", "ai_assess_fit", max_attempts=2)))
    run_id = env.start(wf, env.lead()["id"])["run"]["id"]
    for _ in range(3):
        env.drain()
        env.clock.advance(minutes=15)
    run = env.run(run_id)
    assert run["status"] == "failed" and run["error_category"] == "ai_invalid_output"
    assert [s["attempt"] for s in run["steps"] if s["node_key"] == "fit"] == [1, 2]


def test_not_enough_approved_information_stops_the_draft_with_a_clear_reason(
    client: TestClient, db: DbSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = WfEnv(client, db, monkeypatch, facts=False)
    wf = env.create(linear(node("d", "ai_draft")))
    run_id = env.start(wf, env.lead()["id"])["run"]["id"]
    env.drain()
    run = env.run(run_id)
    assert run["status"] == "failed" and run["error_category"] == "insufficient_context"
    assert len([s for s in run["steps"] if s["node_key"] == "d"]) == 1


# ----------------------------------------------------------------------------- duplicate events and concurrency


def test_the_same_event_cannot_start_a_workflow_twice(env: WfEnv) -> None:
    lead = env.lead()
    wf = env.create(linear(node("w", "delay", amount=1, unit="hours")), activate=True)
    first = env.start(wf, lead["id"], key="event-lead-created-1")
    again = env.start(wf, lead["id"], key="event-lead-created-1", expect=200)
    assert first["created"] is True and again["created"] is False
    assert again["run"]["id"] == first["run"]["id"]
    runs = env.client.get(env.url("/workflow-runs"), params={"workflow_id": wf}).json()
    assert runs["total"] == 1


def test_a_workflow_does_not_run_twice_at_once_for_the_same_lead(env: WfEnv) -> None:
    lead = env.lead()
    wf = env.create(linear(node("w", "delay", amount=1, unit="hours")))
    first = env.start(wf, lead["id"])
    res = env.client.post(
        env.url(f"/workflows/{wf}/runs"), json={"subject_type": "lead", "subject_id": lead["id"]}
    )
    assert res.status_code == 409 and res.json()["error"]["code"] == "run_in_progress"
    other = env.lead("Another", "b@acme.example")
    assert env.start(wf, other["id"])["run"]["id"] != first["run"]["id"]
    # once the first finishes, the lead can be run again
    env.drain()
    env.clock.advance(hours=2)
    env.drain()
    assert env.status(first["run"]["id"]) == "succeeded"
    assert env.start(wf, lead["id"])["created"] is True


def test_events_start_each_listening_workflow_once_and_only_when_it_is_switched_on(
    env: WfEnv, db: DbSession
) -> None:
    import uuid
    from datetime import UTC, datetime

    from app.config import get_settings
    from app.workflows import events

    definition = graph(
        [
            node("t", "trigger", event="lead_created"),
            node("n", "notify", title="New lead {lead_title}"),
            node("end", "end"),
        ],
        [edge("t", "n"), edge("n", "end")],
    )
    wf_on = env.create(definition, name="listening", activate=True)
    env.create(definition, name="draft only")  # never switched on
    lead = env.lead(
        "Fresh lead", "f@acme.example"
    )  # the API creates leads too; it queues the active workflow itself
    now = datetime.now(UTC)
    wid = uuid.UUID(env.wid)
    assert (
        events.emit(
            db, get_settings(), wid, "lead_created", "lead", uuid.UUID(lead["id"]), lead["id"], now
        )
        == []
    )
    db.commit()
    runs = env.client.get(env.url("/workflow-runs"), params={"workflow_id": wf_on}).json()
    assert runs["total"] == 1 and runs["items"][0]["trigger_type"] == "lead_created"
    all_runs = env.client.get(env.url("/workflow-runs")).json()
    assert all_runs["total"] == 1  # the draft-only workflow never ran
    env.drain()
    assert env.status(runs["items"][0]["id"]) == "succeeded"
    # another occurrence of a different event, or a different workspace's events, start nothing here
    assert (
        events.emit(
            db, get_settings(), wid, "reply_received", "conversation", uuid.uuid4(), "x", now
        )
        == []
    )
    assert (
        events.emit(
            db, get_settings(), uuid.uuid4(), "lead_created", "lead", uuid.uuid4(), "y", now
        )
        == []
    )


# ----------------------------------------------------------------------------- cancellation


def test_cancelling_a_waiting_run_cancels_its_open_approval_and_frees_the_draft(
    mail: WfEnv,
) -> None:
    _wf, run_id, _lead = start_to_approval(mail, live=True)
    (approval,) = mail.approvals()
    res = mail.client.post(mail.url(f"/workflow-runs/{run_id}/cancel"))
    assert res.status_code == 200 and res.json()["status"] == "cancelled"
    run = mail.run(run_id)
    assert run["status"] == "cancelled" and run["finished_at"]
    assert [a["status"] for a in run["approvals"]] == ["cancelled"]
    assert next(s for s in run["steps"] if s["node_key"] == "g")["status"] == "cancelled"
    assert mail.draft(approval["draft_id"]).status == "draft"
    mail.decide(approval["id"], "approve", expect=409)  # too late
    mail.drain()
    assert mail.fake is not None and mail.fake.sent == []
    # cancelling again is harmless; cancelling a finished run is refused
    assert (
        mail.client.post(mail.url(f"/workflow-runs/{run_id}/cancel")).json()["status"]
        == "cancelled"
    )


def test_cancelling_a_delayed_run_stops_it_and_a_finished_run_cannot_be_cancelled(
    env: WfEnv,
) -> None:
    wf = env.create(
        linear(node("w", "delay", amount=1, unit="hours"), node("n", "notify", title="never"))
    )
    run_id = env.start(wf, env.lead()["id"])["run"]["id"]
    env.drain()
    assert (
        env.client.post(env.url(f"/workflow-runs/{run_id}/cancel")).json()["status"] == "cancelled"
    )
    env.clock.advance(hours=2)
    assert env.work().claimed == 0
    assert [
        n
        for n in env.client.get(env.url("/notifications")).json()["items"]
        if n["title"] == "never"
    ] == []
    done = env.start(
        env.create(linear(node("n", "notify", title="x"))), env.lead("Z", "z@acme.example")["id"]
    )["run"]["id"]
    env.drain()
    res = env.client.post(env.url(f"/workflow-runs/{done}/cancel"))
    assert res.status_code == 409 and res.json()["error"]["code"] == "run_finished"


def test_a_cancel_that_arrives_while_a_worker_holds_the_run_stops_it_before_its_next_step(
    env: WfEnv,
) -> None:
    from app.db.session import get_sessionmaker
    from app.workflows import engine

    wf = env.create(linear(node("n", "notify", title="one"), node("m", "notify", title="two")))
    run_id = env.start(wf, env.lead()["id"])["run"]["id"]
    deps = env.deps()
    with get_sessionmaker()() as db:
        import uuid

        (claimed,) = engine.claim_runs(db, deps.now(), 10, uuid.UUID(env.wid))
    assert env.status(run_id) == "running"
    res = env.client.post(env.url(f"/workflow-runs/{run_id}/cancel"))
    assert res.json()["status"] == "cancelling" and env.run(run_id)["cancel_requested"] is True
    stats = engine.BatchStats()
    engine.process_run(get_sessionmaker(), deps, claimed[0], claimed[1], stats)
    run = env.run(run_id)
    assert run["status"] == "cancelled" and stats.finished == 1
    assert [s["node_key"] for s in run["steps"]] == []  # it stopped before running anything


# ----------------------------------------------------------------------------- crashes and leases


def test_two_workers_cannot_take_the_same_run(env: WfEnv) -> None:
    import uuid

    from app.db.session import get_sessionmaker
    from app.workflows import engine

    env.start(env.create(linear(node("n", "notify", title="x"))), env.lead()["id"])
    deps = env.deps()
    wid = uuid.UUID(env.wid)
    with get_sessionmaker()() as a, get_sessionmaker()() as b:
        first = engine.claim_runs(a, deps.now(), 10, wid)
        second = engine.claim_runs(b, deps.now(), 10, wid)
    assert len(first) == 1 and second == []


def test_a_run_whose_worker_died_is_recovered_after_its_lease_expires(env: WfEnv) -> None:
    import uuid

    from app.db.session import get_sessionmaker
    from app.workflows import engine

    wf = env.create(linear(node("n", "notify", title="once")))
    run_id = env.start(wf, env.lead()["id"])["run"]["id"]
    deps = env.deps()
    with get_sessionmaker()() as db:
        (old,) = engine.claim_runs(db, deps.now(), 10, uuid.UUID(env.wid))
    # the worker vanished: lease still valid, so nobody else touches it
    assert env.work().claimed == 0 and env.status(run_id) == "running"
    env.clock.advance(minutes=6)
    assert env.work().claimed == 1
    assert env.status(run_id) == "succeeded"
    # the old worker comes back from the dead: it finds the lease is not its own and changes nothing
    stats = engine.BatchStats()
    engine.process_run(get_sessionmaker(), env.deps(), old[0], old[1], stats)
    assert stats.lost_lease == 1
    titles = [n["title"] for n in env.client.get(env.url("/notifications")).json()["items"]]
    assert titles.count("once") == 1


def test_a_step_interrupted_mid_way_is_retried_and_counted(
    env: WfEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.workflows import engine

    wf = env.create(linear(node("n", "notify", title="after the crash")))
    run_id = env.start(wf, env.lead()["id"])["run"]["id"]
    real = engine._apply_result
    calls = {"n": 0}

    def crash_once(*args: object, **kw: object) -> str:
        calls["n"] += 1
        if (
            calls["n"] == 2
        ):  # the notify step: the worker "dies" after the effect, before recording the result
            raise SystemError("worker died")
        return real(*args, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(engine, "_apply_result", crash_once)
    stats = env.work()
    assert stats.errors == 1
    assert env.status(run_id) == "running"
    assert [(k, a, s) for k, a, s in env.steps(run_id)] == [
        ("t", 1, "succeeded"),
        ("n", 1, "running"),
    ]
    monkeypatch.setattr(engine, "_apply_result", real)
    env.clock.advance(minutes=6)
    env.drain()
    assert (
        env.status(run_id) == "queued"
    )  # recovered, and waiting out the retry backoff like any failed attempt
    env.clock.advance(minutes=1)
    env.drain()
    run = env.run(run_id)
    assert run["status"] == "succeeded"
    assert [(s["node_key"], s["attempt"], s["status"], s["error_category"]) for s in run["steps"]][
        1:3
    ] == [
        ("n", 1, "failed", "interrupted"),
        ("n", 2, "succeeded", None),
    ]
    titles = [n["title"] for n in env.client.get(env.url("/notifications")).json()["items"]]
    assert (
        titles.count("after the crash") == 1
    )  # the effect was recorded once: notifications are idempotent per step


# ----------------------------------------------------------------------------- idempotent sending


def test_a_send_that_happened_but_was_never_recorded_is_not_sent_again(
    mail: WfEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.workflows import engine

    _wf, run_id, _lead = start_to_approval(mail, live=True)
    (approval,) = mail.approvals()
    mail.decide(approval["id"], "approve")
    real = engine._apply_result
    state = {"crashed": False}

    def crash_after_send(*args: object, **kw: object) -> str:
        node = args[2]
        if getattr(node, "type", None) == "send_email" and not state["crashed"]:
            state["crashed"] = True
            raise SystemError("worker died right after the provider accepted the message")
        return real(*args, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(engine, "_apply_result", crash_after_send)
    assert mail.work().errors == 1
    assert mail.fake is not None and len(mail.fake.sent) == 1  # the provider did get it
    monkeypatch.setattr(engine, "_apply_result", real)
    mail.clock.advance(minutes=6)
    mail.drain()
    mail.clock.advance(minutes=2)
    mail.drain()
    run = mail.run(run_id)
    assert run["status"] == "succeeded", run["error_summary"]
    assert len(mail.fake.sent) == 1  # recovered without a second email
    last = [s for s in run["steps"] if s["node_key"] == "s"]
    assert [(s["attempt"], s["status"]) for s in last] == [(1, "failed"), (2, "succeeded")]
    assert last[-1]["output_summary"]["replayed"] is True


def test_a_send_the_provider_never_confirmed_is_never_retried_blindly(mail: WfEnv) -> None:
    from app.mailbox.errors import SendOutcomeUnknown

    from app.mailbox.types import SendResult

    assert mail.fake is not None
    mail.fake.sends = [SendOutcomeUnknown(), SendResult("gm-2", "gt-2", "sent")]
    _wf, run_id, _lead = start_to_approval(mail, live=True)
    (approval,) = mail.approvals()
    mail.decide(approval["id"], "approve")
    mail.drain()
    mail.clock.advance(hours=2)
    mail.drain()
    run = mail.run(run_id)
    assert run["status"] == "failed" and run["error_category"] == "outcome_unknown"
    assert (
        len([s for s in run["steps"] if s["node_key"] == "s"]) == 1
    )  # no automatic second attempt
    assert len(mail.fake.sent) == 1
    res = mail.client.post(mail.url(f"/workflow-runs/{run_id}/retry"))
    assert res.status_code == 409 and res.json()["error"]["code"] == "resolve_send_first"
    # the person checks their mailbox, says it was NOT sent, and only then can the step be retried
    resolved = mail.client.post(
        mail.url(f"/drafts/{approval['draft_id']}/resolve-send"), json={"outcome": "not_sent"}
    )
    assert resolved.status_code == 200, resolved.text
    assert mail.client.post(mail.url(f"/workflow-runs/{run_id}/retry")).status_code == 200
    mail.drain()
    assert mail.status(run_id) == "succeeded" and len(mail.fake.sent) == 2


def test_a_send_blocked_by_a_rate_limit_waits_and_then_goes_out_once(mail: WfEnv) -> None:
    from app.mailbox.errors import RateLimited

    assert mail.fake is not None
    from app.mailbox.types import SendResult

    mail.fake.sends = [RateLimited(retry_after=90), SendResult("gm-3", "gt-3", "sent")]
    _wf, run_id, _lead = start_to_approval(mail, live=True)
    (approval,) = mail.approvals()
    mail.decide(approval["id"], "approve")
    mail.drain()
    run = mail.run(run_id)
    assert run["status"] == "queued"
    failed = next(s for s in run["steps"] if s["node_key"] == "s")
    assert failed["status"] == "failed" and failed["error_category"] == "rate_limited"
    mail.clock.advance(seconds=100)
    mail.drain()
    assert mail.status(run_id) == "succeeded"
    assert (
        len(mail.fake.sent) == 2
    )  # the first call hit the limit (nothing left the provider's door), then one send
    assert mail.draft(approval["draft_id"]).status == "sent"


# ----------------------------------------------------------------------------- records: test mode and live mode


def stage_flow() -> dict:  # type: ignore[type-arg]
    return linear(
        node("move", "upsert_record", action="update_lead", stage_key="contacted"),
        node("deal", "upsert_record", action="create_opportunity", title="Website rebuild"),
    )


def test_record_changes_are_simulated_in_test_mode(env: WfEnv) -> None:
    lead = env.lead()
    run_id = env.start(env.create(stage_flow()), lead["id"])["run"]["id"]
    env.drain()
    run = env.run(run_id)
    assert run["status"] == "succeeded"
    assert all(
        s["output_summary"].get("simulated") is True
        for s in run["steps"]
        if s["node_key"] in ("move", "deal")
    )
    assert env.lead_row(lead["id"]).status == "new"
    assert env.client.get(env.url("/opportunities")).json()["total"] == 0


def test_record_changes_are_real_in_live_mode_and_happen_once(env: WfEnv) -> None:
    lead = env.lead()
    wf = env.create(stage_flow(), live=True)
    run_id = env.start(wf, lead["id"])["run"]["id"]
    env.drain()
    run = env.run(run_id)
    assert run["status"] == "succeeded", run["error_summary"]
    assert env.lead_row(lead["id"]).status == "contacted"
    opps = env.client.get(env.url("/opportunities")).json()
    assert opps["total"] == 1 and opps["items"][0]["title"] == "Website rebuild"
    assert run["context"]["opportunity_id"] == opps["items"][0]["id"]
    env.drain()
    assert env.client.get(env.url("/opportunities")).json()["total"] == 1


def test_a_missing_pipeline_stage_is_a_clear_non_retryable_failure(env: WfEnv) -> None:
    wf = env.create(
        linear(node("move", "upsert_record", action="update_lead", stage_key="nope")), live=True
    )
    run_id = env.start(wf, env.lead()["id"])["run"]["id"]
    env.drain()
    run = env.run(run_id)
    assert run["status"] == "failed" and run["error_category"] == "missing_data"
    assert [s["attempt"] for s in run["steps"] if s["node_key"] == "move"] == [1]


def test_a_task_is_created_once_even_if_its_step_runs_again(env: WfEnv) -> None:
    lead = env.lead()
    wf = env.create(linear(node("task", "create_task", title="Follow up {lead_title}")))
    run_id = env.start(wf, lead["id"])["run"]["id"]
    env.drain()
    key = env.row(run_id).id.hex
    tasks = [
        t
        for t in env.client.get(env.url("/tasks")).json()["items"]
        if t["title"] == "Follow up Acme website"
    ]
    assert len(tasks) == 1
    # run the same step again against the same run (what a retry after a lost result would do)
    import uuid
    from datetime import UTC, datetime

    from app.config import get_settings
    from app.db.models_workflow import WorkflowRun, WorkflowStepRun
    from app.db.session import get_sessionmaker
    from app.workflows import executors
    from app.workflows.engine import load_version
    from app.workflows.runtime import StepEnv, deps_from_app, owner_context

    with get_sessionmaker()() as db:
        run = db.get(WorkflowRun, uuid.UUID(run_id))
        assert run is not None and run.id.hex == key
        loaded = load_version(db, run.workspace_id, run.version_id)
        node_def = loaded.nodes["task"]
        from app.workflows.engine import _parse

        step = db.query(WorkflowStepRun).filter_by(run_id=run.id, node_key="task").one()
        again = StepEnv(
            db=db, run=run, step=step, node_key="task", node_type="create_task", cfg=_parse(node_def), attempt=2,
            ctx=owner_context(db, run.workspace_id), deps=deps_from_app(env.client.app), now=datetime.now(UTC),  # type: ignore[arg-type]
            mode="test", timeout_seconds=30,
        )  # fmt: skip
        result = executors.run_create_task(again)
        assert result.output["created"] is False  # type: ignore[union-attr]
        db.commit()
    tasks = [
        t
        for t in env.client.get(env.url("/tasks")).json()["items"]
        if t["title"] == "Follow up Acme website"
    ]
    assert len(tasks) == 1
    _ = get_settings
