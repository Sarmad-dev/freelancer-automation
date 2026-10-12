"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
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
  useToast,
} from "@freelancer-os/ui";
import { browserApi, toFailure } from "@/lib/api-client";
import { describeFailure } from "@/lib/mutation-error";
import { formatDate } from "@/lib/safe-url";
import { DoNotContactBadge, FitBadge, SampleBadge, StatusBadge } from "./lead-badges";
import { LeadCreateForm } from "./lead-create-form";
import {
  ARCHIVED_FILTERS,
  FIT_FILTERS,
  PAGE_SIZE,
  SORT_LABELS,
  activeFilterChips,
  clearFiltersHref,
  exportHref,
  hasFilters,
  leadsHref,
  pageHref,
  sortHref,
  sortState,
  type LeadListQuery,
  type SortField,
} from "./lead-list-model";
import { LEAD_STATUSES, isOverdue, type LeadOut, type TagOut } from "./lead-model";

const linkButton =
  "inline-flex h-9 items-center justify-center gap-2 rounded-md border border-line bg-elevated px-4 text-sm font-medium whitespace-nowrap text-fg hover:brightness-110";
const smallLinkButton =
  "inline-flex h-8 items-center rounded-md border border-line bg-elevated px-3 text-[13px] font-medium text-fg";
const checkbox = "size-4 accent-[var(--fos-accent)]";

function SortHeader({
  query,
  field,
  children,
}: {
  query: LeadListQuery;
  field: SortField;
  children: string;
}) {
  const state = sortState(query, field);
  return (
    <Th sort={state}>
      <Link
        href={sortHref(query, field)}
        className="inline-flex items-center gap-1 rounded-sm hover:text-fg hover:underline"
      >
        {children}
        <span aria-hidden>{state === "ascending" ? "↑" : state === "descending" ? "↓" : ""}</span>
      </Link>
    </Th>
  );
}

