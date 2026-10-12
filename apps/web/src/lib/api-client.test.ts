import { describe, expect, it } from "vitest";
import { describeRateLimit, isSessionLost, toFailure } from "./api-client";

const res = (status: number, headers: Record<string, string> = {}) =>
  new Response(null, { status, headers });

describe("toFailure", () => {
  it("maps the API error envelope", () => {
    const f = toFailure(
      {
        error: {
          code: "validation_error",
          message: "Some fields are invalid.",
          fields: { email: "Bad" },
        },
      },
      res(422),
    );
    expect(f).toMatchObject({ status: 422, code: "validation_error", fields: { email: "Bad" } });
  });

  it("reads Retry-After and produces a friendly rate-limit message", () => {
    const f = toFailure(
      { error: { code: "rate_limited", message: "x" } },
      res(429, { "retry-after": "125" }),
    );
    expect(f.retryAfter).toBe(125);
    expect(describeRateLimit(f)).toBe("Too many attempts. Try again in 3 minutes.");
    expect(describeRateLimit({ ...f, retryAfter: 20 })).toContain("20 seconds");
  });

  it("falls back to safe generic copy without leaking details", () => {
    expect(toFailure(undefined, res(500)).message).toMatch(/temporarily unavailable/);
    expect(toFailure("<html>boom</html>", res(502)).message).not.toContain("boom");
  });

  it("treats a missing response as a network failure", () => {
    expect(toFailure(undefined)).toMatchObject({ status: 0, code: "network_error" });
  });

  it("detects lost sessions", () => {
    expect(
      isSessionLost(toFailure({ error: { code: "session_expired", message: "" } }, res(401))),
    ).toBe(true);
    expect(
      isSessionLost(toFailure({ error: { code: "invalid_credentials", message: "" } }, res(401))),
    ).toBe(false);
  });
});
