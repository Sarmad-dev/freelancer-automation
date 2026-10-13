/**
 * Structural validation of a workflow definition, for instant feedback in the editor.
 *
 * This mirrors the structural part of the authoritative Python validator
 * (`apps/api/app/workflows/validate.py`) and reports the same issue codes for the same definition:
 * duplicate_node_id, duplicate_edge_id, dangling_edge, unknown_node_type, unknown_port, ambiguous_branch,
 * unhandled_branch, missing_trigger, multiple_triggers, trigger_has_incoming, unreachable_node, cycle and
 * missing_end. A malformed definition (bad id, unknown key, too many nodes...) gives a `schema` issue.
 *
 * It does NOT check node settings (missing_config, invalid_config, unknown_placeholder), data flow
 * (missing_input) or the rule that an email is only sent after an approval (send_without_approval).
 * Those need the server's node catalogue and are checked by the API when a workflow is saved or run, so
 * a definition that passes here can still be rejected there.
 */
import type { WorkflowDefinition, WorkflowEdge, WorkflowNode } from "./schema";
import { DEFAULT_PORT, NODE_PORTS, workflowDefinitionSchema } from "./schema";

export type ValidationIssueCode =
  | "schema"
  | "duplicate_node_id"
  | "duplicate_edge_id"
  | "dangling_edge"
  | "unknown_node_type"
  | "unknown_port"
  | "ambiguous_branch"
  | "unhandled_branch"
  | "missing_trigger"
  | "multiple_triggers"
  | "trigger_has_incoming"
  | "unreachable_node"
  | "cycle"
  | "missing_end";

export type ValidationIssue = {
  code: ValidationIssueCode;
  message: string;
  nodeId?: string;
  edgeId?: string;
};

export type ValidationResult =
  | { ok: true; definition: WorkflowDefinition; issues: [] }
  | { ok: false; definition?: WorkflowDefinition; issues: ValidationIssue[] };

const name = (node: WorkflowNode): string => node.label || node.id;
const portOf = (edge: WorkflowEdge): string => edge.branch || DEFAULT_PORT;

/** The output ports of a node type, or undefined when the type is not in the catalogue. */
function portsOf(type: string): readonly string[] | undefined {
  return Object.hasOwn(NODE_PORTS, type) ? NODE_PORTS[type as keyof typeof NODE_PORTS] : undefined;
}

/** Whether every node can be ordered so that each comes after the ones leading to it (no loops). */
function isAcyclic(nodes: Set<string>, outgoing: Map<string, string[]>): boolean {
  const indegree = new Map<string, number>([...nodes].map((id) => [id, 0]));
  for (const [source, targets] of outgoing) {
    if (!nodes.has(source)) continue;
    for (const target of targets) {
      if (indegree.has(target)) indegree.set(target, (indegree.get(target) ?? 0) + 1);
    }
  }
  const ready = [...indegree].filter(([, d]) => d === 0).map(([id]) => id);
  let ordered = 0;
  for (let current = ready.pop(); current !== undefined; current = ready.pop()) {
    ordered += 1;
    for (const target of outgoing.get(current) ?? []) {
      const left = indegree.get(target);
      if (left === undefined) continue;
      indegree.set(target, left - 1);
      if (left - 1 === 0) ready.push(target);
    }
  }
  return ordered === nodes.size;
}

