import { describe, expect, it } from "vitest";
import {
  STATUS_BADGE,
  STATUS_TONE,
  actionsFor,
  flashFrom,
  syncSummary,
  when,
  type SyncOut,
} from "./mailbox-model";

describe("flashFrom", () => {
  it("is empty without a result", () => {
    expect(flashFrom({})).toBeNull();
    expect(flashFrom({ email: "something-else" })).toBeNull();
  });

  it("confirms a connection only in terms of the test that succeeded", () => {
    expect(flashFrom({ email: "connected", provider: "gmail" })).toMatchObject({
      tone: "success",
      title: "Mailbox connected",
    });
  });

  it.each([
    ["denied", "warning", /declined/],
    ["insufficient_scopes", "danger", /every permission/],
    ["no_refresh_token", "danger", /ongoing access/],
    ["expired", "danger", /took too long/],
    ["invalid_state", "danger", /already used/],
    ["wrong_user", "danger", /different account/],
    ["not_allowed", "danger", /workspace owner/],
    ["signed_out", "danger", /Sign in/],
    ["exchange_failed", "danger", /refused/],
    ["profile_failed", "danger", /test of the connection failed/],
    ["provider_unavailable", "danger", /not responding/],
  ] as const)("explains %s in plain words", (reason, tone, text) => {
    const flash = flashFrom({ email: "error", reason });
    expect(flash).toMatchObject({ tone, title: "The mailbox was not connected" });
    expect(flash!.text).toMatch(text);
  });

  it("never echoes an unknown reason back into the page", () => {
    const flash = flashFrom({ email: "error", reason: "<script>alert(1)</script>" });
    expect(flash!.text).not.toContain("script");
    expect(flash!.text).toMatch(/Something went wrong/);
  });

  it("reads the first value of a repeated parameter", () => {
    expect(flashFrom({ email: ["connected", "error"] })?.tone).toBe("success");
  });
});

describe("statuses and actions", () => {
  it("shows every status with its own tone and short label", () => {
    expect(Object.keys(STATUS_TONE).sort()).toEqual([
      "connected",
      "demo",
      "disconnected",
      "error",
      "needs_reauth",
    ]);
    expect(STATUS_BADGE.needs_reauth).toBe("Reconnect needed");
    expect(STATUS_TONE.connected).toBe("success");
    expect(STATUS_TONE.needs_reauth).toBe("warning");
    expect(STATUS_TONE.error).toBe("danger");
  });

  it("offers only what makes sense for each state", () => {
    expect(actionsFor({ status: "connected", is_demo: false })).toEqual({
      sync: true,
      test: true,
      reconnect: false,
      disconnect: true,
    });
    expect(actionsFor({ status: "demo", is_demo: true })).toEqual({
      sync: true,
      test: false,
      reconnect: false,
      disconnect: false,
    });
    expect(actionsFor({ status: "needs_reauth", is_demo: false })).toEqual({
      sync: false,
      test: false,
      reconnect: true,
      disconnect: true,
    });
    expect(actionsFor({ status: "disconnected", is_demo: false })).toEqual({
      sync: false,
      test: false,
      reconnect: true,
      disconnect: false,
    });
    expect(actionsFor({ status: "error", is_demo: false }).test).toBe(true);
  });
});

describe("when", () => {
  it("formats deterministically in UTC and says so when it never happened", () => {
    expect(when("2026-10-12T14:05:59Z", "Never")).toBe("2026-10-12 14:05 UTC");
    expect(when(null, "Never")).toBe("Never");
    expect(when("not a date", "Never")).toBe("Never");
  });
});

const sync = (over: Partial<SyncOut>): SyncOut =>
  ({
    account: {} as SyncOut["account"],
    conversations_created: 0,
    messages_created: 0,
    messages_updated: 0,
    skipped: 0,
    pages: 1,
    complete: true,
    rate_limited_until: null,
    error_code: null,
    ...over,
  }) as SyncOut;

describe("syncSummary", () => {
  it("counts what arrived, with correct plurals", () => {
    expect(syncSummary(sync({ messages_created: 6, conversations_created: 3 }))).toEqual({
      tone: "success",
      title: "Sync complete",
      text: "6 new messages in 3 new conversations.",
    });
    expect(syncSummary(sync({ messages_created: 1, conversations_created: 1 })).text).toBe(
      "1 new message in 1 new conversation.",
    );
  });

  it("says when nothing is new", () => {
    expect(syncSummary(sync({}))).toMatchObject({ title: "Up to date", text: "No new messages." });
  });

  it("is honest about an incomplete or interrupted sync", () => {
    expect(
      syncSummary(sync({ complete: false, messages_created: 2, conversations_created: 1 })).title,
    ).toBe("Sync in progress");
    expect(syncSummary(sync({ complete: false, error_code: "rate_limited" }))).toMatchObject({
      tone: "warning",
      title: "Paused by the provider",
    });
    expect(
      syncSummary(sync({ complete: false, error_code: "provider_unavailable" })),
    ).toMatchObject({ tone: "warning", title: "Sync stopped early" });
  });
});
