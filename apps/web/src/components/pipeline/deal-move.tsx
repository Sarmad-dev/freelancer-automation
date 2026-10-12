"use client";

import { useRouter } from "next/navigation";
import { useCallback, useRef, useState } from "react";
import { Button, ConfirmDialog, Field, Modal, Select, Textarea, useToast } from "@freelancer-os/ui";
import { browserApi, toFailure } from "@/lib/api-client";
import { describeFailure } from "@/lib/mutation-error";
import type { BoardColumn, MoneyTotal, OpportunityOut, PipelineStage } from "./pipeline-model";

/* ------------------------------------------------------------------------------------------------
 * Pure board maths: an optimistic move, applied to a copy of the server's columns.
 * ---------------------------------------------------------------------------------------------- */

export type DealStatus = "open" | "won" | "lost";

export function stageStatus(stage: Pick<PipelineStage, "is_won" | "is_lost">): DealStatus {
  return stage.is_won ? "won" : stage.is_lost ? "lost" : "open";
}

export function isOpenStage(stage: Pick<PipelineStage, "is_won" | "is_lost">): boolean {
  return !stage.is_won && !stage.is_lost;
}

/** Exact decimal arithmetic in millionths, so summed money never picks up floating-point noise. */
const SCALE = 6;

function toUnits(value: string | null | undefined): bigint | null {
  if (value === null || value === undefined) return null;
  const m = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value.trim());
  if (!m) return null;
  const units = BigInt(m[2]! + (m[3] ?? "").slice(0, SCALE).padEnd(SCALE, "0"));
  return m[1] ? -units : units;
}

function fromUnits(units: bigint): string {
  const negative = units < 0n;
  const digits = (negative ? -units : units).toString().padStart(SCALE + 1, "0");
  let fraction = digits.slice(-SCALE).replace(/0+$/, "");
  if (fraction.length < 2) fraction = fraction.padEnd(2, "0");
  return `${negative ? "-" : ""}${digits.slice(0, -SCALE)}.${fraction}`;
}

/** What one deal adds to a column's totals: its value, and (open deals only) value x the user's own estimate. */
function contribution(deal: OpportunityOut): { value: bigint | null; weighted: bigint } {
  const value = toUnits(deal.value_amount);
  if (value === null || deal.status !== "open") return { value, weighted: 0n };
  const given = toUnits(deal.weighted_value);
  if (given !== null) return { value, weighted: given };
  return {
    value,
    weighted: deal.probability === null ? 0n : (value * BigInt(deal.probability)) / 100n,
  };
}

function adjustTotals(
  totals: readonly MoneyTotal[],
  deal: OpportunityOut,
  sign: 1n | -1n,
  open: boolean,
): MoneyTotal[] {
  const { value, weighted } = contribution(deal);
  if (value === null) return [...totals];
  const next = totals.map((t) => ({ ...t }));
  let entry = next.find((t) => t.currency === deal.currency);
  if (!entry) {
    entry = { currency: deal.currency, amount: "0.00", weighted: open ? "0.00" : null };
    next.push(entry);
  }
  entry.amount = fromUnits((toUnits(entry.amount) ?? 0n) + sign * value);
  if (open && entry.weighted !== null) {
    entry.weighted = fromUnits((toUnits(entry.weighted) ?? 0n) + sign * weighted);
  }
  return next.filter((t) => (toUnits(t.amount) ?? 0n) !== 0n);
}

export interface MoveOp {
  key: number;
  dealId: string;
  kind: "move" | "reopen";
  target: PipelineStage;
  lossReason: string | null;
  /** `pending` = request in flight; `settled` = the server accepted it (waiting for the refreshed board). */
  state: "pending" | "settled";
  /** The server's version of the deal once settled. */
  result?: OpportunityOut;
}

/**
 * Move one deal to another column in a copy of `columns`: counts, the newest-first card order and the
 * per-currency totals all follow. A deal that isn't on the board (or a stage that isn't) leaves it as it was.
 */
