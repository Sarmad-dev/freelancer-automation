import createClient from "openapi-fetch";
import type { components, paths } from "./generated/api";

export type { components, paths };
export type HealthResponse = components["schemas"]["HealthResponse"];
export type ReadinessResponse = components["schemas"]["ReadinessResponse"];
export type MeResponse = components["schemas"]["MeResponse"];
export type WorkspaceOut = components["schemas"]["WorkspaceOut"];
export type OnboardingState = components["schemas"]["OnboardingState"];
export type ErrorBody = components["schemas"]["ErrorBody"];

/**
 * Typed API client. The types are generated from the FastAPI OpenAPI document
 * (`pnpm contracts:generate`); CI fails if the committed output is stale.
 */
export function createApiClient(
  baseUrl: string,
  init?: { fetch?: typeof fetch; headers?: Record<string, string> },
) {
  return createClient<paths>({
    baseUrl,
    ...(init?.fetch ? { fetch: init.fetch } : {}),
    ...(init?.headers ? { headers: init.headers } : {}),
  });
}
