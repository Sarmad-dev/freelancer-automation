import axe from "axe-core";

/** Run axe on a DOM subtree and return human-readable violations (jsdom: no colour-contrast). */
export async function axeViolations(container: Element): Promise<string[]> {
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false }, region: { enabled: false } },
  });
  return results.violations.map(
    (v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
  );
}
