"""The workflow validator: structure, settings, branches, data flow and the "never send without approval" rule."""

from __future__ import annotations

from typing import Any

import pytest

from app.workflows.catalog import NODE_SPECS, DelayConfig, render
from app.workflows.definition import WorkflowDefinition
from app.workflows.validate import Report, validate_definition


def node(id_: str, type_: str, **config: Any) -> dict[str, Any]:
    return {"id": id_, "type": type_, "config": config}


def edge(src: str, dst: str, branch: str | None = None, id_: str | None = None) -> dict[str, Any]:
    return {
        "id": id_ or f"{src}-{dst}-{branch or 'next'}",
        "source": src,
        "target": dst,
        "branch": branch,
    }


def check(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> Report:
    return validate_definition(WorkflowDefinition.model_validate({"nodes": nodes, "edges": edges}))


def codes(report: Report) -> list[str]:
    return sorted({i.code for i in report.issues})


TRIGGER = node("t", "trigger", event="lead_created")
END = node("end", "end")


def lead_flow() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """lead created -> assess -> (strong? draft -> approval -> send) -> end"""
    nodes = [
        TRIGGER,
        node("fit", "ai_assess_fit"),
        node("c", "condition", field="fit.rating", op="eq", value="strong"),
        node("d", "ai_draft"),
        node("g", "approval_gate"),
        node("s", "send_email"),
        node("end", "end"),
        node("end2", "end", reason="not a fit"),
        node("end3", "end", reason="rejected"),
    ]
    edges = [
        edge("t", "fit"),
        edge("fit", "c"),
        edge("c", "d", "true"),
        edge("c", "end2", "false"),
        edge("d", "g"),
        edge("g", "s", "approved"),
        edge("g", "end3", "rejected"),
        edge("s", "end"),
    ]
    return nodes, edges


def test_the_starter_flow_is_valid_and_reports_its_trigger() -> None:
    report = check(*lead_flow())
    assert report.valid, report.issues
    assert report.trigger_event == "lead_created"


def test_the_catalogue_covers_the_twelve_node_types_of_the_playbook() -> None:
    assert set(NODE_SPECS) == {
        "trigger",
        "condition",
        "ai_assess_fit",
        "ai_classify_reply",
        "ai_draft",
        "upsert_record",
        "create_task",
        "approval_gate",
        "send_email",
        "delay",
        "notify",
        "end",
    }


def test_a_reply_flow_and_a_follow_up_flow_are_valid() -> None:
    reply = check(
        [
            node("t", "trigger", event="reply_received"),
            node("k", "ai_classify_reply"),
            node("n", "notify", title="Reply: {category}"),
            node("end", "end"),
        ],
        [edge("t", "k"), edge("k", "n"), edge("n", "end")],
    )
    assert reply.valid, reply.issues
    follow = check(
        [
            node("t", "trigger", event="follow_up_due"),
            node("task", "create_task", title="Follow up with {lead_title}", due_in_days=2),
            node("w", "delay", amount=2, unit="days"),
            node("end", "end"),
        ],
        [edge("t", "task"), edge("task", "w"), edge("w", "end")],
    )
    assert follow.valid, follow.issues


# ----------------------------------------------------------------------------- structure


def test_a_workflow_needs_a_trigger_and_an_end() -> None:
    assert "missing_trigger" in codes(check([END], []))
    assert "missing_end" in codes(check([TRIGGER], []))
    assert codes(check([], [])) == ["missing_trigger"]


def test_only_one_trigger_and_nothing_leads_back_into_it() -> None:
    both = check(
        [TRIGGER, node("t2", "trigger", event="manual"), END],
        [edge("t", "end"), edge("t2", "end")],
    )
    assert "multiple_triggers" in codes(both)
    back = check(
        [TRIGGER, node("n", "notify", title="hi"), END],
        [edge("t", "n"), edge("n", "t")],
    )
    assert "trigger_has_incoming" in codes(back)


def test_duplicate_ids_and_dangling_connections_are_reported() -> None:
    dup = check([TRIGGER, TRIGGER, END], [edge("t", "end")])
    assert "duplicate_node_id" in codes(dup)
    dup_edges = check([TRIGGER, END], [edge("t", "end", id_="e1"), edge("t", "end", id_="e1")])
    assert "duplicate_edge_id" in codes(dup_edges)
    dangling = check([TRIGGER, END], [edge("t", "ghost"), edge("ghost", "end")])
    assert "dangling_edge" in codes(dangling)


def test_an_unknown_node_type_is_an_issue_not_a_crash() -> None:
    report = check([TRIGGER, node("x", "teleport"), END], [edge("t", "x"), edge("x", "end")])
    assert "unknown_node_type" in codes(report)


def test_ports_must_exist_and_each_can_be_used_once() -> None:
    wrong_port = check(
        [TRIGGER, node("n", "notify", title="x"), END],
        [edge("t", "n", "yes"), edge("n", "end")],
    )
    assert "unknown_port" in codes(wrong_port)
    out_of_end = check(
        [TRIGGER, END, node("n", "notify", title="x")], [edge("t", "end"), edge("end", "n")]
    )
    assert "unknown_port" in codes(out_of_end)
    two_paths = check(
        [TRIGGER, node("a", "notify", title="a"), node("b", "notify", title="b"), END],
        [edge("t", "a"), edge("t", "b"), edge("a", "end"), edge("b", "end")],
    )
    assert "ambiguous_branch" in codes(two_paths)


def test_every_branch_must_lead_somewhere() -> None:
    nodes, edges = lead_flow()
    no_false = [e for e in edges if e["id"] != "c-end2-false"]
    report = check(nodes, no_false)
    assert "unhandled_branch" in codes(report)
    assert any("false" in i.message for i in report.issues if i.code == "unhandled_branch")
    no_rejected = [e for e in edges if e["branch"] != "rejected"]
    assert "unhandled_branch" in codes(check(nodes, no_rejected))
    dead_end = check([TRIGGER, node("n", "notify", title="x"), END], [edge("t", "n")])
    assert "unhandled_branch" in codes(dead_end)


def test_unreachable_nodes_and_cycles_are_rejected() -> None:
    nodes, edges = lead_flow()
    island = check(nodes + [node("lost", "notify", title="x")], edges + [edge("lost", "end")])
    assert "unreachable_node" in codes(island)
    loop = check(
        [TRIGGER, node("a", "notify", title="a"), node("b", "notify", title="b"), END],
        [edge("t", "a"), edge("a", "b"), edge("b", "a")],
    )
    assert "cycle" in codes(loop)
    self_loop = check(
        [TRIGGER, node("a", "notify", title="a"), END], [edge("t", "a"), edge("a", "a")]
    )
    assert "cycle" in codes(self_loop)


# ----------------------------------------------------------------------------- settings


@pytest.mark.parametrize(
    ("n", "code"),
    [
        (node("n", "create_task"), "missing_config"),
        (node("n", "notify"), "missing_config"),
        (node("n", "delay"), "missing_config"),
        (node("n", "upsert_record"), "missing_config"),
        (node("n", "upsert_record", action="update_lead"), "invalid_config"),
        (node("n", "delay", amount=40, unit="days"), "invalid_config"),
        (node("n", "delay", amount=0, unit="hours"), "invalid_config"),
        (node("n", "delay", amount=1, unit="weeks"), "invalid_config"),
        (node("n", "notify", title="x", surprise=True), "invalid_config"),
        (node("n", "notify", title="x" * 200), "invalid_config"),
        (node("n", "create_task", title="x", due_in_days=-1), "invalid_config"),
        (node("n", "ai_draft", max_attempts=9), "invalid_config"),
        (node("n", "ai_draft", timeout_seconds=1), "invalid_config"),
        (node("n", "notify", title="Hi {secret_message}"), "unknown_placeholder"),
    ],
)
def test_settings_are_checked(n: dict[str, Any], code: str) -> None:
    report = check([TRIGGER, n, END], [edge("t", "n"), edge("n", "end")])
    assert code in codes(report), report.issues


def test_the_trigger_event_and_subject_are_checked() -> None:
    bad_event = check([node("t", "trigger", event="nightly"), END], [edge("t", "end")])
    assert "invalid_config" in codes(bad_event)
    bad_subject = check(
        [node("t", "trigger", event="lead_created", subject="lead"), END], [edge("t", "end")]
    )
    assert "invalid_config" in codes(bad_subject)
    assert check([node("t", "trigger", event="manual"), END], [edge("t", "end")]).valid


@pytest.mark.parametrize(
    "cfg",
    [
        {"field": "fit.rating", "op": "eq", "value": "great"},  # not a rating
        {"field": "fit.rating", "op": "gte", "value": "strong"},  # op not for text
        {"field": "lead.score", "op": "gte", "value": "high"},  # number expected
        {"field": "lead.score", "op": "in", "value": 5},  # list expected
        {"field": "lead.has_contact_email", "op": "is_true", "value": "yes"},  # takes no value
        {"field": "lead.nope", "op": "eq", "value": "x"},
        {"field": "classification.category", "op": "in", "value": []},
        {"field": "lead.score", "op": "eq"},
    ],
)
def test_condition_settings_are_checked(cfg: dict[str, Any]) -> None:
    nodes = [TRIGGER, node("c", "condition", **cfg), node("a", "end"), node("b", "end")]
    report = check(nodes, [edge("t", "c"), edge("c", "a", "true"), edge("c", "b", "false")])
    assert "invalid_config" in codes(report), report.issues


def test_a_good_condition_is_accepted() -> None:
    for cfg in (
        {"field": "lead.score", "op": "gte", "value": 60},
        {"field": "lead.status", "op": "in", "value": ["new", "contacted"]},
        {"field": "contact.suppressed", "op": "is_false"},
    ):
        nodes = [TRIGGER, node("c", "condition", **cfg), node("a", "end"), node("b", "end")]
        report = check(nodes, [edge("t", "c"), edge("c", "a", "true"), edge("c", "b", "false")])
        assert report.valid, report.issues


def test_a_delay_is_capped_at_thirty_days() -> None:
    assert DelayConfig(amount=30, unit="days").seconds == 30 * 86400
    with pytest.raises(ValueError):
        DelayConfig(amount=31, unit="days")


# ----------------------------------------------------------------------------- data flow


def test_a_step_needs_what_the_trigger_and_earlier_steps_provide() -> None:
    wrong_trigger = check(
        [TRIGGER, node("k", "ai_classify_reply"), END], [edge("t", "k"), edge("k", "end")]
    )
    assert "missing_input" in codes(wrong_trigger)
    reply_needs_lead = check(
        [node("t", "trigger", event="reply_received"), node("f", "ai_assess_fit"), END],
        [edge("t", "f"), edge("f", "end")],
    )
    assert "missing_input" in codes(reply_needs_lead)
    template_needs_fact = check(
        [TRIGGER, node("n", "notify", title="Category {category}"), END],
        [edge("t", "n"), edge("n", "end")],
    )
    assert "missing_input" in codes(template_needs_fact)
    cond_needs_fact = check(
        [
            TRIGGER,
            node("c", "condition", field="fit.rating", op="eq", value="strong"),
            END,
            node("e2", "end"),
        ],
        [edge("t", "c"), edge("c", "end", "true"), edge("c", "e2", "false")],
    )
    assert "missing_input" in codes(cond_needs_fact)


def test_a_fact_must_arrive_on_every_path_not_just_one() -> None:
    nodes = [
        TRIGGER,
        node("c", "condition", field="lead.score", op="gte", value=50),
        node("fit", "ai_assess_fit"),
        node("n", "notify", title="Fit {fit_rating}"),
        END,
    ]
    edges = [
        edge("t", "c"),
        edge("c", "fit", "true"),
        edge("c", "n", "false"),  # this path skips the assessment
        edge("fit", "n"),
        edge("n", "end"),
    ]
    assert "missing_input" in codes(check(nodes, edges))


def test_sending_needs_an_approval_gate_on_every_path() -> None:
    # draft -> gate -> send is fine
    ok = check(
        [
            TRIGGER,
            node("d", "ai_draft"),
            node("g", "approval_gate"),
            node("s", "send_email"),
            END,
            node("r", "end"),
        ],
        [
            edge("t", "d"),
            edge("d", "g"),
            edge("g", "s", "approved"),
            edge("g", "r", "rejected"),
            edge("s", "end"),
        ],
    )
    assert ok.valid, ok.issues
    # draft -> send (no gate)
    no_gate = check(
        [TRIGGER, node("d", "ai_draft"), node("s", "send_email"), END],
        [edge("t", "d"), edge("d", "s"), edge("s", "end")],
    )
    assert "send_without_approval" in codes(no_gate)
    # gate first, draft written after approval: the approval was for nothing
    gate_before_draft = check(
        [
            TRIGGER,
            node("g", "approval_gate"),
            node("d", "ai_draft"),
            node("s", "send_email"),
            END,
            node("r", "end"),
        ],
        [
            edge("t", "g"),
            edge("g", "d", "approved"),
            edge("g", "r", "rejected"),
            edge("d", "s"),
            edge("s", "end"),
        ],
    )
    assert "send_without_approval" in codes(gate_before_draft)
    # send on the rejected path
    on_rejected = check(
        [
            TRIGGER,
            node("d", "ai_draft"),
            node("g", "approval_gate"),
            node("s", "send_email"),
            END,
            node("a", "end"),
        ],
        [
            edge("t", "d"),
            edge("d", "g"),
            edge("g", "a", "approved"),
            edge("g", "s", "rejected"),
            edge("s", "end"),
        ],
    )
    assert "send_without_approval" in codes(on_rejected)
    # a second draft after the gate needs its own approval
    redraft = check(
        [
            TRIGGER,
            node("d", "ai_draft"),
            node("g", "approval_gate"),
            node("d2", "ai_draft"),
            node("s", "send_email"),
            END,
            node("r", "end"),
        ],
        [
            edge("t", "d"),
            edge("d", "g"),
            edge("g", "d2", "approved"),
            edge("g", "r", "rejected"),
            edge("d2", "s"),
            edge("s", "end"),
        ],
    )
    assert "send_without_approval" in codes(redraft)
    # one path approved, the other not, merging into the send
    merge = check(
        [
            TRIGGER,
            node("d", "ai_draft"),
            node("c", "condition", field="lead.score", op="gte", value=50),
            node("g", "approval_gate"),
            node("s", "send_email"),
            END,
            node("r", "end"),
        ],
        [
            edge("t", "d"),
            edge("d", "c"),
            edge("c", "g", "true"),
            edge("c", "s", "false"),
            edge("g", "s", "approved"),
            edge("g", "r", "rejected"),
            edge("s", "end"),
        ],
    )
    assert "send_without_approval" in codes(merge)
    # sending with no draft at all
    no_draft = check(
        [TRIGGER, node("g", "approval_gate"), node("s", "send_email"), END, node("r", "end")],
        [edge("t", "g"), edge("g", "s", "approved"), edge("g", "r", "rejected"), edge("s", "end")],
    )
    assert {"send_without_approval", "missing_input"} <= set(codes(no_draft))


def test_validation_does_not_stop_at_the_first_problem_and_messages_name_the_node() -> None:
    nodes = [
        TRIGGER,
        {"id": "x", "type": "create_task", "label": "Chase up", "config": {}},
        node("n", "notify", title="{nope}"),
    ]
    report = check(nodes, [edge("t", "x"), edge("x", "n")])
    assert {"missing_config", "unknown_placeholder", "unhandled_branch", "missing_end"} <= set(
        codes(report)
    )
    assert any("Chase up" in i.message for i in report.issues if i.code == "missing_config")


def test_templates_only_fill_known_placeholders() -> None:
    assert render("Hi {lead_title} {unknown} {category}", {"lead_title": "Acme"}) == "Hi Acme  "
