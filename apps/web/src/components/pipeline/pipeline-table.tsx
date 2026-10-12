"use client";

import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";
import {
  Badge,
  Button,
  EmptyState,
  Field,
  Input,
  Notice,
  Select,
  Table,
  TableContainer,
  Td,
  Th,
} from "@freelancer-os/ui";
import { formatDate } from "@/lib/safe-url";
import { SampleBadge } from "../leads/lead-badges";
import { LiveStatus, MoveDialogs, MoveStageSelect, overlayDeal, useMoveDeal } from "./deal-move";
import { NewDealButton } from "./opportunity-create-drawer";
import {
  DEFAULT_SORT,
  PAGE_SIZE,
  PIPELINE_PATH,
  STATUS_FILTERS,
  dealHref,
  hasPipelineFilters,
  pageHref,
  sortHref,
  sortState,
  tableHref,
  type PipelineQuery,
  type SortField,
} from "./pipeline-list-model";
import {
  DEAL_STATUS_LABEL,
  dealStatusTone,
  formatMoney,
  isCloseOverdue,
  stageTone,
  type OpportunityOut,
  type PipelineStage,
} from "./pipeline-model";

const linkButton =
  "inline-flex h-8 items-center rounded-md border border-line bg-elevated px-3 text-[13px] font-medium text-fg";
const linkClass = "underline underline-offset-4 hover:text-fg";

function SortHeader({
  query,
  field,
  children,
}: {
  query: PipelineQuery;
  field: SortField;
  children: ReactNode;
}) {
  const state = sortState(query, field);
  return (
    <Th sort={state}>
      <Link
        href={sortHref(query, field)}
        className="inline-flex items-center gap-1 underline-offset-4 hover:text-fg hover:underline"
      >
        {children}
        <span aria-hidden>{state === "ascending" ? "↑" : state === "descending" ? "↓" : ""}</span>
      </Link>
    </Th>
  );
}

