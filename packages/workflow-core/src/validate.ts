import type { WorkflowDefinition } from "./schema";
import { SIDE_EFFECT_NODE_TYPES, workflowDefinitionSchema } from "./schema";

export type ValidationIssue = {
  code:
    | "schema"
    | "duplicate_node_id"
    | "duplicate_edge_id"
    | "missing_trigger"
    | "multiple_triggers"
    | "dangling_edge"
    | "unreachable_node"
    | "cycle"
    | "send_without_approval"
    | "condition_branches";
  message: string;
  nodeId?: string;
  edgeId?: string;
};

export type ValidationResult =
  | { ok: true; definition: WorkflowDefinition; issues: [] }
  | { ok: false; definition?: WorkflowDefinition; issues: ValidationIssue[] };

/** Structural validation only; per-node config validation arrives with the engine phase. */
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

  const ids = new Set<string>();
  for (const n of def.nodes) {
    if (ids.has(n.id)) {
      issues.push({
        code: "duplicate_node_id",
        message: `Duplicate node id "${n.id}"`,
        nodeId: n.id,
      });
    }
    ids.add(n.id);
  }
  const edgeIds = new Set<string>();
  for (const e of def.edges) {
    if (edgeIds.has(e.id)) {
      issues.push({
        code: "duplicate_edge_id",
        message: `Duplicate edge id "${e.id}"`,
        edgeId: e.id,
      });
    }
    edgeIds.add(e.id);
    if (!ids.has(e.source) || !ids.has(e.target)) {
      issues.push({
        code: "dangling_edge",
        message: `Edge "${e.id}" references a missing node`,
        edgeId: e.id,
      });
    }
  }

  const triggers = def.nodes.filter((n) => n.type === "trigger");
  if (triggers.length === 0) {
    issues.push({ code: "missing_trigger", message: "A workflow needs exactly one trigger node" });
  } else if (triggers.length > 1) {
    issues.push({ code: "multiple_triggers", message: "Only one trigger node is supported" });
  }

  const outgoing = new Map<string, string[]>();
  for (const e of def.edges) {
    if (!ids.has(e.source) || !ids.has(e.target)) continue;
    outgoing.set(e.source, [...(outgoing.get(e.source) ?? []), e.target]);
  }

  // Reachability from the trigger.
  const reachable = new Set<string>();
  const start = triggers[0];
  if (start) {
    const stack = [start.id];
    while (stack.length > 0) {
      const id = stack.pop() as string;
      if (reachable.has(id)) continue;
      reachable.add(id);
      stack.push(...(outgoing.get(id) ?? []));
    }
    for (const n of def.nodes) {
      if (!reachable.has(n.id)) {
        issues.push({
          code: "unreachable_node",
          message: `Node "${n.label ?? n.id}" is not reachable from the trigger`,
          nodeId: n.id,
        });
      }
    }
  }

  // Cycles are not supported in the MVP (loops arrive later with hard iteration limits).
  const state = new Map<string, 1 | 2>();
  const visit = (id: string): boolean => {
    state.set(id, 1);
    for (const next of outgoing.get(id) ?? []) {
      const s = state.get(next);
      if (s === 1) return true;
      if (s === undefined && visit(next)) return true;
    }
    state.set(id, 2);
    return false;
  };
  for (const n of def.nodes) {
    if (!state.has(n.id) && visit(n.id)) {
      issues.push({
        code: "cycle",
        message: "Workflow contains a cycle, which is not supported yet",
      });
      break;
    }
  }

  // Conditions must expose explicit true and false paths.
  for (const n of def.nodes.filter((x) => x.type === "condition")) {
    const branches = new Set(def.edges.filter((e) => e.source === n.id).map((e) => e.branch));
    if (!branches.has("true") || !branches.has("false")) {
      issues.push({
        code: "condition_branches",
        message: `Condition "${n.label ?? n.id}" needs both a "true" and a "false" branch`,
        nodeId: n.id,
      });
    }
  }

  // Safety: side-effecting nodes must be preceded by an approval gate on every path from the trigger.
  const byId = new Map(def.nodes.map((n) => [n.id, n]));
  if (start) {
    const approved = (id: string, seenApproval: boolean, path: Set<string>): void => {
      const node = byId.get(id);
      if (!node || path.has(id)) return;
      const gate = seenApproval || node.type === "approval_gate";
      if (SIDE_EFFECT_NODE_TYPES.has(node.type) && !seenApproval) {
        issues.push({
          code: "send_without_approval",
          message: `"${node.label ?? node.id}" can run without a preceding approval gate`,
          nodeId: node.id,
        });
        return;
      }
      const next = new Set(path).add(id);
      for (const n of outgoing.get(id) ?? []) approved(n, gate, next);
    };
    approved(start.id, false, new Set());
  }

  return issues.length === 0
    ? { ok: true, definition: def, issues: [] }
    : { ok: false, definition: def, issues };
}
