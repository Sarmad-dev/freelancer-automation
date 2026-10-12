import {
  COMPANY_SIZES,
  firstParam,
  hrefWith,
  pageParam,
  type CompanyOut,
  type CompanySize,
} from "./lead-model";

export type { CompanyOut };

export const PAGE_SIZE = 25;
export const COMPANIES_PATH = "/leads/companies";

export const SORT_FIELDS = ["name", "industry", "updated_at", "created_at"] as const;
export type SortField = (typeof SORT_FIELDS)[number];
export const DEFAULT_SORT = "name";

export const ARCHIVED_FILTERS = [
  { value: "active", label: "Active companies" },
  { value: "archived", label: "Archived only" },
  { value: "all", label: "Active and archived" },
] as const;
export type ArchivedFilter = (typeof ARCHIVED_FILTERS)[number]["value"];

export interface CompanyQuery {
  q: string;
  industry: string;
  size: CompanySize | "";
  archived: ArchivedFilter;
  /** Always a valid API sort string (a field, optionally `-` prefixed). */
  sort: string;
  page: number;
}

type RawParams = Record<string, string | string[] | undefined>;

export function isValidSort(sort: string): boolean {
  const field = sort.startsWith("-") ? sort.slice(1) : sort;
  return (SORT_FIELDS as readonly string[]).includes(field);
}

/** Untrusted URL params -> a validated query. Anything unrecognised is dropped, never forwarded to the API. */
export function parseCompanyQuery(params: RawParams): CompanyQuery {
  const size = firstParam(params, "size_label");
  const archived = firstParam(params, "archived");
  const sort = firstParam(params, "sort");
  return {
    q: firstParam(params, "q").trim().slice(0, 100),
    industry: firstParam(params, "industry").trim().slice(0, 100),
    size: COMPANY_SIZES.some((s) => s.value === size) ? (size as CompanySize) : "",
    archived: ARCHIVED_FILTERS.some((a) => a.value === archived)
      ? (archived as ArchivedFilter)
      : "active",
    sort: isValidSort(sort) ? sort : DEFAULT_SORT,
    page: pageParam(params),
  };
}

export function hasFilters(query: CompanyQuery): boolean {
  return Boolean(query.q || query.industry || query.size || query.archived !== "active");
}

function pairs(query: CompanyQuery, withPage: boolean) {
  return {
    q: query.q,
    industry: query.industry,
    size_label: query.size,
    archived: query.archived === "active" ? undefined : query.archived,
    sort: query.sort === DEFAULT_SORT ? undefined : query.sort,
    ...(withPage ? { page: query.page } : {}),
  };
}

/** Link target for a query (defaults are omitted so URLs stay clean). */
export function companiesHref(query: CompanyQuery): string {
  return hrefWith(COMPANIES_PATH, pairs(query, true));
}

export function pageHref(query: CompanyQuery, page: number): string {
  return companiesHref({ ...query, page });
}

/** The same filters with the filters cleared but the sort kept. */
export function clearFiltersHref(query: CompanyQuery): string {
  return companiesHref({ ...query, q: "", industry: "", size: "", archived: "active", page: 1 });
}

export function sortState(
  query: CompanyQuery,
  field: SortField,
): "ascending" | "descending" | "none" {
  if (query.sort === field) return "ascending";
  if (query.sort === `-${field}`) return "descending";
  return "none";
}

/** Clicking a header sorts by it; clicking the active one flips direction. Always back to page 1. */
export function sortHref(query: CompanyQuery, field: SortField): string {
  const state = sortState(query, field);
  const dateFirst = field === "updated_at" || field === "created_at";
  const next =
    state === "none"
      ? dateFirst
        ? `-${field}`
        : field
      : state === "ascending"
        ? `-${field}`
        : field;
  return companiesHref({ ...query, sort: next, page: 1 });
}

/** The query the API accepts for this list. */
export function apiQuery(query: CompanyQuery) {
  return {
    limit: PAGE_SIZE,
    offset: (query.page - 1) * PAGE_SIZE,
    archived: query.archived,
    sort: query.sort,
    ...(query.q ? { q: query.q } : {}),
    ...(query.industry ? { industry: query.industry } : {}),
    ...(query.size ? { size_label: query.size } : {}),
  };
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export function isUuid(value: string): boolean {
  return UUID.test(value);
}

/* ---------- Form ---------- */

export interface CompanyForm {
  name: string;
  website: string;
  industry: string;
  size_label: CompanySize | "";
  location: string;
  notes: string;
}

export function emptyCompanyForm(): CompanyForm {
  return { name: "", website: "", industry: "", size_label: "", location: "", notes: "" };
}

export function formFromCompany(c: CompanyOut): CompanyForm {
  return {
    name: c.name,
    website: c.website ?? "",
    industry: c.industry ?? "",
    size_label: COMPANY_SIZES.some((s) => s.value === c.size_label)
      ? (c.size_label as CompanySize)
      : "",
    location: c.location ?? "",
    notes: c.notes ?? "",
  };
}

const OPTIONAL_TEXT = ["website", "industry", "location", "notes"] as const;

/** Client-side checks that mirror the API's, so the obvious mistake is caught before a round trip. */
export function validateCompanyForm(form: CompanyForm): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!form.name.trim()) errors.name = "Enter the company's name.";
  return errors;
}

export interface CompanyCreateBody {
  name: string;
  website?: string;
  industry?: string;
  size_label?: CompanySize;
  location?: string;
  notes?: string;
}

/** Only the fields that were filled in are sent. */
export function createBody(form: CompanyForm): CompanyCreateBody {
  const body: CompanyCreateBody = { name: form.name.trim() };
  for (const key of OPTIONAL_TEXT) {
    const value = form[key].trim();
    if (value) body[key] = value;
  }
  if (form.size_label) body.size_label = form.size_label;
  return body;
}

export interface CompanyPatchBody {
  name?: string;
  website?: string | null;
  industry?: string | null;
  size_label?: CompanySize | null;
  location?: string | null;
  notes?: string | null;
}

/** Only changed fields are sent. A blank optional field is sent as null (it clears); a name is never cleared. */
export function diffCompany(base: CompanyForm, next: CompanyForm): CompanyPatchBody {
  const patch: CompanyPatchBody = {};
  if (next.name.trim() && base.name.trim() !== next.name.trim()) patch.name = next.name.trim();
  for (const key of OPTIONAL_TEXT) {
    if (base[key].trim() !== next[key].trim()) patch[key] = next[key].trim() || null;
  }
  if (base.size_label !== next.size_label) patch.size_label = next.size_label || null;
  return patch;
}

/* ---------- Provenance ---------- */

export function provenance(c: Pick<CompanyOut, "source" | "source_retrieved_at">): {
  manual: boolean;
  source: string | null;
  retrievedAt: string | null;
} {
  const source = c.source?.trim() || null;
  const manual = !source || source === "manual";
  return {
    manual,
    source: manual ? null : source,
    retrievedAt: manual ? null : c.source_retrieved_at,
  };
}