export function validateWorkflow(input: unknown): ValidationResult {
  const parsed = workflowDefinitionSchema.safeParse(input);
  if (!parsed.success) {
    return {
      ok: false,
      issues: parsed.error.issues.map((i) => ({
        code: "schema" as const,
        message: `${i.path.join(".") || "definition"}: ${i.message}`,
      })),
    };
  }
  const def = parsed.data;
  const issues: ValidationIssue[] = [];

  // Nodes: unique ids (the first node with an id wins), known types.
  const nodes = new Map<string, WorkflowNode>();
  for (const n of def.nodes) {
    if (nodes.has(n.id)) {
      issues.push({
        code: "duplicate_node_id",
        message: `Two nodes share the id "${n.id}".`,
        nodeId: n.id,
      });
      continue;
    }
    nodes.set(n.id, n);
  }
  for (const n of nodes.values()) {
    if (portsOf(n.type) === undefined) {
      issues.push({
        code: "unknown_node_type",
        message: `"${name(n)}" has an unknown type "${n.type}".`,
        nodeId: n.id,
      });
    }
  }

  // Edges: unique ids, real endpoints, real ports, one edge per port.
  const edgeIds = new Set<string>();
  const used = new Set<string>();
  const goodEdges: WorkflowEdge[] = [];
  for (const e of def.edges) {
    if (edgeIds.has(e.id)) {
      issues.push({
        code: "duplicate_edge_id",
        message: `Two connections share the id "${e.id}".`,
        edgeId: e.id,
      });
      continue;
    }
    edgeIds.add(e.id);
    const source = nodes.get(e.source);
    if (source === undefined || !nodes.has(e.target)) {
      issues.push({
        code: "dangling_edge",
        message: `Connection "${e.id}" points at a node that does not exist.`,
        edgeId: e.id,
      });
      continue;
    }
    const port = portOf(e);
    const ports = portsOf(source.type);
    if (ports !== undefined && !ports.includes(port)) {
      const allowed = ports.length > 0 ? ports.join(", ") : "none (it ends the workflow)";
      issues.push({
        code: "unknown_port",
        message: `"${name(source)}" has no "${port}" output. Its outputs: ${allowed}.`,
        nodeId: source.id,
        edgeId: e.id,
      });
      continue;
    }
    const key = JSON.stringify([e.source, port]);
    if (used.has(key)) {
      issues.push({
        code: "ambiguous_branch",
        message: `"${name(source)}" has two connections from its "${port}" output. A run follows exactly one path.`,
        nodeId: source.id,
        edgeId: e.id,
      });
      continue;
    }
    used.add(key);
    goodEdges.push(e);
  }

  // Trigger: exactly one, and nothing leads back into it.
  const triggers = [...nodes.values()].filter((n) => n.type === "trigger");
  if (triggers.length === 0) {
    issues.push({ code: "missing_trigger", message: "A workflow needs one trigger to start it." });
  }
  for (const t of triggers.slice(1)) {
    issues.push({
      code: "multiple_triggers",
      message: "Only one trigger is supported. Remove the extra one.",
      nodeId: t.id,
    });
  }
  for (const e of goodEdges) {
    if (nodes.get(e.target)?.type === "trigger") {
      issues.push({
        code: "trigger_has_incoming",
        message: "Nothing can lead back into the trigger.",
        nodeId: e.target,
        edgeId: e.id,
      });
    }
  }

  // Every output port of every node is connected.
  for (const n of nodes.values()) {
    for (const port of portsOf(n.type) ?? []) {
      if (!used.has(JSON.stringify([n.id, port]))) {
        const what = port === DEFAULT_PORT ? "the next step" : `the "${port}" path`;
        issues.push({
          code: "unhandled_branch",
          message: `"${name(n)}" does not say what happens on ${what}. Connect it to a step or an end.`,
          nodeId: n.id,
        });
      }
    }
  }

  if (nodes.size > 0 && ![...nodes.values()].some((n) => n.type === "end")) {
    issues.push({ code: "missing_end", message: "A workflow needs at least one End node." });
  }

  // Reachability from the first trigger, over the connections that passed the checks above.
  const outgoing = new Map<string, string[]>();
  for (const e of goodEdges) outgoing.set(e.source, [...(outgoing.get(e.source) ?? []), e.target]);
  const reachable = new Set<string>();
  const start = triggers[0];
  if (start !== undefined) {
    const stack = [start.id];
    for (let current = stack.pop(); current !== undefined; current = stack.pop()) {
      if (reachable.has(current)) continue;
      reachable.add(current);
      stack.push(...(outgoing.get(current) ?? []));
    }
    for (const n of nodes.values()) {
      if (!reachable.has(n.id)) {
        issues.push({
          code: "unreachable_node",
          message: `"${name(n)}" can never run: nothing leads to it from the trigger.`,
          nodeId: n.id,
        });
      }
    }
  }

  // Loops are not supported (only the part reachable from the trigger is checked).
  if (!isAcyclic(reachable, outgoing)) {
    issues.push({
      code: "cycle",
      message: "The workflow loops back on itself. Loops are not supported yet.",
    });
  }

  return issues.length === 0
    ? { ok: true, definition: def, issues: [] }
    : { ok: false, definition: def, issues };
}
