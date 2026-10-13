import { LEAD_STATUSES, firstParam, hrefWith, pageParam, type LeadStatus } from "./lead-model";

export const PAGE_SIZE = 25;
export const LEADS_PATH = "/leads";

export const SORT_FIELDS = [
  "updated_at",
  "created_at",
  "title",
  "status",
  "fit_score",
  "last_activity_at",
  "next_action_at",
] as const;
export type SortField = (typeof SORT_FIELDS)[number];
export const DEFAULT_SORT = "-updated_at";

export const FIT_FILTERS = [
  { value: "strong", label: "Strong fit" },
  { value: "possible", label: "Possible fit" },
  { value: "weak", label: "Weak fit" },
  { value: "unscored", label: "Not scored" },
] as const;
const FIT_VALUES = FIT_FILTERS.map((f) => f.value);
export type FitFilter = (typeof FIT_FILTERS)[number]["value"];

export const ARCHIVED_FILTERS = [
  { value: "active", label: "Active leads" },
  { value: "archived", label: "Archived only" },
  { value: "all", label: "Active and archived" },
] as const;
const ARCHIVED_VALUES = ARCHIVED_FILTERS.map((a) => a.value);
export type ArchivedFilter = (typeof ARCHIVED_FILTERS)[number]["value"];

export type SampleFilter = "only" | "exclude";

export interface LeadListQuery {
  q: string;
  status: LeadStatus[];
  fit: FitFilter | "";
  tagId: string;
  companyId: string;
  contactId: string;
  source: string;
  archived: ArchivedFilter;
  overdue: boolean;
  sample: SampleFilter | "";
  /** Always a valid API sort string (a field, optionally `-` prefixed). */
  sort: string;
  page: number;
}

type RawParams = Record<string, string | string[] | undefined>;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function all(params: RawParams, name: string): string[] {
  const value = params[name];
  return Array.isArray(value) ? value : value === undefined ? [] : [value];
}

function uuidParam(params: RawParams, name: string): string {
  const value = firstParam(params, name).trim();
  return UUID.test(value) ? value.toLowerCase() : "";
}

function pick<T extends string>(value: string, allowed: readonly T[]): T | "" {
  return allowed.includes(value as T) ? (value as T) : "";
}

export function isValidSort(sort: string): boolean {
  const field = sort.startsWith("-") ? sort.slice(1) : sort;
  return (SORT_FIELDS as readonly string[]).includes(field);
}

/** Untrusted URL params -> a validated query. Anything unrecognised is dropped, never forwarded to the API. */
export function parseLeadQuery(params: RawParams): LeadListQuery {
  const known = LEAD_STATUSES.map((s) => s.value as string);
  const status = [
    ...new Set(all(params, "status").filter((s) => known.includes(s))),
  ] as LeadStatus[];
  const sort = firstParam(params, "sort");
  const overdue = firstParam(params, "overdue");
  return {
    q: firstParam(params, "q").trim().slice(0, 100),
    status: LEAD_STATUSES.map((s) => s.value).filter((s) => status.includes(s)),
    fit: pick(firstParam(params, "fit"), FIT_VALUES),
    tagId: uuidParam(params, "tag_id"),
    companyId: uuidParam(params, "company_id"),
    contactId: uuidParam(params, "contact_id"),
    source: firstParam(params, "source").trim().slice(0, 100),
    archived: pick(firstParam(params, "archived"), ARCHIVED_VALUES) || "active",
    overdue: overdue === "1" || overdue === "true",
    sample: pick(firstParam(params, "sample"), ["only", "exclude"] as const),
    sort: isValidSort(sort) ? sort : DEFAULT_SORT,
    page: pageParam(params),
  };
}

/** Everything that narrows the list (no sort, no page). */
export function hasFilters(query: LeadListQuery): boolean {
  return Boolean(
    query.q ||
    query.status.length ||
    query.fit ||
    query.tagId ||
    query.companyId ||
    query.contactId ||
    query.source ||
    query.archived !== "active" ||
    query.overdue ||
    query.sample,
  );
}

function pairs(
  query: LeadListQuery,
  withPage: boolean,
): Record<string, string | number | undefined> {
  return {
    q: query.q,
    fit: query.fit,
    tag_id: query.tagId,
    company_id: query.companyId,
    contact_id: query.contactId,
    source: query.source,
    archived: query.archived === "active" ? undefined : query.archived,
    overdue: query.overdue ? "1" : undefined,
    sample: query.sample,
    sort: query.sort === DEFAULT_SORT ? undefined : query.sort,
    ...(withPage ? { page: query.page } : {}),
  };
}

function withStatuses(href: string, statuses: readonly string[]): string {
  if (statuses.length === 0) return href;
  const extra = statuses.map((s) => `status=${encodeURIComponent(s)}`).join("&");
  return href.includes("?") ? `${href}&${extra}` : `${href}?${extra}`;
}

/** Link target for a query on the leads page (defaults are omitted so URLs stay clean). */
export function leadsHref(query: LeadListQuery): string {
  return withStatuses(hrefWith(LEADS_PATH, pairs(query, true)), query.status);
}

/** Same filters, a different page. */
export function pageHref(query: LeadListQuery, page: number): string {
  return leadsHref({ ...query, page });
}

