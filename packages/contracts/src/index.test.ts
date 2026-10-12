import { describe, expect, it, vi } from "vitest";
import { createApiClient, type Page, type PipelineStageOut, type TagOut } from "./index";

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

  it("types list endpoints with the shared pagination envelope and query params", async () => {
    const body = { items: [], total: 0, limit: 10, offset: 0 };
    const fetchMock = vi.fn(async () => Response.json(body));
    const client = createApiClient("http://api.test", {
      fetch: fetchMock as unknown as typeof fetch,
    });
    const { data } = await client.GET("/api/v1/workspaces/{workspace_id}/tags", {
      params: {
        path: { workspace_id: "w1" },
        // `sort` and `q` are part of the generated contract; a typo here fails the type check.
        query: { limit: 10, offset: 0, sort: "-created_at", q: "warm" },
      },
    });
    const page: Page<TagOut> | undefined = data;
    expect(page?.total).toBe(0);
    const request = (fetchMock.mock.calls[0] as unknown as [Request])[0];
    expect(new URL(request.url).search).toBe("?limit=10&offset=0&sort=-created_at&q=warm");
  });

  it("exposes the pipeline stages endpoint", async () => {
    const fetchMock = vi.fn(async () =>
      Response.json({
        items: [{ id: "s1", key: "new", name: "New", position: 0, is_won: false, is_lost: false }],
        total: 1,
        limit: 25,
        offset: 0,
      }),
    );
    const client = createApiClient("http://api.test", {
      fetch: fetchMock as unknown as typeof fetch,
    });
    const { data } = await client.GET("/api/v1/workspaces/{workspace_id}/pipeline/stages", {
      params: { path: { workspace_id: "w1" } },
    });
    const first: PipelineStageOut | undefined = data?.items[0];
    expect(first?.key).toBe("new");
  });
});
