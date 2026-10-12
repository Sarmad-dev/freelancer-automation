"use client";

import Link from "next/link";
import { useState } from "react";
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
import { formatDate, safeExternalUrl } from "@/lib/safe-url";
import { CompanyDrawer } from "./company-form";
import {
  ARCHIVED_FILTERS,
  COMPANIES_PATH,
  DEFAULT_SORT,
  PAGE_SIZE,
  clearFiltersHref,
  hasFilters,
  pageHref,
  sortHref,
  sortState,
  type CompanyOut,
  type CompanyQuery,
  type SortField,
} from "./company-model";
import { SampleBadge } from "./lead-badges";
import { COMPANY_SIZES, hrefWith, sizeLabel } from "./lead-model";

const linkClass = "underline underline-offset-4 hover:text-accent";
const buttonLinkClass =
  "inline-flex h-8 items-center rounded-md border border-line bg-elevated px-3 text-[13px] font-medium text-fg";

export function WebsiteLink({ website }: { website: string | null }) {
  if (!website) return <span className="text-muted">—</span>;
  const href = safeExternalUrl(website);
  return href ? (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer nofollow"
      className={`${linkClass} break-all`}
    >
      {website}
    </a>
  ) : (
    <span className="break-all">{website}</span>
  );
}

export function ArchivedBadge() {
  return <Badge tone="neutral">Archived</Badge>;
}

function SortHeader({
  query,
  field,
  label,
}: {
  query: CompanyQuery;
  field: SortField;
  label: string;
}) {
  const state = sortState(query, field);
  return (
    <Th sort={state}>
      <Link href={sortHref(query, field)} className="inline-flex items-center gap-1 hover:text-fg">
        {label}
        <span aria-hidden>{state === "ascending" ? "▲" : state === "descending" ? "▼" : ""}</span>
      </Link>
    </Th>
  );
}

export function CompaniesTable({
  workspaceId,
  items,
  total,
  query,
  canEdit,
}: {
  workspaceId: string;
  items: CompanyOut[];
  total: number;
  query: CompanyQuery;
  canEdit: boolean;
}) {
  const [adding, setAdding] = useState(false);
  const filtered = hasFilters(query);
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="flex flex-col gap-5">
      {!canEdit ? (
        <Notice tone="info" title="View only">
          Only the workspace owner can add or change companies.
        </Notice>
      ) : null}

      <div className="flex flex-wrap items-end gap-3">
        <form
          action={COMPANIES_PATH}
          method="get"
          role="search"
          aria-label="Filter companies"
          className="flex flex-1 flex-wrap items-end gap-3"
        >
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
                placeholder="Name or website"
              />
            )}
          </Field>
          <Field label="Industry" className="min-w-40">
            {(p) => <Input {...p} name="industry" defaultValue={query.industry} maxLength={100} />}
          </Field>
          <Field label="Size">
            {(p) => (
              <Select {...p} name="size_label" defaultValue={query.size}>
                <option value="">Any size</option>
                {COMPANY_SIZES.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
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
          <Button type="submit" variant="secondary">
            Apply
          </Button>
          {filtered ? (
            <Link
              href={clearFiltersHref(query)}
              className="inline-flex h-9 items-center px-2 text-sm text-muted underline underline-offset-4 hover:text-fg"
            >
              Clear filters
            </Link>
          ) : null}
        </form>
        {canEdit ? <Button onClick={() => setAdding(true)}>New company</Button> : null}
      </div>

      {items.length === 0 ? (
        total > 0 ? (
          <EmptyState
            title="No companies on this page"
            description="That page is past the end of the list."
          >
            <Link href={pageHref(query, 1)} className={buttonLinkClass}>
              Back to the first page
            </Link>
          </EmptyState>
        ) : filtered ? (
          <EmptyState
            title="No companies match those filters"
            description="Try a different search, or clear the filters."
          >
            <Link href={clearFiltersHref(query)} className={buttonLinkClass}>
              Clear filters
            </Link>
          </EmptyState>
        ) : (
          <EmptyState
            title="No companies yet"
            description="Companies group your leads and contacts. Add one by hand, or import a CSV on the Import tab."
          >
            {canEdit ? (
              <Button onClick={() => setAdding(true)}>Add your first company</Button>
            ) : null}
          </EmptyState>
        )
      ) : (
        <TableContainer>
          <Table>
            <caption className="sr-only">
              Companies, {total} in total. Column headings are links that change the sort order.
            </caption>
            <thead>
              <tr>
                <SortHeader query={query} field="name" label="Name" />
                <Th>Website</Th>
                <SortHeader query={query} field="industry" label="Industry" />
                <Th>Size</Th>
                <Th>Location</Th>
                <Th>Leads</Th>
                <Th>Contacts</Th>
                <SortHeader query={query} field="updated_at" label="Updated" />
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.id}>
                  <Td className="max-w-64 font-medium">
                    <div className="flex flex-wrap items-center gap-2">
                      <Link
                        href={`${COMPANIES_PATH}/${c.id}`}
                        className={`${linkClass} break-words`}
                      >
                        {c.name}
                      </Link>
                      {c.is_sample ? <SampleBadge /> : null}
                      {c.archived_at ? <ArchivedBadge /> : null}
                    </div>
                  </Td>
                  <Td className="max-w-56">
                    <WebsiteLink website={c.website} />
                  </Td>
                  <Td className="break-words">
                    {c.industry || <span className="text-muted">—</span>}
                  </Td>
                  <Td className="whitespace-nowrap">
                    {sizeLabel(c.size_label) || <span className="text-muted">—</span>}
                  </Td>
                  <Td className="break-words">
                    {c.location || <span className="text-muted">—</span>}
                  </Td>
                  <Td className="whitespace-nowrap">
                    <Link
                      href={hrefWith("/leads", { company_id: c.id })}
                      className={linkClass}
                      aria-label={`${c.lead_count} ${c.lead_count === 1 ? "lead" : "leads"} at ${c.name}`}
                    >
                      {c.lead_count}
                    </Link>
                  </Td>
                  <Td className="whitespace-nowrap">
                    <Link
                      href={hrefWith("/leads/contacts", { company_id: c.id })}
                      className={linkClass}
                      aria-label={`${c.contact_count} ${c.contact_count === 1 ? "contact" : "contacts"} at ${c.name}`}
                    >
                      {c.contact_count}
                    </Link>
                  </Td>
                  <Td className="whitespace-nowrap text-muted">
                    <time dateTime={c.updated_at}>{formatDate(c.updated_at)}</time>
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
            Page {query.page} of {pageCount} · {total} {total === 1 ? "company" : "companies"}
          </p>
          <div className="flex gap-2">
            {query.page > 1 ? (
              <Link rel="prev" href={pageHref(query, query.page - 1)} className={buttonLinkClass}>
                Previous
              </Link>
            ) : null}
            {query.page < pageCount ? (
              <Link rel="next" href={pageHref(query, query.page + 1)} className={buttonLinkClass}>
                Next
              </Link>
            ) : null}
          </div>
        </nav>
      ) : null}

      {adding ? <CompanyDrawer workspaceId={workspaceId} onClose={() => setAdding(false)} /> : null}
    </div>
  );
}