export function PipelineTable({
  workspaceId,
  deals,
  total,
  query,
  stages,
  today,
  canEdit,
}: {
  workspaceId: string;
  deals: OpportunityOut[];
  total: number;
  query: PipelineQuery;
  stages: PipelineStage[];
  /** `YYYY-MM-DD`, worked out on the server. */
  today: string;
  canEdit: boolean;
}) {
  const move = useMoveDeal({ workspaceId });
  const [seen, setSeen] = useState(deals);
  if (seen !== deals) {
    setSeen(deals);
    move.dropSettled();
  }
  const rows = useMemo(() => deals.map((d) => overlayDeal(d, move.ops)), [deals, move.ops]);

  const filtered = hasPipelineFilters(query);
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const stageKnown = !query.stageId || stages.some((s) => s.id === query.stageId);

  return (
    <div className="flex flex-col gap-5">
      {!canEdit ? (
        <Notice tone="info" title="View only">
          Only the workspace owner can add or move deals.
        </Notice>
      ) : null}

      <form
        action={PIPELINE_PATH}
        method="get"
        role="search"
        aria-label="Filter deals"
        className="flex flex-wrap items-end gap-3"
      >
        <input type="hidden" name="view" value="table" />
        {query.sort !== DEFAULT_SORT ? (
          <input type="hidden" name="sort" value={query.sort} />
        ) : null}
        <Field label="Search" className="min-w-48 flex-1 sm:max-w-xs">
          {(p) => (
            <Input
              {...p}
              name="q"
              type="search"
              defaultValue={query.q}
              maxLength={100}
              placeholder="Deal, lead or company"
            />
          )}
        </Field>
        <Field label="Status">
          {(p) => (
            <Select {...p} name="status" defaultValue={query.status}>
              <option value="">All</option>
              {STATUS_FILTERS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Stage">
          {(p) => (
            <Select {...p} name="stage_id" defaultValue={query.stageId}>
              <option value="">All stages</option>
              {stageKnown ? null : <option value={query.stageId}>Selected stage</option>}
              {stages.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Button type="submit" variant="secondary">
          Apply
        </Button>
        {filtered ? (
          <Link
            href={tableHref()}
            className="inline-flex h-9 items-center px-2 text-sm text-muted underline underline-offset-4 hover:text-fg"
          >
            Clear filters
          </Link>
        ) : null}
      </form>

      <LiveStatus message={move.message} />

      {rows.length === 0 ? (
        query.page > 1 && total > 0 ? (
          <EmptyState title="Nothing on this page" description="There are fewer deals than that.">
            <Link href={pageHref(query, 1)} className={linkButton}>
              Back to the first page
            </Link>
          </EmptyState>
        ) : filtered ? (
          <EmptyState
            title="No deals match those filters"
            description="Try a different search, or clear the filters."
          >
            <Link href={tableHref()} className={linkButton}>
              Clear filters
            </Link>
          </EmptyState>
        ) : (
          <EmptyState
            title="No deals yet"
            description="A deal is a lead you are working towards a sale. Open a lead and create a deal from it, or start one here by picking a lead."
          >
            <Link href="/leads" className={linkButton}>
              Go to leads
            </Link>
            {canEdit ? <NewDealButton workspaceId={workspaceId} stages={stages} /> : null}
          </EmptyState>
        )
      ) : (
        <TableContainer>
          <Table>
            <caption className="sr-only">
              Deals, {total} in total. Use the Deal, Value, Chance, Expected close and Updated
              column headings to change the order.
            </caption>
            <thead>
              <tr>
                <SortHeader query={query} field="title">
                  Deal
                </SortHeader>
                <Th>Lead</Th>
                <Th>Stage</Th>
                <SortHeader query={query} field="value_amount">
                  Value
                </SortHeader>
                <SortHeader query={query} field="probability">
                  Chance
                </SortHeader>
                <SortHeader query={query} field="expected_close_date">
                  Expected close
                </SortHeader>
                <Th>Next action</Th>
                <Th>Open tasks</Th>
                <SortHeader query={query} field="updated_at">
                  Updated
                </SortHeader>
              </tr>
            </thead>
            <tbody>
              {rows.map((deal) => (
                <DealRow
                  key={deal.id}
                  deal={deal}
                  stages={stages}
                  today={today}
                  canEdit={canEdit}
                  busy={move.isBusy(deal.id)}
                  onMove={(stage) =>
                    deal.status === "open" ? move.move(deal, stage) : move.reopen(deal, stage)
                  }
                />
              ))}
            </tbody>
          </Table>
        </TableContainer>
      )}

      {rows.length > 0 ? (
        <nav aria-label="Pagination" className="flex items-center justify-between gap-4 text-sm">
          <p className="text-muted">
            Page {query.page} of {pageCount} · {total} {total === 1 ? "deal" : "deals"}
          </p>
          <div className="flex gap-2">
            {query.page > 1 ? (
              <Link rel="prev" href={pageHref(query, query.page - 1)} className={linkButton}>
                Previous
              </Link>
            ) : null}
            {query.page < pageCount ? (
              <Link rel="next" href={pageHref(query, query.page + 1)} className={linkButton}>
                Next
              </Link>
            ) : null}
          </div>
        </nav>
      ) : null}

      <MoveDialogs controller={move} />
    </div>
  );
}

function DealRow({
  deal,
  stages,
  today,
  canEdit,
  busy,
  onMove,
}: {
  deal: OpportunityOut;
  stages: PipelineStage[];
  today: string;
  canEdit: boolean;
  busy: boolean;
  onMove: (stage: PipelineStage) => void;
}) {
  const lead = deal.lead;
  // A stage called "Won" already says it; a renamed stage still gets the status in words.
  const statusLabel = DEAL_STATUS_LABEL[deal.status] ?? deal.status;
  const none = (
    <span className="text-muted">
      <span aria-hidden>—</span>
      <span className="sr-only">None</span>
    </span>
  );
  return (
    <tr aria-busy={busy || undefined} className={busy ? "opacity-60" : undefined}>
      <Td className="max-w-xs font-medium">
        <div className="flex flex-wrap items-center gap-1.5">
          <Link href={dealHref(deal.id)} className={`${linkClass} break-words`}>
            {deal.title}
          </Link>
          {deal.is_sample ? <SampleBadge /> : null}
        </div>
      </Td>
      <Td className="max-w-56 break-words">
        <Link href={`/leads/${lead.id}`} className={linkClass}>
          {lead.title}
        </Link>
        {lead.company_name ? <span className="text-muted"> · {lead.company_name}</span> : null}
      </Td>
      <Td>
        <div className="flex min-w-36 flex-col items-start gap-1.5">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge tone={stageTone(deal.stage)}>{deal.stage.name}</Badge>
            {deal.status !== "open" &&
            statusLabel.toLowerCase() !== deal.stage.name.toLowerCase() ? (
              <Badge tone={dealStatusTone(deal.status)}>{statusLabel}</Badge>
            ) : null}
          </div>
          {canEdit ? (
            <MoveStageSelect
              deal={deal}
              stages={stages}
              mode={deal.status === "open" ? "move" : "reopen"}
              disabled={busy}
              onChoose={onMove}
            />
          ) : null}
        </div>
      </Td>
      <Td className="whitespace-nowrap tabular-nums">
        {deal.value_amount !== null ? formatMoney(deal.value_amount, deal.currency) : none}
      </Td>
      <Td className="whitespace-nowrap tabular-nums">
        {deal.probability !== null ? `${deal.probability}%` : none}
      </Td>
      <Td className="whitespace-nowrap">
        {deal.expected_close_date ? (
          <span className="flex items-center gap-1.5">
            <time dateTime={deal.expected_close_date}>{deal.expected_close_date}</time>
            {isCloseOverdue(deal, today) ? <Badge tone="warning">Overdue</Badge> : null}
          </span>
        ) : (
          none
        )}
      </Td>
      <Td className="max-w-56 break-words">{deal.next_action ?? none}</Td>
      <Td className="whitespace-nowrap tabular-nums">
        {deal.open_tasks > 0 ? (
          <Link href="/tasks" className={linkClass}>
            {deal.open_tasks}{" "}
            <span className="sr-only">open {deal.open_tasks === 1 ? "task" : "tasks"}</span>
          </Link>
        ) : (
          <span>0</span>
        )}
      </Td>
      <Td className="whitespace-nowrap text-muted">
        <time dateTime={deal.updated_at}>{formatDate(deal.updated_at)}</time>
      </Td>
    </tr>
  );
}
