"""Validate a workflow definition. Pure: no database, no clock, no network.

Issue codes (stable: the editor and tests rely on them):

``unknown_node_type`` · ``missing_config`` · ``invalid_config`` · ``duplicate_node_id`` · ``duplicate_edge_id`` ·
``dangling_edge`` · ``unknown_port`` · ``ambiguous_branch`` · ``unhandled_branch`` · ``missing_trigger`` ·
``multiple_triggers`` · ``trigger_has_incoming`` · ``unreachable_node`` · ``cycle`` · ``missing_end`` ·
``missing_input`` · ``send_without_approval`` · ``unknown_placeholder``

Rules in short: exactly one trigger and no way back into it; every output port of every node has exactly one edge (a
condition needs *true* and *false*, an approval gate needs *approved* and *rejected*); every node is reachable; no
cycles (loops are not supported); at least one end; every node's required facts are produced on **every** path to it;
and an email can only be sent on the *approved* path of an approval gate that came after the draft was written.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from app.workflows.catalog import (
    FACT_APPROVED_DRAFT,
    FACT_DRAFT,
    FACT_LABELS,
    NODE_SPECS,
    PLACEHOLDERS,
    TRIGGER_EVENTS,
    TriggerConfig,
    placeholders_in,
)
from app.workflows.definition import NodeDef, WorkflowDefinition


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    node_id: str | None = None
    edge_id: str | None = None
    field: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "node_id": self.node_id,
            "edge_id": self.edge_id,
            "field": self.field,
        }


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)
    trigger_event: str | None = None

    @property
    def valid(self) -> bool:
        return not self.issues


def _name(node: NodeDef) -> str:
    return node.label or node.id


def _config_issues(node: NodeDef, model: type[BaseModel]) -> tuple[BaseModel | None, list[Issue]]:
    try:
        return model.model_validate(node.config), []
    except ValidationError as exc:
        issues: list[Issue] = []
        for err in exc.errors():
            where = ".".join(str(p) for p in err["loc"]) or None
            kind = err["type"]
            msg = str(err["msg"]).removeprefix("Value error, ")
            if kind == "missing":
                issues.append(
                    Issue(
                        "missing_config",
                        f'"{_name(node)}" needs the setting "{where}".',
                        node_id=node.id,
                        field=where,
                    )
                )
            elif kind == "extra_forbidden":
                issues.append(
                    Issue(
                        "invalid_config",
                        f'"{_name(node)}" has an unknown setting "{where}".',
                        node_id=node.id,
                        field=where,
                    )
                )
            else:
                prefix = f"{where}: " if where else ""
                issues.append(
                    Issue(
                        "invalid_config",
                        f'"{_name(node)}": {prefix}{msg}',
                        node_id=node.id,
                        field=where,
                    )
                )
        return None, issues


def validate_definition(definition: WorkflowDefinition) -> Report:
    report = Report()
    issues = report.issues

    # --- nodes: unique ids, known types, valid settings
    nodes: dict[str, NodeDef] = {}
    for n in definition.nodes:
        if n.id in nodes:
            issues.append(
                Issue("duplicate_node_id", f'Two nodes share the id "{n.id}".', node_id=n.id)
            )
            continue
        nodes[n.id] = n
    configs: dict[str, BaseModel] = {}
    for n in nodes.values():
        spec = NODE_SPECS.get(n.type)
        if spec is None:
            issues.append(
                Issue(
                    "unknown_node_type",
                    f'"{_name(n)}" has an unknown type "{n.type}".',
                    node_id=n.id,
                )
            )
            continue
        cfg, problems = _config_issues(n, spec.model)
        issues.extend(problems)
        if cfg is not None:
            configs[n.id] = cfg
            for name in placeholders_in(_template_text(n, cfg)):
                if name not in PLACEHOLDERS:
                    issues.append(
                        Issue(
                            "unknown_placeholder",
                            f'"{_name(n)}" uses {{{name}}}, which is not available. Use: '
                            + ", ".join("{" + p + "}" for p in PLACEHOLDERS)
                            + ".",
                            node_id=n.id,
                        )
                    )

    # --- edges: unique ids, real endpoints, real ports, one edge per port
    edge_ids: set[str] = set()
    used: dict[tuple[str, str], str] = {}
    good_edges = []
    for e in definition.edges:
        if e.id in edge_ids:
            issues.append(
                Issue("duplicate_edge_id", f'Two connections share the id "{e.id}".', edge_id=e.id)
            )
            continue
        edge_ids.add(e.id)
        if e.source not in nodes or e.target not in nodes:
            issues.append(
                Issue(
                    "dangling_edge",
                    f'Connection "{e.id}" points at a node that does not exist.',
                    edge_id=e.id,
                )
            )
            continue
        source = nodes[e.source]
        spec = NODE_SPECS.get(source.type)
        if spec is not None and e.port not in spec.ports:
            allowed = ", ".join(spec.ports) if spec.ports else "none (it ends the workflow)"
            issues.append(
                Issue(
                    "unknown_port",
                    f'"{_name(source)}" has no "{e.port}" output. Its outputs: {allowed}.',
                    node_id=source.id,
                    edge_id=e.id,
                )
            )
            continue
        key = (e.source, e.port)
        if key in used:
            issues.append(
                Issue(
                    "ambiguous_branch",
                    f'"{_name(source)}" has two connections from its "{e.port}" output. '
                    "A run follows exactly one path.",
                    node_id=source.id,
                    edge_id=e.id,
                )
            )
            continue
        used[key] = e.target
        good_edges.append(e)

    # --- trigger
    triggers = [n for n in nodes.values() if n.type == "trigger"]
    if not triggers:
        issues.append(Issue("missing_trigger", "A workflow needs one trigger to start it."))
    elif len(triggers) > 1:
        for t in triggers[1:]:
            issues.append(
                Issue(
                    "multiple_triggers",
                    "Only one trigger is supported. Remove the extra one.",
                    node_id=t.id,
                )
            )
    for e in good_edges:
        if nodes[e.target].type == "trigger":
            issues.append(
                Issue(
                    "trigger_has_incoming",
                    "Nothing can lead back into the trigger.",
                    node_id=e.target,
                    edge_id=e.id,
                )
            )

    # --- every port of every node is connected (unhandled branches)
    for n in nodes.values():
        spec = NODE_SPECS.get(n.type)
        if spec is None:
            continue
        for port in spec.ports:
            if (n.id, port) not in used:
                what = "the next step" if port == "next" else f'the "{port}" path'
                issues.append(
                    Issue(
                        "unhandled_branch",
                        f'"{_name(n)}" does not say what happens on {what}. Connect it to a step or an end.',
                        node_id=n.id,
                    )
                )

    if nodes and not any(n.type == "end" for n in nodes.values()):
        issues.append(Issue("missing_end", "A workflow needs at least one End node."))

    start = triggers[0] if triggers else None
    if start is not None and isinstance(configs.get(start.id), TriggerConfig):
        cfg = configs[start.id]
        assert isinstance(cfg, TriggerConfig)
        if cfg.event in TRIGGER_EVENTS:
            report.trigger_event = cfg.event

    # --- reachability and cycles (from the trigger)
    outgoing: dict[str, list[tuple[str, str]]] = {}
    for e in good_edges:
        outgoing.setdefault(e.source, []).append((e.port, e.target))
    reachable: set[str] = set()
    if start is not None:
        stack = [start.id]
        while stack:
            current = stack.pop()
            if current in reachable:
                continue
            reachable.add(current)
            stack.extend(t for _, t in outgoing.get(current, []))
        for n in nodes.values():
            if n.id not in reachable:
                issues.append(
                    Issue(
                        "unreachable_node",
                        f'"{_name(n)}" can never run: nothing leads to it from the trigger.',
                        node_id=n.id,
                    )
                )

    order = _topological(reachable, outgoing)
    if order is None:
        issues.append(
            Issue("cycle", "The workflow loops back on itself. Loops are not supported yet.")
        )
        return report  # data-flow analysis needs an acyclic graph

    # --- data flow: what each node can rely on, on every path to it
    facts_in: dict[str, frozenset[str]] = {}
    incoming: dict[str, list[frozenset[str]]] = {}
    for node_id in order:
        node = nodes[node_id]
        spec = NODE_SPECS.get(node.type)
        cfg = configs.get(node_id)
        arrivals = incoming.get(node_id, [])
        have = frozenset() if node_id == (start.id if start else None) else _meet(arrivals)
        facts_in[node_id] = have
        if spec is None or cfg is None:
            out = have  # a broken node: stop reporting follow-on problems from it
            for _, target in outgoing.get(node_id, []):
                incoming.setdefault(target, []).append(out)
            continue
        needed = spec.needs(cfg)
        missing = sorted(needed - have)
        if missing:
            _missing_input(report, node, missing, have)
        gained = spec.gives(cfg)
        after = have | gained
        if node.type == "ai_draft":
            after = after - {FACT_APPROVED_DRAFT}  # a new draft needs a new approval
        for port, target in outgoing.get(node_id, []):
            out_facts = after
            if node.type == "approval_gate":
                out_facts = (
                    after | {FACT_APPROVED_DRAFT}
                    if port == "approved" and FACT_DRAFT in have
                    else after
                )
            incoming.setdefault(target, []).append(out_facts)
    return report


def _template_text(node: NodeDef, cfg: BaseModel) -> str:
    parts: list[str] = []
    for name in ("title", "message", "description"):
        value = getattr(cfg, name, None)
        if isinstance(value, str) and node.type in ("create_task", "notify"):
            parts.append(value)
    return " ".join(parts)


def _meet(arrivals: list[frozenset[str]]) -> frozenset[str]:
    if not arrivals:
        return frozenset()
    out = arrivals[0]
    for a in arrivals[1:]:
        out = out & a
    return out


def _missing_input(report: Report, node: NodeDef, missing: list[str], have: frozenset[str]) -> None:
    if node.type == "send_email" and FACT_APPROVED_DRAFT in missing:
        report.issues.append(
            Issue(
                "send_without_approval",
                f'"{_name(node)}" can run without a person approving the draft first. Put it after an '
                'approval gate\'s "approved" path, and write the draft before that gate.',
                node_id=node.id,
            )
        )
        missing = [m for m in missing if m != FACT_APPROVED_DRAFT]
        if FACT_DRAFT not in missing:
            return
    if not missing:
        return
    wants = ", ".join(FACT_LABELS.get(m, m) for m in missing)
    report.issues.append(
        Issue(
            "missing_input",
            f'"{_name(node)}" needs {wants}, but not every path to it provides that. '
            "Add the step that produces it earlier, or change the trigger.",
            node_id=node.id,
        )
    )


def _topological(nodes: set[str], outgoing: dict[str, list[tuple[str, str]]]) -> list[str] | None:
    indegree = {n: 0 for n in nodes}
    for source, targets in outgoing.items():
        if source not in nodes:
            continue
        for _, target in targets:
            if target in indegree:
                indegree[target] += 1
    ready = sorted(n for n, d in indegree.items() if d == 0)
    order: list[str] = []
    while ready:
        current = ready.pop(0)
        order.append(current)
        for _, target in outgoing.get(current, []):
            if target not in indegree:
                continue
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    return order if len(order) == len(nodes) else None
