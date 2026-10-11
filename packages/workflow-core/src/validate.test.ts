import { describe, expect, it } from "vitest";
import { validateWorkflow } from "./validate";

const node = (id: string, type: string) => ({ id, type, config: {}, position: { x: 0, y: 0 } });
const edge = (id: string, source: string, target: string, branch?: string) => ({
  id,
  source,
  target,
  ...(branch ? { branch } : {}),
});
const wf = (nodes: unknown[], edges: unknown[]) => ({ schemaVersion: 1, nodes, edges });
const codes = (r: ReturnType<typeof validateWorkflow>) => r.issues.map((i) => i.code);

describe("validateWorkflow", () => {
  it("accepts a linear workflow with approval before send", () => {
    const r = validateWorkflow(
      wf(
        [
          node("t", "trigger"),
          node("d", "ai_draft"),
          node("a", "approval_gate"),
          node("s", "send_email"),
          node("e", "end"),
        ],
        [edge("1", "t", "d"), edge("2", "d", "a"), edge("3", "a", "s"), edge("4", "s", "e")],
      ),
    );
    expect(r.ok).toBe(true);
  });

  it("rejects malformed input with schema issues", () => {
    const r = validateWorkflow({ schemaVersion: 2, nodes: [], edges: [] });
    expect(r.ok).toBe(false);
    expect(codes(r)).toContain("schema");
  });

  it("requires exactly one trigger", () => {
    expect(codes(validateWorkflow(wf([node("e", "end")], [])))).toContain("missing_trigger");
    expect(codes(validateWorkflow(wf([node("a", "trigger"), node("b", "trigger")], [])))).toContain(
      "multiple_triggers",
    );
  });

  it("flags dangling edges and unreachable nodes", () => {
    const r = validateWorkflow(
      wf([node("t", "trigger"), node("x", "end")], [edge("1", "t", "ghost")]),
    );
    expect(codes(r)).toEqual(expect.arrayContaining(["dangling_edge", "unreachable_node"]));
  });

  it("flags cycles", () => {
    const r = validateWorkflow(
      wf(
        [node("t", "trigger"), node("a", "create_task"), node("b", "notify")],
        [edge("1", "t", "a"), edge("2", "a", "b"), edge("3", "b", "a")],
      ),
    );
    expect(codes(r)).toContain("cycle");
  });

  it("requires both branches on conditions", () => {
    const r = validateWorkflow(
      wf(
        [node("t", "trigger"), node("c", "condition"), node("e", "end")],
        [edge("1", "t", "c"), edge("2", "c", "e", "true")],
      ),
    );
    expect(codes(r)).toContain("condition_branches");
  });

  it("blocks send_email that can bypass approval on any path", () => {
    const r = validateWorkflow(
      wf(
        [
          node("t", "trigger"),
          node("c", "condition"),
          node("a", "approval_gate"),
          node("s", "send_email"),
          node("n", "notify"),
        ],
        [
          edge("1", "t", "c"),
          edge("2", "c", "a", "true"),
          edge("3", "c", "s", "false"),
          edge("4", "a", "s"),
          edge("5", "s", "n"),
        ],
      ),
    );
    expect(codes(r)).toContain("send_without_approval");
  });

  it("detects duplicate ids", () => {
    const r = validateWorkflow(wf([node("t", "trigger"), node("t", "end")], []));
    expect(codes(r)).toContain("duplicate_node_id");
  });
});
