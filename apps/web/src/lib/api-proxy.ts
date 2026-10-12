/**
 * Same-origin proxy helpers. The browser only ever talks to the Next.js server; the Next.js server
 * forwards `/api/v1/*` to the FastAPI service. This keeps the session cookie first-party (no CORS, no
 * third-party-cookie issues) and keeps the API's address private.
 */

/** Request headers that are forwarded upstream. Everything else is dropped on purpose. */
const FORWARD_REQUEST_HEADERS = [
  "content-type",
  "accept",
  "accept-language",
  "cookie",
  "origin",
  "user-agent",
  "x-requested-with",
  "x-request-id",
  "x-forwarded-for",
] as const;

/** Response headers sent back to the browser (Set-Cookie is handled separately, one per cookie). */
const FORWARD_RESPONSE_HEADERS = [
  "content-type",
  "retry-after",
  "x-request-id",
  "cache-control",
  "content-disposition", // lets CSV exports and error reports download with their filename
] as const;

const ALLOWED_PREFIXES = ["auth", "workspaces", "email"] as const;

/** The only `email` route the browser may reach: where the mail provider sends people back after they consent. */
const EMAIL_OAUTH_CALLBACK = ["email", "oauth", "callback"] as const;

/** Returns the upstream path (`/api/v1/...`) for a catch-all route, or null if it must be refused. */
export function buildUpstreamPath(segments: string[]): string | null {
  if (segments.length === 0) return null;
  if (!ALLOWED_PREFIXES.includes(segments[0] as (typeof ALLOWED_PREFIXES)[number])) return null;
  if (
    segments[0] === "email" &&
    (segments.length !== EMAIL_OAUTH_CALLBACK.length ||
      !EMAIL_OAUTH_CALLBACK.every((part, i) => segments[i] === part))
  ) {
    return null;
  }
  for (const s of segments) {
    // eslint-disable-next-line no-control-regex -- rejecting control characters is the point
    if (s === "" || s === "." || s === ".." || /[\\/\u0000-\u001f]/.test(s)) return null;
  }
  return `/api/v1/${segments.map(encodeURIComponent).join("/")}`;
}

export function pickRequestHeaders(incoming: Headers): Headers {
  const out = new Headers();
  for (const name of FORWARD_REQUEST_HEADERS) {
    const value = incoming.get(name);
    if (value) out.set(name, value);
  }
  return out;
}

/** A path on this site: starts with one slash, not `//host` or `/\\host`, and has no control characters. */
export function isSameSitePath(value: string): boolean {
  // eslint-disable-next-line no-control-regex -- rejecting control characters is the point
  return /^\/(?![/\\])/.test(value) && !/[\u0000-\u001f]/.test(value);
}

export function pickResponseHeaders(upstream: Headers): Headers {
  const out = new Headers();
  for (const name of FORWARD_RESPONSE_HEADERS) {
    const value = upstream.get(name);
    if (value) out.set(name, value);
  }
  // A redirect is passed on only when it stays on this site (the OAuth callback returns people to /integrations).
  const location = upstream.get("location");
  if (location && isSameSitePath(location)) out.set("location", location);
  // Authenticated responses must never be cached by shared caches or the browser.
  out.set("cache-control", "no-store");
  for (const cookie of upstream.getSetCookie()) out.append("set-cookie", cookie);
  return out;
}
