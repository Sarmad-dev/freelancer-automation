import { firstParam, hrefWith, pageParam, type ContactOut } from "./lead-model";

export const PAGE_SIZE = 25;
export const CONTACTS_PATH = "/leads/contacts";

export const SORT_FIELDS = ["full_name", "email", "updated_at", "created_at"] as const;
export type SortField = (typeof SORT_FIELDS)[number];
export const DEFAULT_SORT = "full_name";

export const ARCHIVED_FILTERS = [
  { value: "active", label: "Active contacts" },
  { value: "archived", label: "Archived only" },
  { value: "all", label: "Active and archived" },
] as const;
export type ArchivedFilter = (typeof ARCHIVED_FILTERS)[number]["value"];

export interface ContactQuery {
  q: string;
  /** A UUID, or "" for any company. */
  companyId: string;
  archived: ArchivedFilter;
  /** Always a valid API sort string (a field, optionally `-` prefixed). */
  sort: string;
  page: number;
}

type RawParams = Record<string, string | string[] | undefined>;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isUuid(value: string): boolean {
  return UUID.test(value);
}

export function isValidSort(sort: string): boolean {
  const field = sort.startsWith("-") ? sort.slice(1) : sort;
  return (SORT_FIELDS as readonly string[]).includes(field);
}

/** Untrusted URL params -> a validated query. Anything unrecognised is dropped, never forwarded to the API. */
export function parseContactQuery(params: RawParams): ContactQuery {
  const company = firstParam(params, "company_id").trim();
  const archived = firstParam(params, "archived");
  const sort = firstParam(params, "sort");
  return {
    q: firstParam(params, "q").trim().slice(0, 100),
    companyId: isUuid(company) ? company.toLowerCase() : "",
    archived: ARCHIVED_FILTERS.find((a) => a.value === archived)?.value ?? "active",
    sort: isValidSort(sort) ? sort : DEFAULT_SORT,
    page: pageParam(params),
  };
}

export function hasContactFilters(query: ContactQuery): boolean {
  return Boolean(query.q || query.companyId || query.archived !== "active");
}

/** Link target for a query (defaults are omitted so URLs stay clean). */
export function contactsHref(query: ContactQuery): string {
  return hrefWith(CONTACTS_PATH, {
    q: query.q,
    company_id: query.companyId,
    archived: query.archived === "active" ? undefined : query.archived,
    sort: query.sort === DEFAULT_SORT ? undefined : query.sort,
    page: query.page,
  });
}

export function pageHref(query: ContactQuery, page: number): string {
  return contactsHref({ ...query, page });
}

/** Query-string parameters for the list API. */
export function apiQuery(query: ContactQuery) {
  return {
    limit: PAGE_SIZE,
    offset: (query.page - 1) * PAGE_SIZE,
    sort: query.sort,
    archived: query.archived,
    ...(query.q ? { q: query.q } : {}),
    ...(query.companyId ? { company_id: query.companyId } : {}),
  };
}

export function sortState(
  query: ContactQuery,
  field: SortField,
): "ascending" | "descending" | "none" {
  if (query.sort === field) return "ascending";
  if (query.sort === `-${field}`) return "descending";
  return "none";
}

/** Text columns start A to Z; dates start with the newest first. */
const ASC_FIRST: readonly SortField[] = ["full_name", "email"];

/** Clicking the active column flips its direction; a new column starts in its natural direction. */
export function sortHref(query: ContactQuery, field: SortField): string {
  const state = sortState(query, field);
  const sort =
    state === "ascending"
      ? `-${field}`
      : state === "descending"
        ? field
        : ASC_FIRST.includes(field)
          ? field
          : `-${field}`;
  return contactsHref({ ...query, sort, page: 1 });
}

export function detailHref(id: string): string {
  return `${CONTACTS_PATH}/${id}`;
}

/* ---------- phone ---------- */

const DIALABLE = /^\+?[0-9 ().-]+$/;

/**
 * A `tel:` link only for a value that is plainly a phone number. Anything else (stored text can be
 * anything) stays plain text, so it can never become a `javascript:` or other odd link.
 */
export function telHref(phone: string | null | undefined): string | null {
  if (!phone) return null;
  const value = phone.trim();
  if (!DIALABLE.test(value)) return null;
  const digits = value.replace(/\D/g, "");
  if (digits.length === 0) return null;
  return `tel:${value.startsWith("+") ? "+" : ""}${digits}`;
}

/**
 * A `mailto:` link only for a plain address. Stored text can be anything, and a `?` or `,` would let it
 * add recipients or a body, so anything beyond a simple `name@host` stays plain text.
 */
export function mailHref(email: string | null | undefined): string | null {
  if (!email) return null;
  const value = email.trim();
  return /^[^\s<>"'`,;?&#%\\()[\]:]+@[^\s<>"'`,;?&#%\\()[\]:@]+$/.test(value)
    ? `mailto:${value}`
    : null;
}

/* ---------- provenance ---------- */

/** "Added manually" for hand-entered contacts, otherwise the recorded source. */
export function isManualSource(source: string | null | undefined): boolean {
  return !source || source.trim().toLowerCase() === "manual";
}

/* ---------- form ---------- */

export interface ContactForm {
  full_name: string;
  email: string;
  role_title: string;
  phone: string;
  /** A company id, or "" for none. */
  company_id: string;
  notes: string;
  source: string;
}

export const FORM_LIMITS = {
  full_name: 200,
  email: 254,
  role_title: 120,
  phone: 40,
  notes: 4000,
  source: 100,
} as const;

export function emptyForm(): ContactForm {
  return {
    full_name: "",
    email: "",
    role_title: "",
    phone: "",
    company_id: "",
    notes: "",
    source: "",
  };
}

export function formFromContact(contact: ContactOut): ContactForm {
  return {
    full_name: contact.full_name,
    email: contact.email ?? "",
    role_title: contact.role_title ?? "",
    phone: contact.phone ?? "",
    company_id: contact.company_id ?? "",
    notes: contact.notes ?? "",
    source: contact.source ?? "",
  };
}

export type ContactCreateBody = {
  full_name: string;
  email?: string;
  role_title?: string;
  phone?: string;
  company_id?: string;
  notes?: string;
  source?: string;
};

const OPTIONAL_TEXT = ["email", "role_title", "phone", "notes", "source"] as const;

/** The create request: only the fields that were filled in. */
export function createBody(form: ContactForm): ContactCreateBody {
  const body: ContactCreateBody = { full_name: form.full_name.trim() };
  for (const key of OPTIONAL_TEXT) {
    const value = form[key].trim();
    if (value) body[key] = value;
  }
  if (form.company_id) body.company_id = form.company_id;
  return body;
}

export type ContactPatchBody = {
  full_name?: string;
  email?: string | null;
  role_title?: string | null;
  phone?: string | null;
  company_id?: string | null;
  notes?: string | null;
  source?: string | null;
};

/** The edit request: only what changed. A blank optional field clears it (`null`). */
export function diffContact(baseline: ContactForm, form: ContactForm): ContactPatchBody {
  const patch: ContactPatchBody = {};
  const name = form.full_name.trim();
  if (name && name !== baseline.full_name.trim()) patch.full_name = name;
  for (const key of OPTIONAL_TEXT) {
    const next = form[key].trim();
    if (next !== baseline[key].trim()) patch[key] = next || null;
  }
  if (form.company_id !== baseline.company_id) patch.company_id = form.company_id || null;
  return patch;
}
