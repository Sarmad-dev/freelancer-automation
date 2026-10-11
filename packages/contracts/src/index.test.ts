import { describe, expect, it, vi } from "vitest";
import { createApiClient } from "./index";

describe("createApiClient", () => {
  it("calls the typed /health endpoint", async () => {
    const body = {
      status: "ok",
      service: "freelancer-os-api",
      version: "0.0.0",
      environment: "test",
    };
    const fetchMock = vi.fn(async () => Response.json(body));
    const client = createApiClient("http://api.test", {
      fetch: fetchMock as unknown as typeof fetch,
    });
    const { data, error } = await client.GET("/health");
    expect(error).toBeUndefined();
    expect(data?.status).toBe("ok");
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});
