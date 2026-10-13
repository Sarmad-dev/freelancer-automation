import { describe, expect, it } from "vitest";
import fixtures from "../fixtures/structure.json";
import { NODE_PORTS, NODE_TYPES, SIDE_EFFECT_NODE_TYPES } from "./schema";
import { validateWorkflow } from "./validate";

const structural = new Set<string>(fixtures.structural_codes);

const structuralCodes = (input: unknown): string[] =>
  [
    ...new Set(
      validateWorkflow(input)
        .issues.map((i) => i.code as string)
        .filter((c) => structural.has(c)),
    ),
  ].sort();

const allCodes = (input: unknown): string[] => validateWorkflow(input).issues.map((i) => i.code);

const node = (id: string, type: string, extra: object = {}) => ({ id, type, config: {}, ...extra });
const edge = (id: string, source: string, target: string, branch?: string | null) => ({
  id,
  source,
  target,
  ...(branch === undefined ? {} : { branch }),
});
const wf = (nodes: unknown[], edges: unknown[]) => ({ schemaVersion: 1, nodes, edges });

describe("structural issue codes match the Python validator (fixtures/structure.json)", () => {
  it.each(fixtures.cases)("$name", (c) => {
    expect(structuralCodes(c.definition)).toEqual([...c.codes].sort());
  });

  it("covers every structural code in at least one fixture case", () => {
    const covered = new Set(fixtures.cases.flatMap((c) => c.codes));
    expect([...structural].filter((c) => !covered.has(c))).toEqual([]);
  });
});

describe("shape errors give a schema issue", () => {
  const valid = wf([node("t", "trigger"), node("e", "end")], [edge("a", "t", "e")]);

  it("accepts a minimal valid definition", () => {
    const r = validateWorkflow(valid);
    expect(r.ok).toBe(true);
    expect(r.issues).toEqual([]);
  });

  it("rejects a node id with a space", () => {
    expect(allCodes(wf([node("bad id", "trigger")], []))).toEqual(["schema"]);
  });

  it("rejects an edge id with a space", () => {
    expect(allCodes(wf([node("t", "trigger")], [edge("bad id", "t", "t")]))).toEqual(["schema"]);
  });

  it("rejects an unknown key on the definition, a node and an edge", () => {
    expect(allCodes({ ...valid, extra: 1 })).toEqual(["schema"]);
    expect(allCodes(wf([{ ...node("t", "trigger"), colour: "red" }], []))).toEqual(["schema"]);
    expect(
      allCodes(wf([node("t", "trigger")], [{ ...edge("a", "t", "t"), port: "next" }])),
    ).toEqual(["schema"]);
  });

  it("rejects schemaVersion 2", () => {
    expect(allCodes({ ...valid, schemaVersion: 2 })).toEqual(["schema"]);
  });

  it("rejects 51 nodes but accepts 50", () => {
    const many = (n: number) => Array.from({ length: n }, (_, i) => node(`n${i}`, "end"));
    expect(allCodes(wf(many(51), []))).toEqual(["schema"]);
    expect(allCodes(wf(many(50), []))).not.toContain("schema");
  });

  it("rejects a position outside the allowed range", () => {
    expect(allCodes(wf([node("t", "trigger", { position: { x: 100001, y: 0 } })], []))).toEqual([
      "schema",
    ]);
  });

  it("returns no definition for a shape error", () => {
    const r = validateWorkflow({ schemaVersion: 2, nodes: [], edges: [] });
    expect(r.ok).toBe(false);
    expect(r.definition).toBeUndefined();
  });

  it("treats an unknown node type as an issue, not a schema error", () => {
    const r = validateWorkflow(wf([node("x", "teleport")], []));
    expect(r.definition).toBeDefined();
    expect(allCodes(wf([node("x", "teleport")], []))).toContain("unknown_node_type");
    expect(allCodes(wf([node("x", "teleport")], []))).not.toContain("schema");
  });

  it("defaults the position to 0,0 and the config to empty", () => {
    const r = validateWorkflow(wf([{ id: "t", type: "trigger" }], []));
    expect(r.definition?.nodes[0]).toMatchObject({ config: {}, position: { x: 0, y: 0 } });
  });
});

