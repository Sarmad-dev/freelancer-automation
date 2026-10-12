"use client";

import Link from "next/link";
import { useMemo, useState, type DragEvent } from "react";
import { Badge, EmptyState, Notice } from "@freelancer-os/ui";
import { SampleBadge } from "../leads/lead-badges";
import {
  LiveStatus,
  MoveDialogs,
  MoveStageSelect,
  applyOps,
  useMoveDeal,
  type MoveController,
} from "./deal-move";
import { NewDealButton } from "./opportunity-create-drawer";
import { dealHref, tableHref } from "./pipeline-list-model";
import {
  DEAL_STATUS_LABEL,
  dealStatusTone,
  formatMoney,
  isCloseOverdue,
  type BoardColumn,
  type OpportunityOut,
  type PipelineBoard as PipelineBoardData,
  type PipelineStage,
} from "./pipeline-model";

const linkClass = "underline underline-offset-4 hover:text-fg";

export function PipelineBoard({
  workspaceId,
  board,
  today,
  canEdit,
}: {
  workspaceId: string;
  board: PipelineBoardData;
  /** `YYYY-MM-DD`, worked out on the server so the first paint and the browser agree. */
  today: string;
  canEdit: boolean;
}) {
  const move = useMoveDeal({ workspaceId });
  const [seen, setSeen] = useState(board);
  if (seen !== board) {
    // A fresh board from the server is the truth: forget moves it has already seen.
    setSeen(board);
    move.dropSettled();
  }
  const [dragId, setDragId] = useState<string | null>(null);
  const [overStageId, setOverStageId] = useState<string | null>(null);

  const stages = useMemo(() => board.columns.map((c) => c.stage), [board.columns]);
  const columns = useMemo(() => applyOps(board.columns, move.ops), [board.columns, move.ops]);
  const deals = useMemo(() => {
    const map = new Map<string, OpportunityOut>();
    for (const c of columns) for (const d of c.items) map.set(d.id, d);
    return map;
  }, [columns]);
  const total = columns.reduce((sum, c) => sum + c.count, 0);

  const dragging = dragId ? deals.get(dragId) : undefined;

  function endDrag() {
    setDragId(null);
    setOverStageId(null);
  }

  function dropOn(event: DragEvent, stage: PipelineStage) {
    event.preventDefault();
    // Only a deal this board knows about counts: text dragged in from elsewhere is ignored.
    const id = event.dataTransfer.getData("text/plain") || dragId;
    const deal = id ? deals.get(id) : undefined;
    endDrag();
    if (!deal || deal.status !== "open" || deal.stage.id === stage.id) return;
    move.move(deal, stage);
  }

  return (
    <div className="flex flex-col gap-3">
      {!canEdit ? (
        <Notice tone="info" title="View only">
          Only the workspace owner can add or move deals.
        </Notice>
      ) : (
        <p className="text-[13px] text-muted">
          Drag a card to another column, or choose a stage from its “Move to…” menu. The menu works
          with a keyboard, a screen reader and a touch screen.
        </p>
      )}
      <LiveStatus message={move.message} />

      {total === 0 ? (
        <EmptyState
          title="No deals yet"
          description="A deal is a lead you are working towards a sale. Open a lead and create a deal from it, or start one here by picking a lead. Deals you create show up in the column for their stage."
        >
          <Link
            href="/leads"
            className="inline-flex h-9 items-center rounded-md border border-line bg-elevated px-3 text-sm font-medium text-fg"
          >
            Go to leads
          </Link>
          {canEdit ? <NewDealButton workspaceId={workspaceId} stages={stages} /> : null}
        </EmptyState>
      ) : (
        <div
          role="region"
          aria-label="Pipeline board"
          tabIndex={0}
          className="relative flex items-start gap-3 overflow-x-auto pb-3"
        >
          {columns.map((column) => (
            <Column
              key={column.stage.id}
              column={column}
              stages={stages}
              today={today}
              canEdit={canEdit}
              move={move}
              dragId={dragId}
              dropTarget={
                canEdit &&
                dragging !== undefined &&
                overStageId === column.stage.id &&
                dragging.stage.id !== column.stage.id
              }
              onDragStart={setDragId}
              onDragEnd={endDrag}
              onDragOver={(event) => {
                if (!dragging || dragging.stage.id === column.stage.id) return;
                event.preventDefault();
                event.dataTransfer.dropEffect = "move";
                if (overStageId !== column.stage.id) setOverStageId(column.stage.id);
              }}
              onDragLeave={(event) => {
                if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                  setOverStageId((current) => (current === column.stage.id ? null : current));
                }
              }}
              onDrop={(event) => dropOn(event, column.stage)}
            />
          ))}
        </div>
      )}
      <MoveDialogs controller={move} />
    </div>
  );
}