/** The same filters and order as the list, with no page: a download covers every matching lead. */
export function exportHref(workspaceId: string, query: LeadListQuery): string {
  const params: Record<string, string | number | undefined> = {
    q: query.q,
    fit: query.fit,
    tag_id: query.tagId,
    company_id: query.companyId,
    contact_id: query.contactId,
    source: query.source,
    archived: query.archived === "active" ? undefined : query.archived,
    overdue: query.overdue ? "true" : undefined,
    sample: query.sample,
    sort: query.sort,
  };
  return withStatuses(
    hrefWith(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/leads/export`, params),
    query.status,
  );
}

/** Query-string parameters for the list API. */
export function apiQuery(query: LeadListQuery) {
  return {
    limit: PAGE_SIZE,
    offset: (query.page - 1) * PAGE_SIZE,
    sort: query.sort,
    ...(query.q ? { q: query.q } : {}),
    ...(query.status.length ? { status: query.status } : {}),
    ...(query.fit ? { fit: query.fit } : {}),
    ...(query.tagId ? { tag_id: query.tagId } : {}),
    ...(query.companyId ? { company_id: query.companyId } : {}),
    ...(query.contactId ? { contact_id: query.contactId } : {}),
    ...(query.source ? { source: query.source } : {}),
    archived: query.archived,
    ...(query.overdue ? { overdue: true } : {}),
    ...(query.sample ? { sample: query.sample } : {}),
  };
}

/* ---------- sorting ---------- */

export const SORT_LABELS: Record<SortField, string> = {
  updated_at: "Updated",
  created_at: "Created",
  title: "Title",
  status: "Status",
  fit_score: "Fit",
  last_activity_at: "Last activity",
  next_action_at: "Next action",
};

export function sortState(
  query: LeadListQuery,
  field: SortField,
): "ascending" | "descending" | "none" {
  if (query.sort === field) return "ascending";
  if (query.sort === `-${field}`) return "descending";
  return "none";
}

/** Text columns start A to Z; dates and scores start with the biggest or newest first. */
const ASC_FIRST: readonly SortField[] = ["title", "status"];

/** Clicking the active column flips its direction; a new column starts in its natural direction. */
export function sortHref(query: LeadListQuery, field: SortField): string {
  const state = sortState(query, field);
  const sort =
    state === "ascending"
      ? `-${field}`
      : state === "descending"
        ? field
        : ASC_FIRST.includes(field)
          ? field
          : `-${field}`;
  return leadsHref({ ...query, sort, page: 1 });
}

/* ---------- active filter chips ---------- */

export interface FilterChipLink {
  id: string;
  label: string;
  /** The current list without this one filter. */
  href: string;
}

export interface FilterLookup {
  tagName: (id: string) => string | undefined;
  companyName: (id: string) => string | undefined;
  contactName: (id: string) => string | undefined;
}

export function activeFilterChips(query: LeadListQuery, lookup: FilterLookup): FilterChipLink[] {
  const without = (patch: Partial<LeadListQuery>) => leadsHref({ ...query, ...patch, page: 1 });
  const chips: FilterChipLink[] = [];
  if (query.q) chips.push({ id: "q", label: `Search: “${query.q}”`, href: without({ q: "" }) });
  for (const status of query.status) {
    const label = LEAD_STATUSES.find((s) => s.value === status)?.label ?? status;
    chips.push({
      id: `status:${status}`,
      label: `Status: ${label}`,
      href: without({ status: query.status.filter((s) => s !== status) }),
    });
  }
  if (query.fit) {
    const label = FIT_FILTERS.find((f) => f.value === query.fit)?.label ?? query.fit;
    chips.push({ id: "fit", label: `Fit: ${label}`, href: without({ fit: "" }) });
  }
  if (query.tagId) {
    chips.push({
      id: "tag",
      label: `Tag: ${lookup.tagName(query.tagId) ?? "selected tag"}`,
      href: without({ tagId: "" }),
    });
  }
  if (query.companyId) {
    chips.push({
      id: "company",
      label: `Company: ${lookup.companyName(query.companyId) ?? "selected company"}`,
      href: without({ companyId: "" }),
    });
  }
  if (query.contactId) {
    chips.push({
      id: "contact",
      label: `Contact: ${lookup.contactName(query.contactId) ?? "selected contact"}`,
      href: without({ contactId: "" }),
    });
  }
  if (query.source) {
    chips.push({ id: "source", label: `Source: ${query.source}`, href: without({ source: "" }) });
  }
  if (query.archived !== "active") {
    const label = ARCHIVED_FILTERS.find((a) => a.value === query.archived)?.label ?? query.archived;
    chips.push({ id: "archived", label, href: without({ archived: "active" }) });
  }
  if (query.overdue) {
    chips.push({ id: "overdue", label: "Overdue next action", href: without({ overdue: false }) });
  }
  if (query.sample) {
    chips.push({
      id: "sample",
      label: query.sample === "only" ? "Sample data only" : "Sample data hidden",
      href: without({ sample: "" }),
    });
  }
  return chips;
}

/** Clear all filters but keep the chosen order. */
export function clearFiltersHref(query: LeadListQuery): string {
  return leadsHref({
    ...parseLeadQuery({}),
    sort: query.sort,
  });
}

/** `datetime-local` value (no zone) -> ISO string, read as UTC like every other date in the app. */
export function localToIso(value: string): string | undefined {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(value)) return undefined;
  const d = new Date(`${value}Z`);
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString();
}