describe("edge ports", () => {
  const base = (branch?: string | null) =>
    wf([node("t", "trigger"), node("e", "end")], [edge("a", "t", "e", branch)]);

  it("accepts branch: null as the default port", () => {
    expect(validateWorkflow(base(null)).ok).toBe(true);
  });

  it("treats an empty branch as the default port", () => {
    expect(validateWorkflow(base("")).ok).toBe(true);
  });

  it("lets an edge name the single default output explicitly as next", () => {
    expect(validateWorkflow(base("next")).ok).toBe(true);
  });

  it("counts an explicit next and an implicit next as the same output", () => {
    const r = validateWorkflow(
      wf(
        [node("t", "trigger"), node("e", "end"), node("f", "end")],
        [edge("a", "t", "e"), edge("b", "t", "f", "next")],
      ),
    );
    expect(r.issues.map((i) => i.code)).toContain("ambiguous_branch");
  });

  it("rejects a port the node does not have, and names the real ones", () => {
    const r = validateWorkflow(base("true"));
    const issue = r.issues.find((i) => i.code === "unknown_port");
    expect(issue).toMatchObject({ nodeId: "t", edgeId: "a" });
    expect(issue?.message).toContain("Its outputs: next.");
  });

  it("requires both ports of a condition and of an approval gate", () => {
    const r = validateWorkflow(
      wf(
        [
          node("t", "trigger"),
          node("c", "condition"),
          node("g", "approval_gate"),
          node("e", "end"),
        ],
        [edge("1", "t", "c"), edge("2", "c", "g", "true"), edge("3", "g", "e", "approved")],
      ),
    );
    const unhandled = r.issues.filter((i) => i.code === "unhandled_branch");
    expect(unhandled.map((i) => i.nodeId).sort()).toEqual(["c", "g"]);
  });

  it("does not report an unknown_port for an edge out of an unknown node type", () => {
    const r = validateWorkflow(
      wf(
        [node("t", "trigger"), node("x", "teleport"), node("e", "end")],
        [edge("1", "t", "x"), edge("2", "x", "e", "whatever")],
      ),
    );
    expect(r.issues.map((i) => i.code)).toEqual(["unknown_node_type"]);
  });
});

describe("issue details", () => {
  it("points at the node and uses its label in the message", () => {
    const r = validateWorkflow(
      wf(
        [node("t", "trigger"), node("c", "condition", { label: "Is it good?" }), node("e", "end")],
        [edge("1", "t", "c"), edge("2", "c", "e", "true")],
      ),
    );
    expect(r.issues).toEqual([
      {
        code: "unhandled_branch",
        message:
          '"Is it good?" does not say what happens on the "false" path. Connect it to a step or an end.',
        nodeId: "c",
      },
    ]);
  });

  it("points at the extra trigger", () => {
    const r = validateWorkflow(wf([node("a", "trigger"), node("b", "trigger")], []));
    expect(r.issues.find((i) => i.code === "multiple_triggers")?.nodeId).toBe("b");
  });

  it("reports a loop only once, even when it has several", () => {
    const r = validateWorkflow(
      wf(
        [node("t", "trigger"), node("a", "notify"), node("b", "notify"), node("e", "end")],
        [edge("1", "t", "a"), edge("2", "a", "b"), edge("3", "b", "a")],
      ),
    );
    expect(r.issues.filter((i) => i.code === "cycle")).toHaveLength(1);
  });

  it("ignores a loop that the trigger cannot reach", () => {
    const r = validateWorkflow(
      wf(
        [node("t", "trigger"), node("e", "end"), node("a", "notify"), node("b", "notify")],
        [edge("1", "t", "e"), edge("2", "a", "b"), edge("3", "b", "a")],
      ),
    );
    expect(r.issues.map((i) => i.code)).not.toContain("cycle");
    expect(r.issues.map((i) => i.code)).toContain("unreachable_node");
  });
});

describe("node catalogue", () => {
  it("has ports for every node type", () => {
    expect(Object.keys(NODE_PORTS).sort()).toEqual([...NODE_TYPES].sort());
  });

  it("marks record changes and email as side effects", () => {
    expect([...SIDE_EFFECT_NODE_TYPES].sort()).toEqual(["send_email", "upsert_record"]);
  });
});