export function applyMove(
  columns: readonly BoardColumn[],
  dealId: string,
  target: PipelineStage,
  opts: { lossReason?: string | null; result?: OpportunityOut } = {},
): BoardColumn[] {
  const source = columns.find((c) => c.items.some((d) => d.id === dealId));
  const dest = columns.find((c) => c.stage.id === target.id);
  if (!source || !dest) return [...columns];
  const deal = source.items.find((d) => d.id === dealId)!;
  const status = stageStatus(target);
  const open = status === "open";

  let moved: OpportunityOut;
  if (opts.result) {
    moved = opts.result;
  } else {
    const value = toUnits(deal.value_amount);
    moved = {
      ...deal,
      stage: target,
      status,
      loss_reason: status === "lost" ? opts.lossReason || null : null,
      closed_at: open ? null : deal.closed_at,
      weighted_value:
        open && value !== null && deal.probability !== null
          ? fromUnits((value * BigInt(deal.probability)) / 100n)
          : null,
    };
    // Moving between open columns keeps the server's own weighted figure.
    if (deal.status === "open" && open) moved.weighted_value = deal.weighted_value;
  }

  if (source.stage.id === dest.stage.id) {
    return columns.map((c) =>
      c.stage.id === source.stage.id
        ? { ...c, items: c.items.map((d) => (d.id === dealId ? moved : d)) }
        : c,
    );
  }
  const unvalued = deal.value_amount === null ? 1 : 0;
  return columns.map((c) => {
    if (c.stage.id === source.stage.id) {
      return {
        ...c,
        items: c.items.filter((d) => d.id !== dealId),
        count: Math.max(0, c.count - 1),
        unvalued: Math.max(0, c.unvalued - unvalued),
        totals: adjustTotals(c.totals, deal, -1n, isOpenStage(c.stage)),
      };
    }
    if (c.stage.id === dest.stage.id) {
      return {
        ...c,
        items: [moved, ...c.items],
        count: c.count + 1,
        unvalued: c.unvalued + unvalued,
        totals: adjustTotals(c.totals, moved, 1n, isOpenStage(c.stage)),
      };
    }
    return c;
  });
}

/** The server's columns with every in-flight or just-settled move laid on top, in the order they were made. */
export function applyOps(columns: readonly BoardColumn[], ops: readonly MoveOp[]): BoardColumn[] {
  return ops.reduce<BoardColumn[]>(
    (acc, op) =>
      applyMove(acc, op.dealId, op.target, {
        lossReason: op.lossReason,
        ...(op.result ? { result: op.result } : {}),
      }),
    [...columns],
  );
}

/** A deal as the person should see it right now, for views (like the table) that aren't a board. */
export function overlayDeal(deal: OpportunityOut, ops: readonly MoveOp[]): OpportunityOut {
  const op = [...ops].reverse().find((o) => o.dealId === deal.id);
  if (!op) return deal;
  if (op.result) return op.result;
  return { ...deal, stage: op.target, status: stageStatus(op.target) };
}

/* ------------------------------------------------------------------------------------------------
 * Requests
 * ---------------------------------------------------------------------------------------------- */

export type MoveResult =
  | { ok: true; deal: OpportunityOut }
  | {
      ok: false;
      message: string;
      code: string;
      /** The board was out of date: refresh it. */
      stale: boolean;
      /** Nothing to tell the person (the browser is already on its way to sign-in). */
      silent: boolean;
    };

const MOVE_PATH = "/api/v1/workspaces/{workspace_id}/opportunities/{opportunity_id}/move" as const;
const REOPEN_PATH =
  "/api/v1/workspaces/{workspace_id}/opportunities/{opportunity_id}/reopen" as const;

function failureResult(error: unknown, response: Response | undefined): MoveResult {
  const f = toFailure(error, response);
  const handled = describeFailure(error, response, "deal");
  return {
    ok: false,
    code: f.code,
    message: f.fields.loss_reason ?? f.fields.stage_id ?? f.message,
    stale: f.code === "stale_stage" || f.code === "opportunity_closed",
    silent: handled === null,
  };
}

/** Always sends `expected_stage_id`, so a stale board can never overwrite someone else's move. */
export async function requestMove(
  workspaceId: string,
  deal: Pick<OpportunityOut, "id" | "stage">,
  target: Pick<PipelineStage, "id">,
  lossReason?: string | null,
): Promise<MoveResult> {
  try {
    const { data, error, response } = await browserApi().POST(MOVE_PATH, {
      params: { path: { workspace_id: workspaceId, opportunity_id: deal.id } },
      body: {
        stage_id: target.id,
        expected_stage_id: deal.stage.id,
        ...(lossReason?.trim() ? { loss_reason: lossReason.trim() } : {}),
      },
    });
    if (response.ok && data) return { ok: true, deal: data };
    return failureResult(error, response);
  } catch {
    return failureResult(undefined, undefined);
  }
}

