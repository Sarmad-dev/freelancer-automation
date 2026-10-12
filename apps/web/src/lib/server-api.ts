import "server-only";
import { cookies } from "next/headers";
import { createApiClient } from "@freelancer-os/contracts";
import { getEnv } from "@/env";
import { SESSION_COOKIE_NAMES } from "./auth-constants";

/** `name=value` for the session cookie in the incoming request, if any. */
export async function sessionCookieHeader(): Promise<string | null> {
  const jar = await cookies();
  for (const name of SESSION_COOKIE_NAMES) {
    const value = jar.get(name)?.value;
    if (value) return `${name}=${value}`;
  }
  return null;
}

/**
 * API client for server components: forwards the visitor's session cookie and never caches.
 * Returns null when there is no session cookie (callers redirect to sign-in).
 */
export async function serverApi() {
  const cookie = await sessionCookieHeader();
  if (!cookie) return null;
  return createApiClient(getEnv().API_URL, {
    headers: { cookie },
    fetch: ((req: Request) =>
      fetch(req, { cache: "no-store", signal: AbortSignal.timeout(8000) })) as typeof fetch,
  });
}