function FilterForm({ query, tags }: { query: LeadListQuery; tags: TagOut[] }) {
  const tagKnown = tags.some((t) => t.id === query.tagId);
  return (
    <form
      action="/leads"
      method="get"
      role="search"
      aria-label="Filter leads"
      className="flex flex-1 flex-wrap items-end gap-3"
    >
      <Field label="Search" className="min-w-48 flex-1 sm:max-w-xs">
        {(p) => <Input {...p} name="q" type="search" defaultValue={query.q} maxLength={100} />}
      </Field>
      <Field label="Fit">
        {(p) => (
          <Select {...p} name="fit" defaultValue={query.fit}>
            <option value="">Any</option>
            {FIT_FILTERS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field label="Tag">
        {(p) => (
          <Select {...p} name="tag_id" defaultValue={query.tagId}>
            <option value="">Any</option>
            {query.tagId && !tagKnown ? <option value={query.tagId}>Selected tag</option> : null}
            {tags.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field label="Show">
        {(p) => (
          <Select {...p} name="archived" defaultValue={query.archived}>
            {ARCHIVED_FILTERS.map((a) => (
              <option key={a.value} value={a.value}>
                {a.label}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <fieldset className="flex flex-col gap-1.5">
        <legend className="text-sm font-medium text-fg">Status</legend>
        <div className="flex h-9 flex-wrap items-center gap-x-3 gap-y-1">
          {LEAD_STATUSES.map((s) => (
            <label key={s.value} className="flex items-center gap-1.5 text-sm text-fg">
              <input
                type="checkbox"
                name="status"
                value={s.value}
                defaultChecked={query.status.includes(s.value)}
                className={checkbox}
              />
              {s.label}
            </label>
          ))}
        </div>
      </fieldset>
      <label className="flex h-9 items-center gap-2 text-sm text-fg">
        <input
          type="checkbox"
          name="overdue"
          value="1"
          defaultChecked={query.overdue}
          className={checkbox}
        />
        Overdue next action
      </label>
      {/* Filters and order that have no control here still survive a new search. */}
      {query.companyId ? <input type="hidden" name="company_id" value={query.companyId} /> : null}
      {query.contactId ? <input type="hidden" name="contact_id" value={query.contactId} /> : null}
      {query.source ? <input type="hidden" name="source" value={query.source} /> : null}
      {query.sample ? <input type="hidden" name="sample" value={query.sample} /> : null}
      {query.sort !== "-updated_at" ? <input type="hidden" name="sort" value={query.sort} /> : null}
      <Button type="submit" variant="secondary">
        Apply
      </Button>
    </form>
  );
}

export function LeadsTable({
  workspaceId,
  items,
  total,
  query,
  tags,
  canEdit,
  nowIso,
}: {
  workspaceId: string;
  items: LeadOut[];
  total: number;
  query: LeadListQuery;
  tags: TagOut[];
  canEdit: boolean;
  /** Server time as an ISO string, so "Overdue" renders the same on server and client. */
  nowIso: string;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const now = new Date(nowIso);
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [bulkTag, setBulkTag] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkError, setBulkError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const allRef = useRef<HTMLInputElement>(null);

  const sortField = query.sort.replace(/^-/, "") as SortField;
  const filtered = hasFilters(query);
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const onPage = items.filter((i) => selected.has(i.id));
  const allSelected = items.length > 0 && onPage.length === items.length;

  useEffect(() => {
    if (allRef.current) allRef.current.indeterminate = onPage.length > 0 && !allSelected;
  }, [onPage.length, allSelected]);

  // `onPage` is derived from the current rows, so ids left over from another page are never sent.

  const chips = activeFilterChips(query, {
    tagName: (id) => tags.find((t) => t.id === id)?.name,
    companyName: (id) => items.find((i) => i.company?.id === id)?.company?.name,
    contactName: (id) => items.find((i) => i.contact?.id === id)?.contact?.full_name,
  });

  function toggleOne(id: string, on: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  async function bulk(mode: "add" | "remove") {
    if (!bulkTag || onPage.length === 0) return;
    setBulkBusy(true);
    setBulkError(null);
    const lead_ids = onPage.map((i) => i.id);
    try {
      const { data, error, response } = await browserApi().POST(
        "/api/v1/workspaces/{workspace_id}/leads/bulk-tags",
        {
          params: { path: { workspace_id: workspaceId } },
          body:
            mode === "add"
              ? { lead_ids, add_tag_ids: [bulkTag] }
              : { lead_ids, remove_tag_ids: [bulkTag] },
        },
      );
      if (response.ok && data) {
        const n = mode === "add" ? data.tags_added : data.tags_removed;
        toast({
          title: mode === "add" ? "Tag added" : "Tag removed",
          description: `${data.leads} ${data.leads === 1 ? "lead" : "leads"} checked · ${n} ${n === 1 ? "tag" : "tags"} ${mode === "add" ? "added" : "removed"}`,
          tone: "success",
        });
        setSelected(new Set());
        router.refresh();
      } else {
        const out = describeFailure(error, response, "lead");
        if (out) setBulkError(out.failure.text);
      }
    } catch {
      setBulkError(toFailure(undefined).message);
    }
    setBulkBusy(false);
  }

  const noLeadsAtAll = items.length === 0 && total === 0 && !filtered;

  return (
    <div className="flex flex-col gap-5">
      {!canEdit ? (
        <Notice tone="info" title="View only">
          Only the workspace owner can add, tag, import or export leads.
        </Notice>
      ) : null}

      {noLeadsAtAll ? null : (
        <div className="flex flex-wrap items-end gap-3">
          <FilterForm key={leadsHref({ ...query, page: 1 })} query={query} tags={tags} />
          {canEdit ? (
            <div className="flex flex-wrap gap-2">
              <a href={exportHref(workspaceId, query)} download className={linkButton}>
                Export CSV
              </a>
              <Link href="/leads/import" className={linkButton}>
                Import CSV
              </Link>
              <Button onClick={() => setAdding(true)}>New lead</Button>
            </div>
          ) : null}
        </div>
      )}

      {chips.length > 0 ? (
        <ul aria-label="Active filters" className="flex flex-wrap items-center gap-2">
          {chips.map((chip) => (
            <li key={chip.id}>
              <span className="inline-flex items-center gap-1 rounded-full border border-line bg-elevated py-0.5 pr-1 pl-3 text-[13px] text-fg">
                {chip.label}
                <Link
                  href={chip.href}
                  aria-label={`Remove filter: ${chip.label}`}
                  className="flex size-5 items-center justify-center rounded-full text-muted hover:bg-line hover:text-fg"
                >
                  <span aria-hidden>×</span>
                </Link>
              </span>
            </li>
          ))}
          <li>
            <Link
              href={clearFiltersHref(query)}
              className="text-[13px] text-muted underline underline-offset-4 hover:text-fg"
            >
              Clear filters
            </Link>
          </li>
        </ul>
      ) : null}

      {canEdit && onPage.length > 0 ? (
        <div
          role="group"
          aria-label="Bulk tag actions"
          className="flex flex-wrap items-end gap-3 rounded-lg border border-line bg-elevated p-3"
        >
          <p role="status" className="self-center text-sm font-medium text-fg">
            {onPage.length} selected
          </p>
          {tags.length > 0 ? (
            <>
              <Field label="Tag for selected leads">
                {(p) => (
                  <Select {...p} value={bulkTag} onChange={(e) => setBulkTag(e.target.value)}>
                    <option value="">Choose a tag…</option>
                    {tags.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              <Button
                variant="secondary"
                disabled={!bulkTag || bulkBusy}
                onClick={() => void bulk("add")}
              >
                Add tag
              </Button>
              <Button
                variant="secondary"
                disabled={!bulkTag || bulkBusy}
                onClick={() => void bulk("remove")}
              >
                Remove tag
              </Button>
            </>
          ) : (
            <p className="self-center text-sm text-muted">
              You have no tags yet. Create one from a lead&apos;s page first.
            </p>
          )}
          <Button variant="ghost" onClick={() => setSelected(new Set())} disabled={bulkBusy}>
            Clear selection
          </Button>
        </div>
      ) : null}
      {bulkError ? (
        <Notice tone="danger" title="Couldn't update the tags">
          {bulkError}
        </Notice>
      ) : null}

      {items.length === 0 ? (
        noLeadsAtAll ? (
          <EmptyState
            title="No leads yet"
            description="Add a lead by hand, import a CSV you already have, or start from the sample data. Nothing here needs an outside lead source."
          >
            {canEdit ? (
              <>
                <Button onClick={() => setAdding(true)}>New lead</Button>
                <Link href="/leads/import" className={linkButton}>
                  Import CSV
                </Link>
              </>
            ) : null}
          </EmptyState>
        ) : total > 0 ? (
          <EmptyState
            title="No leads on this page"
            description={`There are ${total} leads in all, but not this far in.`}
          >
            <Link href={pageHref(query, 1)} className={linkButton}>
              Go to the first page
            </Link>
          </EmptyState>
        ) : (
          <EmptyState
            title="No leads match these filters"
            description="Try a different search, or clear the filters."
          >
            <Link href={clearFiltersHref(query)} className={linkButton}>
              Clear filters
            </Link>
          </EmptyState>
        )
      ) : (
        <TableContainer>
          <Table>
            <caption className="sr-only">
              Leads, {total} in total, page {query.page} of {pageCount}. Sorted by{" "}
              {SORT_LABELS[sortField]}, {query.sort.startsWith("-") ? "descending" : "ascending"}.
            </caption>
            <thead>
              <tr>
                {canEdit ? (
                  <Th className="w-10">
                    <input
                      ref={allRef}
                      type="checkbox"
                      className={checkbox}
                      aria-label="Select all leads on this page"
                      checked={allSelected}
                      onChange={(e) =>
                        setSelected(e.target.checked ? new Set(items.map((i) => i.id)) : new Set())
                      }
                    />
                  </Th>
                ) : null}
                <SortHeader query={query} field="title">
                  Title
                </SortHeader>
                <Th>Company</Th>
                <Th>Contact</Th>
                <SortHeader query={query} field="status">
                  Status
                </SortHeader>
                <SortHeader query={query} field="fit_score">
                  Fit
                </SortHeader>
                <SortHeader query={query} field="next_action_at">
                  Next action
                </SortHeader>
                <SortHeader query={query} field="updated_at">
                  Updated
                </SortHeader>
              </tr>
            </thead>
            <tbody>
              {items.map((lead) => (
                <tr key={lead.id} className={selected.has(lead.id) ? "bg-elevated" : undefined}>
                  {canEdit ? (
                    <Td className="w-10">
                      <input
                        type="checkbox"
                        className={checkbox}
                        aria-label={`Select ${lead.title}`}
                        checked={selected.has(lead.id)}
                        onChange={(e) => toggleOne(lead.id, e.target.checked)}
                      />
                    </Td>
                  ) : null}
                  <Td className="max-w-xs">
                    <Link
                      href={`/leads/${lead.id}`}
                      className="line-clamp-2 font-medium break-words underline-offset-4 hover:underline"
                    >
                      {lead.title}
                    </Link>
                    {lead.is_sample ||
                    lead.do_not_contact ||
                    lead.archived_at ||
                    lead.tags.length > 0 ? (
                      <ul aria-label="Labels" className="mt-1 flex flex-wrap gap-1">
                        {lead.is_sample ? (
                          <li>
                            <SampleBadge />
                          </li>
                        ) : null}
                        {lead.do_not_contact ? (
                          <li>
                            <DoNotContactBadge />
                          </li>
                        ) : null}
                        {lead.archived_at ? (
                          <li>
                            <Badge>Archived</Badge>
                          </li>
                        ) : null}
                        {lead.tags.map((tag) => (
                          <li key={tag.id}>
                            <Badge>{tag.name}</Badge>
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </Td>
                  <Td className="max-w-48">
                    <span className="line-clamp-2 break-words">
                      {lead.company ? (
                        <Link
                          href={`/leads/companies/${lead.company.id}`}
                          className="underline-offset-4 hover:underline"
                        >
                          {lead.company.name}
                        </Link>
                      ) : (
                        <span className="text-muted">None</span>
                      )}
                    </span>
                  </Td>
                  <Td className="max-w-48">
                    <span className="line-clamp-2 break-words">
                      {lead.contact ? (
                        <Link
                          href={`/leads/contacts/${lead.contact.id}`}
                          className="underline-offset-4 hover:underline"
                        >
                          {lead.contact.full_name}
                        </Link>
                      ) : (
                        <span className="text-muted">None</span>
                      )}
                    </span>
                  </Td>
                  <Td>
                    <StatusBadge status={lead.status} />
                  </Td>
                  <Td>
                    <FitBadge band={lead.fit_band} score={lead.fit_score} />
                  </Td>
                  <Td className="max-w-56">
                    {lead.next_action || lead.next_action_at ? (
                      <div className="flex flex-col items-start gap-1">
                        {lead.next_action ? (
                          <span className="line-clamp-2 break-words">{lead.next_action}</span>
                        ) : null}
                        <span className="flex flex-wrap items-center gap-2 text-[13px] text-muted">
                          {lead.next_action_at ? (
                            <time dateTime={lead.next_action_at}>
                              {formatDate(lead.next_action_at)}
                            </time>
                          ) : null}
                          {isOverdue(lead, now) ? <Badge tone="danger">Overdue</Badge> : null}
                        </span>
                      </div>
                    ) : (
                      <span className="text-muted">None</span>
                    )}
                  </Td>
                  <Td className="whitespace-nowrap text-muted">
                    <time dateTime={lead.updated_at}>{formatDate(lead.updated_at)}</time>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </TableContainer>
      )}

      {total > 0 ? (
        <nav aria-label="Pagination" className="flex items-center justify-between gap-4 text-sm">
          <p className="text-muted">
            Page {query.page} of {pageCount} · {total} {total === 1 ? "lead" : "leads"}
          </p>
          <div className="flex gap-2">
            {query.page > 1 ? (
              <Link rel="prev" href={pageHref(query, query.page - 1)} className={smallLinkButton}>
                Previous
              </Link>
            ) : null}
            {query.page < pageCount ? (
              <Link rel="next" href={pageHref(query, query.page + 1)} className={smallLinkButton}>
                Next
              </Link>
            ) : null}
          </div>
        </nav>
      ) : null}

      {noLeadsAtAll ? null : (
        <p className="text-[13px] text-muted">
          Fit scores are rule-based. They come from the criteria you set, never from AI, and they
          are a guide, not a verdict.{" "}
          <Link href="/leads/scoring" className="underline underline-offset-4 hover:text-fg">
            How is fit calculated?
          </Link>
        </p>
      )}

      {adding ? (
        <LeadCreateForm workspaceId={workspaceId} tags={tags} onClose={() => setAdding(false)} />
      ) : null}
    </div>
  );
}