/* ---------- Column ---------- */

function Column({
  column,
  stages,
  today,
  canEdit,
  move,
  dragId,
  dropTarget,
  onDragStart,
  onDragEnd,
  onDragOver,
  onDragLeave,
  onDrop,
}: {
  column: BoardColumn;
  stages: readonly PipelineStage[];
  today: string;
  canEdit: boolean;
  move: MoveController;
  dragId: string | null;
  dropTarget: boolean;
  onDragStart: (id: string) => void;
  onDragEnd: () => void;
  onDragOver: (event: DragEvent) => void;
  onDragLeave: (event: DragEvent) => void;
  onDrop: (event: DragEvent) => void;
}) {
  const { stage, count, items, unvalued, totals } = column;
  const open = !stage.is_won && !stage.is_lost;
  const headingId = `stage-${stage.id}`;
  const valued = totals;
  const weighted = open ? totals.filter((t) => t.weighted !== null) : [];

  return (
    <section
      aria-labelledby={headingId}
      data-stage={stage.key}
      data-drop-target={dropTarget ? "true" : undefined}
      onDragOver={canEdit ? onDragOver : undefined}
      onDragLeave={canEdit ? onDragLeave : undefined}
      onDrop={canEdit ? onDrop : undefined}
      className={`flex w-72 shrink-0 flex-col gap-2 rounded-lg border bg-surface p-3 ${
        dropTarget ? "border-accent ring-2 ring-accent" : "border-line"
      }`}
    >
      <header className="flex flex-col gap-1">
        <h2 id={headingId} className="flex items-center gap-2 text-sm font-semibold text-fg">
          <span className="min-w-0 break-words">{stage.name}</span>{" "}
          <Badge tone={stage.is_won ? "success" : stage.is_lost ? "danger" : "neutral"}>
            {count} <span className="sr-only">{count === 1 ? "deal" : "deals"}</span>
          </Badge>
        </h2>
        {valued.length > 0 ? (
          <p className="text-[13px] text-fg tabular-nums">
            <span className="sr-only">Total value: </span>
            {valued.map((t, i) => (
              <span key={t.currency}>
                {i > 0 ? " · " : ""}
                <span>{formatMoney(t.amount, t.currency)}</span>
              </span>
            ))}
          </p>
        ) : null}
        {weighted.length > 0 ? (
          <p className="text-[13px] text-muted tabular-nums">
            {weighted.map((t, i) => (
              <span key={t.currency}>
                {i > 0 ? " · " : ""}
                <span>{`≈ ${formatMoney(t.weighted, t.currency)} weighted`}</span>
              </span>
            ))}
          </p>
        ) : null}
        {unvalued > 0 ? <p className="text-[13px] text-muted">{unvalued} without a value</p> : null}
      </header>

      {dropTarget ? (
        <p
          aria-hidden
          className="rounded-md border border-dashed border-accent px-2 py-1.5 text-center text-[13px] text-accent"
        >
          Drop here to move to {stage.name}
        </p>
      ) : null}

      {items.length === 0 ? (
        <p className="rounded-md border border-dashed border-line px-3 py-6 text-center text-[13px] text-muted">
          No deals here
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((deal) => (
            <li key={deal.id}>
              <DealCard
                deal={deal}
                stages={stages}
                today={today}
                canEdit={canEdit}
                move={move}
                dragged={dragId === deal.id}
                onDragStart={onDragStart}
                onDragEnd={onDragEnd}
              />
            </li>
          ))}
        </ul>
      )}

      {count > items.length ? (
        <p className="text-[13px] text-muted">
          Showing the newest {items.length} of {count}.{" "}
          <Link href={tableHref({ stageId: stage.id })} className={linkClass}>
            See all {count} in the table
          </Link>
        </p>
      ) : null}
    </section>
  );
}

