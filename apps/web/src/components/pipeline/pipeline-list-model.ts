import { firstParam, hrefWith, pageParam } from "../leads/lead-model";

export const PAGE_SIZE = 25;
export const PIPELINE_PATH = "/pipeline";

export const SORT_FIELDS = [
  "updated_at",
  "created_at",
  "title",
  "value_amount",
  "expected_close_date",
  "probability",
] as const;
export type SortField = (typeof SORT_FIELDS)[number];
export const DEFAULT_SORT = "-updated_at";

export const STATUS_FILTERS = [
  { value: "open", label: "Open" },
  { value: "won", label: "Won" },
  { value: "lost", label: "Lost" },
] as const;
export type StatusFilter = (typeof STATUS_FILTERS)[number]["value"];

export type PipelineView = "board" | "table";

export interface PipelineQuery {
  q: string;
  /** "" = any status. */
  status: StatusFilter | "";
  /** A UUID, or "" for any stage. */
  stageId: string;
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

/** `?view=table` selects the table; anything else is the board. */
export function parseView(params: RawParams): PipelineView {
  return firstParam(params, "view") === "table" ? "table" : "board";
}

/** Untrusted URL params -> a validated query. Anything unrecognised is dropped, never forwarded to the API. */
export function parsePipelineQuery(params: RawParams): PipelineQuery {
  const status = firstParam(params, "status");
  const stage = firstParam(params, "stage_id").trim();
  const sort = firstParam(params, "sort");
  return {
    q: firstParam(params, "q").trim().slice(0, 100),
    status: STATUS_FILTERS.find((s) => s.value === status)?.value ?? "",
    stageId: isUuid(stage) ? stage.toLowerCase() : "",
    sort: isValidSort(sort) ? sort : DEFAULT_SORT,
    page: pageParam(params),
  };
}

export function hasPipelineFilters(query: PipelineQuery): boolean {
  return Boolean(query.q || query.status || query.stageId);
}

export function boardHref(): string {
  return PIPELINE_PATH;
}

/** Link target for the table view (defaults are omitted so URLs stay clean). */
export function tableHref(query: Partial<PipelineQuery> = {}): string {
  return hrefWith(PIPELINE_PATH, {
    view: "table",
    q: query.q,
    status: query.status,
    stage_id: query.stageId,
    sort: query.sort === undefined || query.sort === DEFAULT_SORT ? undefined : query.sort,
    page: query.page,
  });
}

export function pageHref(query: PipelineQuery, page: number): string {
  return tableHref({ ...query, page });
}

/** Query-string parameters for the list API. */
export function apiQuery(query: PipelineQuery) {
  return {
    limit: PAGE_SIZE,
    offset: (query.page - 1) * PAGE_SIZE,
    sort: query.sort,
    ...(query.q ? { q: query.q } : {}),
    ...(query.status ? { status: query.status } : {}),
    ...(query.stageId ? { stage_id: query.stageId } : {}),
  };
}

export function sortState(
  query: Pick<PipelineQuery, "sort">,
  field: SortField,
): "ascending" | "descending" | "none" {
  if (query.sort === field) return "ascending";
  if (query.sort === `-${field}`) return "descending";
  return "none";
}

/** Titles and close dates start soonest / A to Z; everything else starts with the biggest or newest. */
const ASC_FIRST: readonly SortField[] = ["title", "expected_close_date"];

/** Clicking the active column flips its direction; a new column starts in its natural direction. */
export function sortHref(query: PipelineQuery, field: SortField): string {
  const state = sortState(query, field);
  const sort =
    state === "ascending"
      ? `-${field}`
      : state === "descending"
        ? field
        : ASC_FIRST.includes(field)
          ? field
          : `-${field}`;
  return tableHref({ ...query, sort, page: 1 });
}

export function dealHref(id: string): string {
  return `${PIPELINE_PATH}/${id}`;
}
