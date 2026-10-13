import type { components } from "@freelancer-os/contracts";
import type { BadgeTone } from "@freelancer-os/ui";
import type { ApiFailure } from "@/lib/api-client";
import type { ConversationDetail, DraftOut } from "./inbox-model";

export type SendOut = components["schemas"]["SendOut"];

export const KNOWLEDGE_HREF = "/ai-workspace/knowledge";
export const INTEGRATIONS_HREF = "/integrations";
export const BODY_MAX = 20000;

/** Drafts a person can still work on. `sent` is shown read-only; `discarded` counts as no draft. */
const EDITABLE = new Set<DraftOut["status"]>(["draft", "pending_approval", "approved", "rejected"]);

export function isEditable(draft: Pick<DraftOut, "status">): boolean {
  return EDITABLE.has(draft.status);
}

/** The draft the editor works with: a discarded draft is the same as none. */
export function openDraft(draft: DraftOut | null | undefined): DraftOut | null {
  return draft && draft.status !== "discarded" ? draft : null;
}

export function hasInbound(thread: Pick<ConversationDetail, "messages">): boolean {
  return thread.messages.some((m) => m.direction === "inbound");
}

/** "Re: Hello" for "Hello"; an existing "Re:" is not doubled. */
export function replySubject(subject: string | null | undefined): string {
  const s = (subject ?? "").trim();
  if (!s) return "Re: (no subject)";
  return /^re:/i.test(s) ? s : `Re: ${s}`;
}

export function statusBadge(draft: Pick<DraftOut, "status" | "approval_is_current">): {
  label: string;
  tone: BadgeTone;
} {
  switch (draft.status) {
    case "approved":
      return draft.approval_is_current
        ? { label: "Approved", tone: "success" }
        : { label: "Approval withdrawn", tone: "warning" };
    case "sent":
      return { label: "Sent", tone: "success" };
    case "rejected":
      return { label: "Rejected", tone: "warning" };
    case "discarded":
      return { label: "Discarded", tone: "neutral" };
    default:
      return { label: "Draft", tone: "neutral" };
  }
}

export function authorBadge(draft: Pick<DraftOut, "author">): { label: string; tone: BadgeTone } {
  return draft.author === "ai"
    ? { label: "AI draft: check every line", tone: "info" }
    : { label: "Written by you", tone: "neutral" };
}

const WARNING_TEXT: Record<string, string> = {
  injection_suspected:
    "The message you're answering contained text that tries to instruct the AI. Read this draft carefully.",
  placeholder_in_draft: "The draft has a placeholder to fill in before sending.",
  no_facts_cited: "The draft doesn't cite any approved fact.",
};

/** Suggestion warnings in plain words. Unknown codes are ignored; `review:` carries its own text. */
export function warningTexts(warnings: readonly string[]): string[] {
  const out: string[] = [];
  for (const w of warnings) {
    const known = WARNING_TEXT[w];
    const text = known ?? (w.startsWith("review:") ? w.slice("review:".length).trim() : "");
    if (text && !out.includes(text)) out.push(text);
  }
  return out;
}

export function isDirty(
  draft: Pick<DraftOut, "subject" | "body_text">,
  subject: string,
  body: string,
) {
  return subject !== draft.subject || body !== draft.body_text;
}

/** A send has started or its outcome is unknown: nothing about the draft may change. */
export function isLocked(draft: Pick<DraftOut, "send_locked" | "message">): boolean {
  const state = draft.message?.delivery_state;
  return draft.send_locked || state === "queued" || state === "unknown";
}

export function canSend(
  draft: Pick<DraftOut, "status" | "approval_is_current" | "send_locked" | "message">,
  dirty: boolean,
): boolean {
  return draft.status === "approved" && draft.approval_is_current && !dirty && !isLocked(draft);
}

/** One key per send dialog session: retries reuse it, so the server can never send twice. */
export function newIdempotencyKey(): string {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  const alphabet = "abcdefghijklmnopqrstuvwxyz0123456789";
  let out = "key-";
  for (let i = 0; i < 24; i += 1) {
    const n =
      c && typeof c.getRandomValues === "function"
        ? c.getRandomValues(new Uint8Array(1))[0]!
        : Math.floor(Math.random() * 256);
    out += alphabet[n % alphabet.length];
  }
  return out;
}

export type SendResult =
  | { kind: "sent" | "demo" | "replayed" | "queued" }
  | { kind: "unknown" }
  | { kind: "failed"; label: string };

/** What a successful call to `/send` means, in the order that matters most to the person. */
export function sendResult(out: SendOut, status: number): SendResult {
  const state = out.draft.message?.delivery_state;
  if (status === 202 || state === "unknown") return { kind: "unknown" };
  if (state === "failed") {
    return {
      kind: "failed",
      label: out.draft.message?.delivery_label || "The message wasn't sent.",
    };
  }
  if (out.replayed) return { kind: "replayed" };
  if (state === "demo") return { kind: "demo" };
  if (state === "queued") return { kind: "queued" };
  return { kind: "sent" };
}

/** "about 2 minutes", for a Retry-After in seconds. */
export function waitText(seconds: number | undefined): string {
  if (!seconds || seconds <= 0) return "a little while";
  if (seconds < 60) return `${Math.ceil(seconds)} seconds`;
  const minutes = Math.ceil(seconds / 60);
  return minutes === 1 ? "about a minute" : `about ${minutes} minutes`;
}

export interface SendProblem {
  text: string;
  /** Offer a link to the integrations page. */
  reconnect: boolean;
  /** The draft or contact changed on the server: reload what the page shows. */
  refresh: boolean;
  /** Retrying this exact send can't help; only Cancel makes sense. */
  blocked: boolean;
}

/** The text and follow-up for each way `/send` can refuse. */
export function sendProblem(f: ApiFailure): SendProblem {
  const base: SendProblem = { text: f.message, reconnect: false, refresh: false, blocked: false };
  switch (f.code) {
    case "network_error":
      return {
        ...base,
        text: `${f.message} Trying again is safe: the same request can't send the message twice.`,
      };
    case "recipient_suppressed":
      return {
        ...base,
        text: `${f.message} This person is on your do-not-contact list, so nothing was sent.`,
        refresh: true,
        blocked: true,
      };
    case "draft_changed":
    case "draft_not_approved":
    case "already_sent":
    case "send_outcome_unknown":
      return { ...base, refresh: true, blocked: true };
    case "reconnect_required":
      return { ...base, reconnect: true };
    case "send_rate_limited":
    case "rate_limited":
      return {
        ...base,
        text: `${f.message} Please wait ${waitText(f.retryAfter)} before trying again.`,
      };
    default:
      return f.status === 429
        ? {
            ...base,
            text: `${f.message} Please wait ${waitText(f.retryAfter)} before trying again.`,
          }
        : base;
  }
}

export interface SuggestProblem {
  text: string;
  /** Link to the AI Workspace: the server needs more approved facts. */
  addFacts: boolean;
  refresh: boolean;
}

export function suggestProblem(f: ApiFailure): SuggestProblem {
  return {
    text: f.message,
    addFacts: f.code === "insufficient_context",
    refresh: f.code === "contact_stopped",
  };
}