/* ---------- Card ---------- */

function DealCard({
  deal,
  stages,
  today,
  canEdit,
  move,
  dragged,
  onDragStart,
  onDragEnd,
}: {
  deal: OpportunityOut;
  stages: readonly PipelineStage[];
  today: string;
  canEdit: boolean;
  move: MoveController;
  dragged: boolean;
  onDragStart: (id: string) => void;
  onDragEnd: () => void;
}) {
  const busy = move.isBusy(deal.id);
  const isOpen = deal.status === "open";
  const draggable = canEdit && isOpen && !busy;
  const titleId = `deal-${deal.id}`;
  const overdue = isCloseOverdue(deal, today);
  const lead = deal.lead;

  return (
    <article
      aria-labelledby={titleId}
      aria-busy={busy || undefined}
      draggable={draggable}
      onDragStart={
        draggable
          ? (event) => {
              event.dataTransfer.setData("text/plain", deal.id);
              event.dataTransfer.effectAllowed = "move";
              onDragStart(deal.id);
            }
          : undefined
      }
      onDragEnd={draggable ? onDragEnd : undefined}
      className={`flex flex-col gap-1.5 rounded-md border border-line bg-elevated p-3 text-sm ${
        draggable ? "cursor-grab" : ""
      } ${busy ? "opacity-60" : ""} ${dragged ? "opacity-50" : ""}`.trim()}
    >
      <div className="flex flex-wrap items-start gap-1.5">
        <h3 id={titleId} className="min-w-0 flex-1 font-medium break-words text-fg">
          <Link href={dealHref(deal.id)} className={linkClass}>
            {deal.title}
          </Link>
        </h3>
        {!isOpen ? (
          <Badge tone={dealStatusTone(deal.status)}>
            {DEAL_STATUS_LABEL[deal.status] ?? deal.status}
          </Badge>
        ) : null}
        {deal.is_sample ? <SampleBadge /> : null}
      </div>

      <p className="text-[13px] break-words text-muted">
        <Link href={`/leads/${lead.id}`} className={linkClass}>
          {lead.title}
        </Link>
        {lead.company_name ? <span> · {lead.company_name}</span> : null}
      </p>

      <p className="text-[13px] text-fg tabular-nums">
        {deal.value_amount !== null ? (
          formatMoney(deal.value_amount, deal.currency)
        ) : (
          <span className="text-muted">No value yet</span>
        )}
        {deal.probability !== null ? (
          <span className="text-muted"> · {deal.probability}% chance</span>
        ) : null}
      </p>

      {deal.expected_close_date ? (
        <p className="flex flex-wrap items-center gap-1.5 text-[13px] text-muted">
          <span>
            Closes <time dateTime={deal.expected_close_date}>{deal.expected_close_date}</time>
          </span>
          {overdue ? <Badge tone="warning">Overdue</Badge> : null}
        </p>
      ) : null}

      {deal.next_action ? (
        <p className="text-[13px] break-words text-muted">Next: {deal.next_action}</p>
      ) : null}
      {deal.status === "lost" && deal.loss_reason ? (
        <p className="text-[13px] break-words text-muted">Lost because: {deal.loss_reason}</p>
      ) : null}

      {deal.open_tasks > 0 ? (
        <p className="text-[13px] text-muted">
          <Link href="/tasks" className={linkClass}>
            {deal.open_tasks} open {deal.open_tasks === 1 ? "task" : "tasks"}
          </Link>
        </p>
      ) : null}

      {busy ? <p className="text-[13px] text-muted">Moving…</p> : null}

      {canEdit ? (
        <MoveStageSelect
          deal={deal}
          stages={stages}
          mode={isOpen ? "move" : "reopen"}
          disabled={busy}
          onChoose={(stage) => (isOpen ? move.move(deal, stage) : move.reopen(deal, stage))}
        />
      ) : null}
    </article>
  );
}
