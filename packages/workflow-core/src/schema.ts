import { z } from "zod";

/**
 * The workflow definition as the API saves, returns and exchanges it. This mirrors
 * `apps/api/app/workflows/definition.py` (shape) and `catalog.py` (node ports); the Python side is
 * authoritative, this copy exists so the editor can give instant feedback.
 *
 * Shape errors (a bad id, an unknown key, too many nodes) are rejected by this schema. Whether the
 * graph makes sense (unknown node types, missing ports, unreachable nodes...) is reported as issues by
 * `validateWorkflow`, so work in progress can still be saved.
 */
export const MAX_NODES = 50;
export const MAX_EDGES = 100;
export const SCHEMA_VERSION = 1;

export const NODE_TYPES = [
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
] as const;

export const nodeTypeSchema = z.enum(NODE_TYPES);
export type NodeType = z.infer<typeof nodeTypeSchema>;

/** The output ports of each node type. A single default output is called "next". */
export const NODE_PORTS: Record<NodeType, readonly string[]> = {
  trigger: ["next"],
  condition: ["true", "false"],
  ai_assess_fit: ["next"],
  ai_classify_reply: ["next"],
  ai_draft: ["next"],
  upsert_record: ["next"],
  create_task: ["next"],
  approval_gate: ["approved", "rejected"],
  send_email: ["next"],
  delay: ["next"],
  notify: ["next"],
  end: [],
};

/** Node types that change records or leave the system. */
export const SIDE_EFFECT_NODE_TYPES: ReadonlySet<NodeType> = new Set<NodeType>([
  "upsert_record",
  "send_email",
]);

/** The port an edge leaves from when it names none. */
export const DEFAULT_PORT = "next";

const keySchema = z.string().regex(/^[A-Za-z0-9_.-]{1,80}$/);
const coordinate = z.number().min(-100_000).max(100_000).default(0);

export const workflowNodeSchema = z.strictObject({
  id: keySchema,
  /** Any non-empty string: an unknown type is a validation issue, not a schema error. */
  type: z.string().min(1).max(40),
  label: z.string().max(120).nullish(),
  config: z.record(z.string(), z.unknown()).default({}),
  position: z.strictObject({ x: coordinate, y: coordinate }).default({ x: 0, y: 0 }),
});
export type WorkflowNode = z.infer<typeof workflowNodeSchema>;

export const workflowEdgeSchema = z.strictObject({
  id: keySchema,
  source: keySchema,
  target: keySchema,
  /** The source's output port, such as "true" / "approved". Empty or null means the default port ("next"). */
  branch: z.string().max(60).nullish(),
});
export type WorkflowEdge = z.infer<typeof workflowEdgeSchema>;

export const workflowDefinitionSchema = z.strictObject({
  schemaVersion: z.literal(SCHEMA_VERSION).default(SCHEMA_VERSION),
  nodes: z.array(workflowNodeSchema).max(MAX_NODES).default([]),
  edges: z.array(workflowEdgeSchema).max(MAX_EDGES).default([]),
});
export type WorkflowDefinition = z.infer<typeof workflowDefinitionSchema>;

export const WORKFLOW_RUN_STATUSES = [
  "queued",
  "running",
  "waiting_approval",
  "waiting_delay",
  "succeeded",
  "failed",
  "cancelled",
] as const;
export type WorkflowRunStatus = (typeof WORKFLOW_RUN_STATUSES)[number];
