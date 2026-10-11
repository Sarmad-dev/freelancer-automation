import { createApiClient, type ReadinessResponse } from "@freelancer-os/contracts";

export type ApiStatus =
  | { state: "ready"; checks: ReadinessResponse["checks"] }
  | { state: "degraded"; checks: ReadinessResponse["checks"] }
  | { state: "unreachable"; reason: string };

/** Server-side connectivity check against the API readiness endpoint. */
export async function fetchApiStatus(
  baseUrl: string,
  fetchImpl: typeof fetch = fetch,
  timeoutMs = 2500,
): Promise<ApiStatus> {
  const client = createApiClient(baseUrl, {
    fetch: ((input: Request) => fetchImpl(input, { cache: "no-store" })) as typeof fetch,
  });
  try {
    const { data, error, response } = await client.GET("/ready", {
      signal: AbortSignal.timeout(timeoutMs),
    });
    const body = data ?? (error as ReadinessResponse | undefined);
    if (body && "checks" in body) {
      return { state: response.ok ? "ready" : "degraded", checks: body.checks };
    }
    return { state: "unreachable", reason: `Unexpected response (HTTP ${response.status})` };
  } catch (err) {
    const reason =
      err instanceof Error && err.name === "TimeoutError" ? "Timed out" : "Connection failed";
    return { state: "unreachable", reason };
  }
}
