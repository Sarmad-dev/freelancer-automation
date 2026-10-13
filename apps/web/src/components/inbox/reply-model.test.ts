import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApiFailure } from "@/lib/api-client";
import type { DraftOut } from "./inbox-model";
import {
  authorBadge,
  canSend,
  hasInbound,
  isDirty,
  isLocked,
  newIdempotencyKey,
  openDraft,
  replySubject,
  sendProblem,
  sendResult,
  statusBadge,
  suggestProblem,
  waitText,
  warningTexts,
  type SendOut,
} from "./reply-model";

const draft = (over: Partial<DraftOut> = {}): DraftOut => ({
  approval_is_current: false,
  approved_at: null,
  author: "ai",
  body_text: "Hello",
  conversation_id: "c1",
  created_at: "2026-10-12T10:00:00Z",
  email_account_id: "a1",
  facts: [],
  facts_used: [],
  id: "d1",
  lead_id: null,
  message: null,
  send_locked: false,
  sent_at: null,
  status: "draft",
  subject: "Re: Hi",
  to_address: "sam@acme.example",
  updated_at: "2026-10-12T10:00:00Z",
  version: 1,
  ...over,
});

const failure = (over: Partial<ApiFailure>): ApiFailure => ({
  status: 409,
  code: "x",
  message: "Server words.",
  fields: {},
  ...over,
});

afterEach(() => vi.unstubAllGlobals());

describe("replySubject", () => {
  it("prefixes once, case-insensitively", () => {
    expect(replySubject("Quote")).toBe("Re: Quote");
    expect(replySubject("Re: Quote")).toBe("Re: Quote");
    expect(replySubject("re: Quote")).toBe("re: Quote");
    expect(replySubject("RE:Quote")).toBe("RE:Quote");
    expect(replySubject("Research")).toBe("Re: Research");
    expect(replySubject("  Quote ")).toBe("Re: Quote");
  });
  it("copes with no subject", () => {
    expect(replySubject(null)).toBe("Re: (no subject)");
    expect(replySubject("  ")).toBe("Re: (no subject)");
  });
});

describe("badges", () => {
  it("tells a current approval from a withdrawn one", () => {
    expect(statusBadge(draft({ status: "approved", approval_is_current: true })).label).toBe(
      "Approved",
    );
    expect(statusBadge(draft({ status: "approved", approval_is_current: false })).label).toBe(
      "Approval withdrawn",
    );
    expect(statusBadge(draft()).label).toBe("Draft");
    expect(statusBadge(draft({ status: "pending_approval" })).label).toBe("Draft");
    expect(statusBadge(draft({ status: "sent" })).label).toBe("Sent");
  });
  it("names the author", () => {
    expect(authorBadge({ author: "ai" }).label).toBe("AI draft: check every line");
    expect(authorBadge({ author: "user" }).label).toBe("Written by you");
  });
});

describe("warningTexts", () => {
  it("turns known codes into words, keeps review: text, and ignores the rest", () => {
    expect(
      warningTexts([
        "injection_suspected",
        "placeholder_in_draft",
        "no_facts_cited",
        "review:  Check the price. ",
        "mystery_code",
        "review:",
        "no_facts_cited",
      ]),
    ).toEqual([
      "The message you're answering contained text that tries to instruct the AI. Read this draft carefully.",
      "The draft has a placeholder to fill in before sending.",
      "The draft doesn't cite any approved fact.",
      "Check the price.",
    ]);
    expect(warningTexts([])).toEqual([]);
  });
});

describe("draft helpers", () => {
  it("hides a discarded draft", () => {
    expect(openDraft(null)).toBeNull();
    expect(openDraft(draft({ status: "discarded" }))).toBeNull();
    expect(openDraft(draft())?.id).toBe("d1");
  });
  it("finds an inbound message", () => {
    expect(hasInbound({ messages: [] })).toBe(false);
    expect(hasInbound({ messages: [{ direction: "outbound" }] as never })).toBe(false);
    expect(hasInbound({ messages: [{ direction: "inbound" }] as never })).toBe(true);
  });
  it("notices edits", () => {
    expect(isDirty(draft(), "Re: Hi", "Hello")).toBe(false);
    expect(isDirty(draft(), "Re: Hi!", "Hello")).toBe(true);
    expect(isDirty(draft(), "Re: Hi", "Hello there")).toBe(true);
  });
  it("locks while a send is running or unknown", () => {
    const message = (delivery_state: string) => ({ delivery_state }) as never;
    expect(isLocked(draft())).toBe(false);
    expect(isLocked(draft({ send_locked: true }))).toBe(true);
    expect(isLocked(draft({ message: message("queued") }))).toBe(true);
    expect(isLocked(draft({ message: message("unknown") }))).toBe(true);
    expect(isLocked(draft({ message: message("failed") }))).toBe(false);
  });
  it("sends only a current, unedited, unlocked approval", () => {
    const ok = draft({ status: "approved", approval_is_current: true });
    expect(canSend(ok, false)).toBe(true);
    expect(canSend(ok, true)).toBe(false);
    expect(canSend(draft({ status: "approved", approval_is_current: false }), false)).toBe(false);
    expect(canSend(draft(), false)).toBe(false);
    expect(canSend({ ...ok, send_locked: true }, false)).toBe(false);
  });
});