export async function requestReopen(
  workspaceId: string,
  deal: Pick<OpportunityOut, "id">,
  target: Pick<PipelineStage, "id">,
): Promise<MoveResult> {
  try {
    const { data, error, response } = await browserApi().POST(REOPEN_PATH, {
      params: { path: { workspace_id: workspaceId, opportunity_id: deal.id } },
      body: { stage_id: target.id },
    });
    if (response.ok && data) return { ok: true, deal: data };
    return failureResult(error, response);
  } catch {
    return failureResult(undefined, undefined);
  }
}

/* ------------------------------------------------------------------------------------------------
 * Hook
 * ---------------------------------------------------------------------------------------------- */

export type DealRef = Pick<OpportunityOut, "id" | "title" | "stage" | "status">;

export interface MoveController {
  ops: MoveOp[];
  /** The last result, in words, for the live region. */
  message: string;
  isBusy: (dealId: string) => boolean;
  /** Move an open deal. Won and lost columns ask first; the same column is a no-op. */
  move: (deal: DealRef, target: PipelineStage) => void;
  /** Reopen a won or lost deal into an open stage. */
  reopen: (deal: DealRef, target: PipelineStage) => void;
  /** The won/lost question currently on screen, if any. */
  confirming: { deal: DealRef; target: PipelineStage } | null;
  confirm: (lossReason: string) => void;
  cancel: () => void;
  /** Forget moves the server has now reported on (call when a fresh board arrives). */
  dropSettled: () => void;
}

/**
 * One way to move a deal, for every view. Each move is "optimistic": it shows up in `ops` at once and is
 * removed again, exactly, if the server says no. Only one request per deal is ever in flight.
 */
export function useMoveDeal({ workspaceId }: { workspaceId: string }): MoveController {
  const router = useRouter();
  const { toast } = useToast();
  const [ops, setOps] = useState<MoveOp[]>([]);
  const [message, setMessage] = useState("");
  const [confirming, setConfirming] = useState<MoveController["confirming"]>(null);
  const inFlight = useRef(new Set<string>());
  const seq = useRef(0);

  const run = useCallback(
    async (
      deal: DealRef,
      target: PipelineStage,
      kind: MoveOp["kind"],
      lossReason: string | null,
    ) => {
      if (inFlight.current.has(deal.id)) return;
      if (kind === "move" && deal.stage.id === target.id) return;
      inFlight.current.add(deal.id);
      const key = ++seq.current;
      setOps((prev) => [
        ...prev,
        { key, dealId: deal.id, kind, target, lossReason, state: "pending" },
      ]);
      const result =
        kind === "move"
          ? await requestMove(workspaceId, deal, target, lossReason)
          : await requestReopen(workspaceId, deal, target);
      inFlight.current.delete(deal.id);
      if (result.ok) {
        setOps((prev) =>
          prev.map((o) => (o.key === key ? { ...o, state: "settled", result: result.deal } : o)),
        );
        setMessage(
          kind === "move"
            ? `Moved ${deal.title} to ${target.name}`
            : `Reopened ${deal.title} in ${target.name}`,
        );
        router.refresh();
        return;
      }
      setOps((prev) => prev.filter((o) => o.key !== key));
      if (!result.silent) {
        const text = result.stale
          ? `${result.message} The board has been refreshed.`
          : result.message;
        setMessage(`Couldn't move ${deal.title}: ${text}`);
        toast({ title: `Couldn't move ${deal.title}`, description: text, tone: "danger" });
      }
      if (result.stale) router.refresh();
    },
    [router, toast, workspaceId],
  );

  const move = useCallback(
    (deal: DealRef, target: PipelineStage) => {
      if (deal.stage.id === target.id || inFlight.current.has(deal.id)) return;
      if (stageStatus(target) !== "open") {
        setConfirming({ deal, target });
        return;
      }
      void run(deal, target, "move", null);
    },
    [run],
  );

  const reopen = useCallback(
    (deal: DealRef, target: PipelineStage) => void run(deal, target, "reopen", null),
    [run],
  );

  const confirm = useCallback(
    (lossReason: string) => {
      if (!confirming) return;
      const { deal, target } = confirming;
      setConfirming(null);
      void run(deal, target, "move", stageStatus(target) === "lost" ? lossReason : null);
    },
    [confirming, run],
  );

  const cancel = useCallback(() => setConfirming(null), []);

  const dropSettled = useCallback(
    () =>
      setOps((prev) =>
        prev.some((o) => o.state === "settled") ? prev.filter((o) => o.state === "pending") : prev,
      ),
    [],
  );

  const isBusy = useCallback(
    (dealId: string) => ops.some((o) => o.dealId === dealId && o.state === "pending"),
    [ops],
  );

  return { ops, message, isBusy, move, reopen, confirming, confirm, cancel, dropSettled };
}

