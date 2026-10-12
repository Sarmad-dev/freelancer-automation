import { describe, expect, it } from "vitest";
import { isPublicPath } from "./auth-constants";
import { buildUpstreamPath, pickRequestHeaders, pickResponseHeaders } from "./api-proxy";

describe("buildUpstreamPath", () => {
  it("allows only the auth and workspaces API areas", () => {
    expect(buildUpstreamPath(["auth", "me"])).toBe("/api/v1/auth/me");
    expect(buildUpstreamPath(["workspaces", "abc", "onboarding", "step"])).toBe(
      "/api/v1/workspaces/abc/onboarding/step",
    );
    expect(buildUpstreamPath(["admin"])).toBeNull();
    expect(buildUpstreamPath(["docs"])).toBeNull();
    expect(buildUpstreamPath([])).toBeNull();
  });

  it.each([
    [["auth", "..", "..", "ready"]],
    [["auth", "."]],
    [["auth", ""]],
    [["auth", "a/b"]],
    [["auth", "a\\b"]],
    [["auth", "a\u0000b"]],
  ])("rejects traversal and separators %j", (segments) => {
    expect(buildUpstreamPath(segments)).toBeNull();
  });

  it("percent-encodes odd characters instead of passing them through", () => {
    expect(buildUpstreamPath(["auth", "a b?x=1#y"])).toBe("/api/v1/auth/a%20b%3Fx%3D1%23y");
  });
});

describe("header filtering", () => {
  it("forwards only the allow-listed request headers", () => {
    const out = pickRequestHeaders(
      new Headers({
        cookie: "fos_session=abc",
        origin: "http://localhost:3000",
        "x-requested-with": "freelancer-os",
        "content-type": "application/json",
        authorization: "Bearer should-not-pass",
        host: "evil.example",
        "x-forwarded-host": "evil.example",
        connection: "keep-alive",
      }),
    );
    expect([...out.keys()].sort()).toEqual([
      "content-type",
      "cookie",
      "origin",
      "x-requested-with",
    ]);
  });

  it("forwards every Set-Cookie and forces no-store", () => {
    const upstream = new Headers({
      "content-type": "application/json",
      "retry-after": "30",
      "content-disposition": 'attachment; filename="leads.csv"',
      "x-powered-by": "x",
    });
    upstream.append("set-cookie", "a=1; Path=/; HttpOnly");
    upstream.append("set-cookie", "b=2; Path=/; HttpOnly");
    const out = pickResponseHeaders(upstream);
    expect(out.getSetCookie()).toEqual(["a=1; Path=/; HttpOnly", "b=2; Path=/; HttpOnly"]);
    expect(out.get("cache-control")).toBe("no-store");
    expect(out.get("retry-after")).toBe("30");
    expect(out.get("content-disposition")).toBe('attachment; filename="leads.csv"');
    expect(out.has("x-powered-by")).toBe(false);
  });
});

describe("isPublicPath", () => {
  it.each([
    "/sign-in",
    "/sign-up",
    "/forgot-password",
    "/reset-password",
    "/api/health",
    "/api/v1/auth/me",
  ])("%s is public", (p) => expect(isPublicPath(p)).toBe(true));
  it.each([
    "/",
    "/leads",
    "/onboarding",
    "/settings",
    "/sign-in-evil",
    "/design-system",
    "/api/other",
  ])("%s requires a session", (p) => expect(isPublicPath(p)).toBe(false));
});