describe("newIdempotencyKey", () => {
  it("is a valid key every time", () => {
    const a = newIdempotencyKey();
    expect(a).toMatch(/^[A-Za-z0-9._:-]{8,100}$/);
    expect(newIdempotencyKey()).not.toBe(a);
  });
  it("falls back when randomUUID is missing", () => {
    vi.stubGlobal("crypto", { getRandomValues: (a: Uint8Array) => a.fill(7) });
    expect(newIdempotencyKey()).toMatch(/^[A-Za-z0-9._:-]{8,100}$/);
  });
  it("falls back when there is no crypto at all", () => {
    vi.stubGlobal("crypto", undefined);
    const a = newIdempotencyKey();
    expect(a).toMatch(/^[A-Za-z0-9._:-]{8,100}$/);
    expect(newIdempotencyKey()).not.toBe(a);
  });
});

describe("sendResult", () => {
  const out = (state: string | null, replayed = false): SendOut => ({
    replayed,
    draft: draft({
      status: "sent",
      message: state ? ({ delivery_state: state, delivery_label: "Label." } as never) : null,
    }),
  });
  it("orders the outcomes by what matters most", () => {
    expect(sendResult(out("sent"), 201)).toEqual({ kind: "sent" });
    expect(sendResult(out("demo"), 201)).toEqual({ kind: "demo" });
    expect(sendResult(out("sent", true), 200)).toEqual({ kind: "replayed" });
    expect(sendResult(out("queued"), 201)).toEqual({ kind: "queued" });
    expect(sendResult(out("unknown"), 201)).toEqual({ kind: "unknown" });
    expect(sendResult(out("sent"), 202)).toEqual({ kind: "unknown" });
    expect(sendResult(out("failed"), 201)).toEqual({ kind: "failed", label: "Label." });
    expect(sendResult(out(null), 201)).toEqual({ kind: "sent" });
  });
});

describe("waitText", () => {
  it("speaks plainly", () => {
    expect(waitText(undefined)).toBe("a little while");
    expect(waitText(30)).toBe("30 seconds");
    expect(waitText(60)).toBe("about a minute");
    expect(waitText(150)).toBe("about 3 minutes");
  });
});

describe("sendProblem", () => {
  it("explains a suppressed recipient and refreshes", () => {
    const p = sendProblem(failure({ code: "recipient_suppressed" }));
    expect(p.text).toContain("do-not-contact list");
    expect(p).toMatchObject({ refresh: true, blocked: true, reconnect: false });
  });
  it.each(["draft_changed", "draft_not_approved", "already_sent", "send_outcome_unknown"])(
    "refreshes and blocks on %s",
    (code) => {
      expect(sendProblem(failure({ code }))).toMatchObject({
        refresh: true,
        blocked: true,
        text: "Server words.",
      });
    },
  );
  it("offers reconnecting", () => {
    expect(sendProblem(failure({ code: "reconnect_required" }))).toMatchObject({
      reconnect: true,
      refresh: false,
      blocked: false,
    });
  });
  it("asks to wait on rate limits", () => {
    for (const code of ["send_rate_limited", "rate_limited", "something_else"]) {
      const p = sendProblem(failure({ status: 429, code, retryAfter: 120 }));
      expect(p.text).toBe("Server words. Please wait about 2 minutes before trying again.");
      expect(p.blocked).toBe(false);
    }
  });
  it("says retrying a lost connection is safe", () => {
    const p = sendProblem(failure({ status: 0, code: "network_error" }));
    expect(p.text).toContain("Trying again is safe");
  });
  it("passes other messages through", () => {
    for (const code of [
      "send_in_progress",
      "idempotency_key_conflict",
      "provider_not_configured",
      "provider_rejected",
      "provider_unavailable",
    ]) {
      expect(sendProblem(failure({ code, status: 503 }))).toMatchObject({
        text: "Server words.",
        refresh: false,
      });
    }
  });
});

describe("suggestProblem", () => {
  it("links to the AI Workspace only when context is missing", () => {
    expect(suggestProblem(failure({ code: "insufficient_context", status: 422 }))).toMatchObject({
      addFacts: true,
      refresh: false,
    });
    expect(suggestProblem(failure({ code: "contact_stopped" }))).toMatchObject({
      addFacts: false,
      refresh: true,
    });
    expect(suggestProblem(failure({ code: "ai_unavailable" }))).toMatchObject({
      addFacts: false,
      refresh: false,
    });
  });
});
