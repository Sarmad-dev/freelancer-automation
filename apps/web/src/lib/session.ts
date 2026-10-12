import "server-only";
import { cookies } from "next/headers";
import { createApiClient, type MeResponse } from "@freelancer-os/contracts";
import { getEnv } from "@/env";
import { SESSION_COOKIE_NAMES } from "./auth-constants";

export type SessionResult =
  | { status: "authenticated"; me: MeResponse }
  | { status: "anonymous" }
  | { status: "expired" }
  | { status: "unavailable" };

/**
 * Authoritative server-side session check: asks the API who the cookie belongs to.
 * (The proxy only does a cheap "is there a cookie" check; this is the real gate.)
 */
export async function getSession(): Promise<SessionResult> {
  const jar = await cookies();
  const cookie = SESSION_COOKIE_NAMES.map((n) => {
    const v = jar.get(n)?.value;
    return v ? `${n}=${v}` : null;
  }).find(Boolean);
  if (!cookie) return { status: "anonymous" };

  const client = createApiClient(getEnv().API_URL, {
    headers: { cookie },
    fetch: ((req: Request) =>
      fetch(req, { cache: "no-store", signal: AbortSignal.timeout(5000) })) as typeof fetch,
  });
  try {
    const { data, error, response } = await client.GET("/api/v1/auth/me");
    if (data) return { status: "authenticated", me: data };
    if (response.status === 401) {
      return error?.error.code === "session_expired"
        ? { status: "expired" }
        : { status: "anonymous" };
    }
    return { status: "unavailable" };
  } catch {
    return { status: "unavailable" };
  }
}

/** Public capability flags (no session needed). Falls back to "disabled" if the API is unreachable. */
export async function getAuthConfig(): Promise<{ passwordResetEnabled: boolean }> {
  try {
    const client = createApiClient(getEnv().API_URL, {
      fetch: ((req: Request) =>
        fetch(req, { cache: "no-store", signal: AbortSignal.timeout(3000) })) as typeof fetch,
    });
    const { data } = await client.GET("/api/v1/auth/config");
    return { passwordResetEnabled: data?.password_reset_enabled ?? false };
  } catch {
    return { passwordResetEnabled: false };
  }
}
