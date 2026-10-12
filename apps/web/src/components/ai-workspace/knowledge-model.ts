import type { components } from "@freelancer-os/contracts";
import type { BadgeTone } from "@freelancer-os/ui";

export type KnowledgeOut = components["schemas"]["KnowledgeOut"];
export type KnowledgeVersionOut = components["schemas"]["KnowledgeVersionOut"];

export const PAGE_SIZE = 20;

export const KINDS = [
  { value: "fact", label: "Fact" },
  { value: "service", label: "Service" },
  { value: "case_study", label: "Case study" },
  { value: "portfolio", label: "Portfolio" },
  { value: "pricing", label: "Pricing" },
  { value: "other", label: "Other" },
] as const;
export type Kind = (typeof KINDS)[number]["value"];

export const STATUSES = [
  { value: "pending_review", label: "Needs review", tone: "warning" },
  { value: "draft", label: "Draft", tone: "neutral" },
  { value: "approved", label: "Approved", tone: "success" },
  { value: "rejected", label: "Rejected", tone: "danger" },
] as const satisfies readonly { value: string; label: string; tone: BadgeTone }[];
export type Status = (typeof STATUSES)[number]["value"];

export const SOURCE_LABELS: Record<string, string> = {
  manual: "Written by you",
  upload: "Imported",
  extracted: "Extracted",
};

export function kindLabel(kind: string): string {
  return KINDS.find((k) => k.value === kind)?.label ?? "Other";
}

export function statusMeta(status: string): { label: string; tone: BadgeTone } {
  return STATUSES.find((s) => s.value === status) ?? { label: "Unknown", tone: "neutral" };
}

export interface KnowledgeQuery {
  status: Status | "";
  kind: Kind | "";
  q: string;
  page: number;
}

type RawParams = Record<string, string | string[] | undefined>;

function first(v: string | string[] | undefined): string {
  return (Array.isArray(v) ? v[0] : v) ?? "";
}

/** Untrusted URL params -> a validated query. Anything unrecognised is dropped, never forwarded to the API. */
export function parseQuery(params: RawParams): KnowledgeQuery {
  const status = first(params.status);
  const kind = first(params.kind);
  const page = Number.parseInt(first(params.page), 10);
  return {
    status: STATUSES.some((s) => s.value === status) ? (status as Status) : "",
    kind: KINDS.some((k) => k.value === kind) ? (kind as Kind) : "",
    q: first(params.q).trim().slice(0, 100),
    page: Number.isFinite(page) && page >= 1 && page <= 10_000 ? page : 1,
  };
}

/** Link target for a query (defaults are omitted so URLs stay clean). */
export function queryHref(query: KnowledgeQuery): string {
  const sp = new URLSearchParams();
  if (query.status) sp.set("status", query.status);
  if (query.kind) sp.set("kind", query.kind);
  if (query.q) sp.set("q", query.q);
  if (query.page > 1) sp.set("page", String(query.page));
  const qs = sp.toString();
  return qs ? `/ai-workspace/knowledge?${qs}` : "/ai-workspace/knowledge";
}

export interface ItemForm {
  kind: Kind;
  title: string;
  content: string;
  source_ref: string;
}

export function formFromItem(item: KnowledgeOut): ItemForm {
  return {
    kind: KINDS.some((k) => k.value === item.kind) ? (item.kind as Kind) : "other",
    title: item.title,
    content: item.content,
    source_ref: item.source_ref ?? "",
  };
}

export function emptyForm(): ItemForm {
  return { kind: "fact", title: "", content: "", source_ref: "" };
}

/** Only changed fields are sent. A cleared source reference is sent as null. */
export function diffItem(
  base: ItemForm,
  next: ItemForm,
): { kind?: Kind; title?: string; content?: string; source_ref?: string | null } {
  const patch: ReturnType<typeof diffItem> = {};
  if (base.kind !== next.kind) patch.kind = next.kind;
  if (base.title !== next.title) patch.title = next.title;
  if (base.content !== next.content) patch.content = next.content;
  if (base.source_ref !== next.source_ref) patch.source_ref = next.source_ref.trim() || null;
  return patch;
}
