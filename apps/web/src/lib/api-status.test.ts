import { describe, expect, it } from "vitest";
import { fetchApiStatus } from "./api-status";

const ok = { status: "ok" as const };
const json = (body: unknown, status: number) => async () => Response.json(body, { status });

describe("fetchApiStatus", () => {
  it("reports ready", async () => {
    const f = json({ status: "ready", checks: { database: ok, redis: ok } }, 200);
    const s = await fetchApiStatus("http://api.test", f as unknown as typeof fetch);
    expect(s.state).toBe("ready");
  });

  it("reports degraded when a dependency is down (503)", async () => {
    const f = json(
      {
        status: "not_ready",
        checks: { database: ok, redis: { status: "error", detail: "ConnectionError" } },
      },
      503,
    );
    const s = await fetchApiStatus("http://api.test", f as unknown as typeof fetch);
    expect(s.state).toBe("degraded");
  });

  it("reports unreachable on network failure without leaking details", async () => {
    const f = async () => {
      throw new TypeError("connect ECONNREFUSED 10.0.0.1:8000");
    };
    const s = await fetchApiStatus("http://api.test", f as unknown as typeof fetch);
    expect(s).toEqual({ state: "unreachable", reason: "Connection failed" });
  });
});
