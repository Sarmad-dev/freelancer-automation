import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { describe, expect, it, vi } from "vitest";
import { FitBreakdown } from "./fit-breakdown";
import type { CriterionResult, FitExplanation } from "./lead-model";

function criterion(over: Partial<CriterionResult> = {}): CriterionResult {
  return {
    key: "industry",
    label: "Industry",
    weight: 20,
    outcome: "match",
    points: 20,
    reason: "Works in SaaS, one of your preferred industries.",
    evidence: [{ field: "industry", value: "SaaS", note: "from the lead" }],
    ...over,
  };
}

function explanation(over: Partial<FitExplanation> = {}): FitExplanation {
  return {
    band: "strong",
    capped: false,
    computed_at: "2026-10-12T14:03:00Z",
    confidence: 0.8,
    config_version: 2,
    criteria: [
      criterion(),
      criterion({
        key: "budget",
        label: "Budget",
        weight: 10,
        outcome: "partial",
        points: 5,
        reason: "Medium budget.",
        evidence: [{ field: "budget_signal", value: "medium" }],
      }),
      criterion({
        key: "geo",
        label: "Location",
        weight: 10,
        outcome: "miss",
        points: 0,
        reason: "Based in a region you don't serve.",
        evidence: [],
      }),
      criterion({
        key: "size",
        label: "Company size",
        weight: 10,
        outcome: "unknown",
        points: 0,
        reason: "The company size isn't recorded.",
        evidence: [],
      }),
    ],
    known_weight: 40,
    method: "rules",
    profile_version: 1,
    score: 75,
    summary: "Good industry match with a medium budget.",
    total_weight: 50,
    version: 1,
    warnings: [],
    ...over,
  };
}

function setup(over: Partial<React.ComponentProps<typeof FitBreakdown>> = {}) {
  const onRescore = vi.fn();
  const utils = render(
    <FitBreakdown
      explanation={explanation()}
      score={75}
      band="strong"
      stale={false}
      canEdit
      onRescore={onRescore}
      {...over}
    />,
  );
  return { onRescore, ...utils };
}

describe("FitBreakdown", () => {
  it("leads with the band in words, the score, and how much data it rests on", () => {
    setup();
    expect(screen.getByTestId("fit-headline")).toHaveTextContent("Strong fit · 75 / 100");
    expect(screen.getByText("Good industry match with a medium budget.")).toBeInTheDocument();
    expect(
      screen.getByText(/Based on 3 of 4 criteria · 80% of your weighting had data/),
    ).toBeInTheDocument();
    expect(screen.getByText(/rounded to the nearest 5/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Change your criteria" })).toHaveAttribute(
      "href",
      "/leads/scoring",
    );
  });

  it.each([
    ["possible", 55, "Possible fit · 55 / 100"],
    ["weak", 25, "Weak fit · 25 / 100"],
  ] as const)("shows the %s band in words", (band, score, text) => {
    setup({ band, score, explanation: explanation({ band, score }) });
    expect(screen.getByTestId("fit-headline")).toHaveTextContent(text);
  });

  it("says there is not enough information instead of showing a number", () => {
    setup({
      band: "insufficient",
      score: null,
      explanation: explanation({ band: "insufficient", score: null, confidence: 0.1 }),
    });
    expect(screen.getByTestId("fit-headline")).toHaveTextContent(
      "Not enough information to score yet",
    );
    expect(screen.queryByText(/\/ 100/)).toBeNull();
  });

  it("shows every outcome as words with an icon, and unknown as no data", () => {
    setup();
    const items = within(screen.getByRole("list", { name: "Scoring criteria" })).getAllByRole(
      "listitem",
    );
    const top = items.filter((li) => li.hasAttribute("data-outcome"));
    expect(top).toHaveLength(4);
    expect(within(top[0]!).getByText("Matches")).toBeInTheDocument();
    expect(within(top[1]!).getByText("Partly")).toBeInTheDocument();
    expect(within(top[2]!).getByText("Doesn't match")).toBeInTheDocument();
    expect(within(top[3]!).getByText("Unknown · no data")).toBeInTheDocument();
    expect(within(top[3]!).getByText(/not counted/)).toBeInTheDocument();
    for (const li of top) expect(li.querySelector("svg")).not.toBeNull();
  });

  it("renders each criterion's reason, weight and evidence", () => {
    setup();
    expect(screen.getByText("Works in SaaS, one of your preferred industries.")).toBeVisible();
    const industry = screen.getAllByText("Industry")[0]!.closest("li")!;
    expect(within(industry).getByText(/Weight 20/)).toBeInTheDocument();
    expect(within(industry).getByText("SaaS")).toBeInTheDocument();
    expect(within(industry).getByText("(from the lead)")).toBeInTheDocument();
  });

  it("explains a cap and lists warnings", () => {
    setup({
      band: "weak",
      score: 30,
      explanation: explanation({
        band: "weak",
        score: 30,
        capped: true,
        warnings: ["This looks like an agency, a client type you don't take."],
      }),
    });
    expect(screen.getByText("The score was limited")).toBeInTheDocument();
    expect(screen.getByText(/client type you don.t take, so the score/)).toBeInTheDocument();
    expect(
      screen.getByText("This looks like an agency, a client type you don't take."),
    ).toBeInTheDocument();
  });

  it("offers Recalculate when the score is stale and asks the parent to rescore", async () => {
    const user = userEvent.setup();
    const { onRescore } = setup({ stale: true });
    expect(
      screen.getByText("This score uses older criteria or an older profile"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Recalculate" }));
    expect(onRescore).toHaveBeenCalledTimes(1);
  });

  it("hides Recalculate from members but still explains staleness", () => {
    setup({ stale: true, canEdit: false });
    expect(
      screen.getByText("This score uses older criteria or an older profile"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Recalculate/ })).toBeNull();
  });

  it("shows busy and failed recalculation", () => {
    setup({ stale: true, rescoring: true, rescoreError: "The service is busy." });
    const button = screen.getByRole("button", { name: "Recalculating…" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(screen.getByText("The service is busy.")).toBeInTheDocument();
  });

  it("shows an empty state with Recalculate when the lead was never scored", async () => {
    const user = userEvent.setup();
    const { onRescore } = setup({ explanation: null, score: null, band: null });
    expect(screen.getByRole("heading", { name: "Not scored yet", level: 3 })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Recalculate" }));
    expect(onRescore).toHaveBeenCalled();
  });

  it("renders hostile text as inert text", () => {
    const evil = '<img src=x onerror="alert(1)">';
    setup({
      explanation: explanation({
        summary: evil,
        warnings: [evil],
        criteria: [
          criterion({
            label: evil,
            reason: evil,
            evidence: [{ field: evil, value: evil, note: evil }],
          }),
        ],
      }),
    });
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getAllByText(evil, { exact: false }).length).toBeGreaterThan(3);
  });

  it("has no detectable accessibility violations", async () => {
    const { container } = setup({
      stale: true,
      explanation: explanation({ capped: true, warnings: ["A warning."] }),
    });
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations).toEqual([]);
  });

  it("has no detectable accessibility violations when never scored", async () => {
    const { container } = setup({ explanation: null, score: null, band: null });
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations).toEqual([]);
  });
});
