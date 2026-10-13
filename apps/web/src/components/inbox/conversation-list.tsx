import Link from "next/link";
import { Badge, EmptyState } from "@freelancer-os/ui";
import { SampleBadge } from "@/components/leads/lead-badges";
import { formatDateTime } from "@/components/leads/lead-model";
import {
  CATEGORY_LABEL,
  CATEGORY_TONE,
  FILTERS,
  PAGE_SIZE,
  counterpartLabel,
  hasFilters,
  inboxHref,
  type ConversationSummary,
  type InboxCounts,
  type InboxQuery,
} from "./inbox-model";

/** The left side of the inbox. Search and filters are plain links and a GET form, so they work without JavaScript. */
export function ConversationList({
  items,
  total,
  query,
  counts,
  hasMailbox,
}: {
  items: readonly ConversationSummary[];
  total: number;
  query: InboxQuery;
  counts: InboxCounts;
  hasMailbox: boolean;
}) {
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <form method="get" action="/inbox" role="search" className="flex gap-2">
        {query.filter ? <input type="hidden" name="filter" value={query.filter} /> : null}
        {query.account ? <input type="hidden" name="account" value={query.account} /> : null}
        <label htmlFor="inbox-search" className="sr-only">
          Search conversations
        </label>
        <input
          id="inbox-search"
          name="q"
          type="search"
          defaultValue={query.q}
          maxLength={100}
          placeholder="Search people, subjects, text…"
          className="h-9 min-w-0 flex-1 rounded-md border border-line bg-canvas px-3 text-sm text-fg placeholder:text-muted hover:border-muted"
        />
        <button
          type="submit"
          className="inline-flex h-9 shrink-0 items-center rounded-md border border-line bg-elevated px-3 text-sm font-medium text-fg hover:brightness-110"
        >
          Search
        </button>
      </form>

      <nav aria-label="Filter conversations" className="flex flex-wrap gap-1.5">
        {FILTERS.map((f) => {
          const active = query.filter === f.value;
          const badge =
            f.value === "unread"
              ? counts.unread
              : f.value === "review"
                ? counts.needs_review
                : null;
          return (
            <Link
              key={f.value || "all"}
              href={inboxHref(query, { filter: f.value, selected: "" })}
              aria-current={active ? "true" : undefined}
              className={
                "inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-[13px] " +
                (active
                  ? "border-accent bg-accent/15 text-fg"
                  : "border-line text-muted hover:text-fg")
              }
            >
              {f.label}
              {badge ? (
                <span className="rounded-full bg-elevated px-1.5 text-xs text-fg">{badge}</span>
              ) : null}
            </Link>
          );
        })}
      </nav>

      {items.length === 0 ? (
        !hasMailbox ? (
          <EmptyState
            title="No mailbox connected"
            description="Add the demo mailbox, or connect Gmail, and sync it to see conversations here."
          >
            <Link href="/integrations" className="text-sm font-medium text-accent underline">
              Go to Integrations
            </Link>
          </EmptyState>
        ) : hasFilters(query) ? (
          <EmptyState
            title="Nothing matches"
            description="No conversation fits this search or filter."
          >
            <Link
              href={inboxHref(query, { q: "", filter: "", account: "" })}
              className="text-sm font-medium text-accent underline"
            >
              Clear search and filters
            </Link>
          </EmptyState>
        ) : (
          <EmptyState
            title="No conversations yet"
            description="Sync a mailbox on the Integrations page to bring in replies."
          >
            <Link href="/integrations" className="text-sm font-medium text-accent underline">
              Go to Integrations
            </Link>
          </EmptyState>
        )
      ) : (
        <ul className="flex flex-col divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface">
          {items.map((c) => {
            const selected = c.id === query.selected;
            const category = c.classification.category;
            return (
              <li key={c.id}>
                <Link
                  href={inboxHref(query, { selected: c.id })}
                  aria-current={selected ? "true" : undefined}
                  className={
                    "flex flex-col gap-1 px-3 py-2.5 hover:bg-elevated " +
                    (selected ? "bg-elevated" : "")
                  }
                >
                  <span className="flex items-center gap-2">
                    {c.unread ? (
                      <>
                        <span
                          aria-hidden="true"
                          className="size-2 shrink-0 rounded-full bg-accent"
                        />
                        <span className="sr-only">Unread. </span>
                      </>
                    ) : null}
                    <span
                      className={
                        "min-w-0 flex-1 truncate text-sm " +
                        (c.unread ? "font-semibold text-fg" : "text-fg")
                      }
                    >
                      {counterpartLabel(c)}
                    </span>
                    <span className="shrink-0 text-xs text-muted">
                      {c.last_message_at ? formatDateTime(c.last_message_at) : ""}
                    </span>
                  </span>
                  <span className="truncate text-[13px] text-fg">
                    {c.subject || "(no subject)"}
                  </span>
                  <span className="truncate text-xs text-muted">{c.last_preview ?? ""}</span>
                  <span className="flex flex-wrap items-center gap-1.5">
                    {category ? (
                      <Badge tone={CATEGORY_TONE[category]}>{CATEGORY_LABEL[category]}</Badge>
                    ) : c.classification.status === "pending" ? (
                      <Badge tone="neutral">Classifying…</Badge>
                    ) : null}
                    {c.classification.needs_review ? (
                      <Badge tone="warning">Needs review</Badge>
                    ) : null}
                    {c.stop ? <Badge tone="danger">Stopped</Badge> : null}
                    {c.has_draft ? <Badge tone="accent">Draft</Badge> : null}
                    {c.is_demo ? <SampleBadge /> : null}
                    {c.company ? (
                      <span className="truncate text-xs text-muted">{c.company.name}</span>
                    ) : null}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}

      {pages > 1 ? (
        <nav aria-label="Pages" className="flex items-center justify-between text-sm">
          {query.page > 1 ? (
            <Link
              href={inboxHref(query, { page: query.page - 1 })}
              className="text-accent underline"
            >
              Newer
            </Link>
          ) : (
            <span />
          )}
          <span className="text-muted">
            Page {query.page} of {pages}
          </span>
          {query.page < pages ? (
            <Link
              href={inboxHref(query, { page: query.page + 1 })}
              className="text-accent underline"
            >
              Older
            </Link>
          ) : (
            <span />
          )}
        </nav>
      ) : null}
    </div>
  );
}
