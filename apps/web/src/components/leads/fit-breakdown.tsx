"use client";

import { CircleCheck, CircleDot, CircleHelp, CircleX } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { Badge, Button, EmptyState, Notice, type BadgeTone } from "@freelancer-os/ui";
import {
  FIT_BANDS,
  OUTCOME_LABELS,
  formatDateTime,
  type CriterionResult,
  type FitBand,
  type FitExplanation,
} from "./lead-model";

const OUTCOME_VIEW: Record<
  CriterionResult["outcome"],
  { icon: ReactNode; tone: BadgeTone; hint: string }
> = {
  match: { icon: <CircleCheck className="size-3.5" />, tone: "success", hint: "" },
  partial: { icon: <CircleDot className="size-3.5" />, tone: "warning", hint: "" },
  miss: { icon: <CircleX className="size-3.5" />, tone: "danger", hint: "" },
  // "Unknown" means we had no data. It is not a failure, so it gets a calm tone and says so.
  unknown: { icon: <CircleHelp className="size-3.5" />, tone: "neutral", hint: "no data" },
};

function bandWords(band: string | null | undefined): string {
  return band && band in FIT_BANDS ? FIT_BANDS[band as FitBand].label : "Not scored";
}

function humanField(field: string): string {
  const text = field.replace(/_/g, " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : field;
}

function points(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

function Criterion({ criterion }: { criterion: CriterionResult }) {
  const view = OUTCOME_VIEW[criterion.outcome] ?? OUTCOME_VIEW.unknown;
  const unknown = criterion.outcome === "unknown";
  return (
    <li className="rounded-md border border-line p-3" data-outcome={criterion.outcome}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="min-w-0 font-medium break-words text-fg">{criterion.label}</p>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={view.tone} icon={view.icon}>
            {OUTCOME_LABELS[criterion.outcome] ?? criterion.outcome}
            {view.hint ? ` · ${view.hint}` : ""}
          </Badge>
          <span className="text-xs text-muted">
            Weight {points(criterion.weight)}
            {" · "}
            {unknown
              ? "not counted"
              : `${points(criterion.points)} of ${points(criterion.weight)} points`}
          </span>
        </div>
      </div>
      <p className="mt-1.5 text-sm break-words text-muted">{criterion.reason}</p>
      {criterion.evidence.length > 0 ? (
        <ul className="mt-2 flex flex-col gap-1 border-l-2 border-line pl-3 text-[13px]">
          {criterion.evidence.map((e, i) => (
            <li key={`${e.field}-${i}`} className="break-words">
              <span className="font-medium text-fg">{humanField(e.field)}</span>
              <span className="text-muted">: </span>
              <span className="text-fg">{e.value ? e.value : "no value"}</span>
              {e.note ? <span className="text-muted">{` (${e.note})`}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

/**
 * Explains a fit score: the number is never shown alone. It always comes with its band in words, how much of the
 * user's own weighting had data, and every criterion with its evidence.
 */
export function FitBreakdown({
  explanation,
  score,
  band,
  stale,
  canEdit,
  onRescore,
  rescoring = false,
  rescoreError = null,
}: {
  explanation: FitExplanation | null;
  score: number | null;
  band: string | null;
  stale: boolean;
  canEdit: boolean;
  onRescore: () => void;
  rescoring?: boolean;
  rescoreError?: string | null;
}) {
  const recalc = canEdit ? (
    <Button
      variant="secondary"
      size="sm"
      onClick={onRescore}
      disabled={rescoring}
      aria-busy={rescoring}
    >
      {rescoring ? "Recalculating…" : "Recalculate"}
    </Button>
  ) : null;

  const effectiveBand = band ?? explanation?.band ?? null;
  const insufficient = effectiveBand === "insufficient" || (explanation != null && score == null);

  return (
    <section aria-labelledby="fit-h" className="rounded-lg border border-line bg-surface p-5">
      <h2 id="fit-h" className="text-base font-semibold text-fg">
        Fit score
      </h2>

      <div className="mt-3 flex flex-col gap-4">
        {rescoreError ? (
          <Notice tone="danger" title="Couldn't recalculate the score">
            {rescoreError}
          </Notice>
        ) : null}

        {stale && explanation ? (
          <Notice tone="warning" title="This score uses older criteria or an older profile">
            <p>Your scoring criteria or profile changed after this was calculated.</p>
            {recalc ? <div className="mt-2">{recalc}</div> : null}
          </Notice>
        ) : null}

        {!explanation ? (
          <EmptyState
            titleAs="h3"
            title="Not scored yet"
            description="This lead hasn't been scored against your criteria. The score is a rule-based estimate from your own criteria, nothing more."
          >
            {recalc}
            <Link
              href="/leads/scoring"
              className="inline-flex h-8 items-center text-[13px] underline underline-offset-4"
            >
              Change your criteria
            </Link>
          </EmptyState>
        ) : (
          <>
            <div>
              <p className="text-lg font-semibold text-fg" data-testid="fit-headline">
                {insufficient
                  ? "Not enough information to score yet"
                  : `${bandWords(effectiveBand)} · ${score ?? "?"} / 100`}
              </p>
              <p className="mt-1 text-sm break-words text-fg">{explanation.summary}</p>
              <p className="mt-1 text-sm text-muted">
                {`Based on ${explanation.criteria.filter((c) => c.outcome !== "unknown").length} of ${explanation.criteria.length} criteria · ${Math.round(explanation.confidence * 100)}% of your weighting had data`}
                {` (${points(explanation.known_weight)} of ${points(explanation.total_weight)}).`}
              </p>
              <p className="mt-2 text-[13px] text-muted">
                A rule-based estimate from your own criteria, rounded to the nearest 5. It is not a
                prediction. Scored{" "}
                <time dateTime={explanation.computed_at}>
                  {formatDateTime(explanation.computed_at)}
                </time>
                .{" "}
                <Link href="/leads/scoring" className="underline underline-offset-4">
                  Change your criteria
                </Link>
              </p>
            </div>

            {explanation.capped ? (
              <Notice tone="warning" title="The score was limited">
                This lead matches a client type you don&apos;t take, so the score can&apos;t go
                above a weak fit however well the rest matches.
              </Notice>
            ) : null}
            {explanation.warnings.length > 0 ? (
              <Notice tone="warning" title="Worth knowing">
                <ul className="list-disc pl-5">
                  {explanation.warnings.map((w, i) => (
                    <li key={`${i}-${w}`} className="break-words">
                      {w}
                    </li>
                  ))}
                </ul>
              </Notice>
            ) : null}

            <div>
              <h3 className="text-sm font-medium text-fg">How each criterion scored</h3>
              <p className="mt-0.5 text-[13px] text-muted">
                &ldquo;Unknown&rdquo; means we have no data for that criterion yet. It isn&apos;t
                counted for or against the lead.
              </p>
              {explanation.criteria.length === 0 ? (
                <p className="mt-2 text-sm text-muted">No criteria are switched on.</p>
              ) : (
                <ul className="mt-3 flex flex-col gap-2" aria-label="Scoring criteria">
                  {explanation.criteria.map((c) => (
                    <Criterion key={c.key} criterion={c} />
                  ))}
                </ul>
              )}
            </div>
            {!stale && recalc ? <div>{recalc}</div> : null}
          </>
        )}
      </div>
    </section>
  );
}
