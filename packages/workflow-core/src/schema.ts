import { z } from "zod";

/**
 * Initial workflow definition schema (MVP Prompt 11 extends the node catalogue
 * and adds per-node config schemas and typed ports).
 *
 * Execution is a backend concern; this package only describes and validates
 * the definition so the API and the editor agree on one contract.
 */
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

/** Node types that cause external side effects and therefore need an approval path. */
export const SIDE_EFFECT_NODE_TYPES: ReadonlySet<NodeType> = new Set<NodeType>(["send_email"]);

export const workflowNodeSchema = z.object({
  id: z.string().min(1),
  type: nodeTypeSchema,
  label: z.string().max(120).optional(),
  config: z.record(z.string(), z.unknown()).default({}),
  position: z.object({ x: z.number(), y: z.number() }).default({ x: 0, y: 0 }),
});
export type WorkflowNode = z.infer<typeof workflowNodeSchema>;

export const workflowEdgeSchema = z.object({
  id: z.string().min(1),
  source: z.string().min(1),
  target: z.string().min(1),
  /** Branch label such as "true" / "false" for condition nodes. */
  branch: z.string().max(60).optional(),
});
export type WorkflowEdge = z.infer<typeof workflowEdgeSchema>;

export const workflowDefinitionSchema = z.object({
  schemaVersion: z.literal(1),
  nodes: z.array(workflowNodeSchema),
  edges: z.array(workflowEdgeSchema),
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