/* ------------------------------------------------------------------------------------------------
 * UI pieces
 * ---------------------------------------------------------------------------------------------- */

/** Announces each result ("Moved Big project to Proposal") to screen readers, and shows it to everyone. */
export function LiveStatus({ message }: { message: string }) {
  return (
    <p role="status" aria-live="polite" className="min-h-5 text-sm text-muted">
      {message}
    </p>
  );
}

/**
 * The keyboard and screen-reader way to move a deal: a native select that always reads "Move to…" and
 * moves the deal as soon as a stage is chosen. In `reopen` mode (won/lost deals) it lists open stages only.
 */
export function MoveStageSelect({
  deal,
  stages,
  mode = "move",
  disabled = false,
  onChoose,
  className,
}: {
  deal: Pick<OpportunityOut, "title" | "stage">;
  stages: readonly PipelineStage[];
  mode?: "move" | "reopen";
  disabled?: boolean;
  onChoose: (stage: PipelineStage) => void;
  className?: string;
}) {
  const reopen = mode === "reopen";
  const options = reopen ? stages.filter(isOpenStage) : stages;
  return (
    <Select
      aria-label={reopen ? `Reopen ${deal.title}…` : `Move ${deal.title} to…`}
      className={`h-8 text-[13px] ${className ?? ""}`.trim()}
      value=""
      disabled={disabled}
      onChange={(e) => {
        const stage = stages.find((s) => s.id === e.target.value);
        if (stage) onChoose(stage);
      }}
    >
      <option value="">{reopen ? "Reopen…" : "Move to…"}</option>
      {options.map((s) => {
        const current = !reopen && s.id === deal.stage.id;
        return (
          <option key={s.id} value={s.id} disabled={current}>
            {current ? `${s.name} (current)` : s.name}
          </option>
        );
      })}
    </Select>
  );
}

/** The "Mark as won?" question and the "Why was it lost?" form. Cancelling changes nothing. */
export function MoveDialogs({ controller }: { controller: MoveController }) {
  const { confirming, confirm, cancel } = controller;
  if (!confirming) return null;
  const { deal, target } = confirming;
  if (target.is_lost) {
    return (
      <LostDialog
        key={deal.id}
        title={deal.title}
        stage={target.name}
        onConfirm={confirm}
        onCancel={cancel}
      />
    );
  }
  return (
    <ConfirmDialog
      open
      onOpenChange={(open) => {
        if (!open) cancel();
      }}
      title="Mark as won?"
      description={`${deal.title} will move to ${target.name} and be marked as won. You can reopen it later.`}
      confirmLabel="Mark as won"
      onConfirm={() => confirm("")}
    />
  );
}

export const LOSS_REASON_MAX = 300;

function LostDialog({
  title,
  stage,
  onConfirm,
  onCancel,
}: {
  title: string;
  stage: string;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState("");
  return (
    <Modal
      open
      onOpenChange={(open) => {
        if (!open) onCancel();
      }}
      title="Mark as lost?"
      description={`${title} will move to ${stage} and be marked as lost. You can reopen it later.`}
      footer={
        <>
          <Button variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant="danger" type="submit" form="deal-lost-form">
            Mark as lost
          </Button>
        </>
      }
    >
      <form
        id="deal-lost-form"
        aria-label="Mark as lost"
        onSubmit={(e) => {
          e.preventDefault();
          onConfirm(reason);
        }}
      >
        <Field label="Why was it lost?" hint={`Optional. Up to ${LOSS_REASON_MAX} characters.`}>
          {(p) => (
            <Textarea
              {...p}
              rows={3}
              maxLength={LOSS_REASON_MAX}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          )}
        </Field>
      </form>
    </Modal>
  );
}
