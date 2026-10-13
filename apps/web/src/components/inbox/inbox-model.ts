import type { components, paths } from "@freelancer-os/contracts";
import type { BadgeTone } from "@freelancer-os/ui";
import { firstParam, hrefWith, pageParam } from "@/components/leads/lead-model";

type Schemas = components["schemas"];
export type ConversationSummary = Schemas["ConversationSummary"];
export type ConversationDetail = Schemas["ConversationDetail"];
export type ThreadMessage = Schemas["ThreadMessage"];
export type ClassificationOut = Schemas["ClassificationOut"];
export type StopOut = Schemas["StopOut"];
export type DraftOut = Schemas["DraftOut"];
export type InboxCounts = Schemas["InboxCounts"];
export type SuggestReplyOut = Schemas["SuggestReplyOut"];
export type ReplyCategory = Schemas["SetClassification"]["category"];

export const INBOX_PATH = "/inbox";
export const PAGE_SIZE = 25;

export const CATEGORIES: readonly ReplyCategory[] = [
  "interested",
  "question",
  "objection",
  "not_now",
  "referral",
  "out_of_office",
  "unsubscribe",
  "irrelevant",
];

export const CATEGORY_LABEL: Record<ReplyCategory, string> = {
  interested: "Interested",
  question: "Question",
  objection: "Objection",
  not_now: "Not now",
  referral: "Referral",
  out_of_office: "Out of office",
  unsubscribe: "Unsubscribe",
  irrelevant: "Irrelevant",
};

export const CATEGORY_TONE: Record<ReplyCategory, BadgeTone> = {
  interested: "success",
  question: "info",
  objection: "warning",
  not_now: "neutral",
  referral: "accent",
  out_of_office: "neutral",
  unsubscribe: "danger",
  irrelevant: "neutral",
};

/** One-line help for each category, shown where a person picks one. */
export const CATEGORY_HELP: Record<ReplyCategory, string> = {
  interested: "They want to talk or hear more.",
  question: "They asked something before deciding.",
  objection: "They gave a reason it may not fit.",
  not_now: "Interested in principle, but not at the moment.",
  referral: "They pointed to someone else.",
  out_of_office: "An automatic away message.",
  unsubscribe: "They asked not to be contacted. They are added to your do-not-contact list.",
  irrelevant: "Nothing here needs a reply.",
};

export type InboxFilter = "" | "unread" | "review" | "unclassified" | ReplyCategory;

export const FILTERS: readonly { value: InboxFilter; label: string }[] = [
  { value: "", label: "All" },
  { value: "unread", label: "Unread" },
  { value: "review", label: "Needs review" },
  ...CATEGORIES.map((c) => ({ value: c as InboxFilter, label: CATEGORY_LABEL[c] })),
  { value: "unclassified", label: "Not classified" },
];
const FILTER_VALUES = new Set<string>(FILTERS.map((f) => f.value));

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export interface InboxQuery {
  q: string;
  filter: InboxFilter;
  /** A mailbox id, or "". */
  account: string;
  page: number;
  /** The conversation open on the right, or "". */
  selected: string;
}

type RawParams = Record<string, string | string[] | undefined>;

/** Everything from the URL is untrusted: unknown values fall back to "everything". */
export function parseInboxQuery(params: RawParams): InboxQuery {
  const filter = firstParam(params, "filter");
  const account = firstParam(params, "account");
  const selected = firstParam(params, "c");
  return {
    q: firstParam(params, "q").trim().slice(0, 100),
    filter: (FILTER_VALUES.has(filter) ? filter : "") as InboxFilter,
    account: UUID.test(account) ? account : "",
    page: pageParam(params),
    selected: UUID.test(selected) ? selected : "",
  };
}

type ListQuery = NonNullable<
  paths["/api/v1/workspaces/{workspace_id}/inbox/conversations"]["get"]["parameters"]["query"]
>;

/** The query string for `GET /inbox/conversations`. */
export function apiQuery(query: InboxQuery): ListQuery {
  const out: ListQuery = {
    limit: PAGE_SIZE,
    offset: (query.page - 1) * PAGE_SIZE,
  };
  if (query.q) out.q = query.q;
  if (query.account) out.account_id = query.account;
  if (query.filter === "unread") out.unread = true;
  else if (query.filter === "review") out.needs_review = true;
  else if (query.filter) out.classification = query.filter;
  return out;
}

/** A link to the inbox with some of the query changed. Changing the search or filter goes back to page one. */
export function inboxHref(query: InboxQuery, patch: Partial<InboxQuery> = {}): string {
  const next = { ...query, ...patch };
  const resets = "q" in patch || "filter" in patch || "account" in patch;
  return hrefWith(INBOX_PATH, {
    q: next.q,
    filter: next.filter,
    account: next.account,
    page: resets && !("page" in patch) ? 1 : next.page,
    c: next.selected,
  });
}

export function hasFilters(query: InboxQuery): boolean {
  return Boolean(query.q || query.filter || query.account);
}

export function sourceLabel(source: ClassificationOut["source"]): string {
  switch (source) {
    case "model":
      return "AI";
    case "demo_ai":
      return "Demo AI: a rule-based stand-in, not a real model";
    case "rules_fallback":
      return "Keyword rules: the AI provider was unavailable";
    case "manual":
      return "Set by you";
    default:
      return "";
  }
}

export function confidenceText(confidence: number | null | undefined): string {
  return confidence === null || confidence === undefined
    ? ""
    : `${Math.round(confidence * 100)}% confident`;
}

/** Who a conversation is with: the contact's name, else the address, else a plain fallback. */
export function counterpartLabel(c: Pick<ConversationSummary, "counterpart">): string {
  return c.counterpart.name || c.counterpart.address || "Unknown sender";
}
