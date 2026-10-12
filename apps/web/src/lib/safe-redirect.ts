/**
 * Validate a post-sign-in destination taken from the URL. Only same-origin absolute paths are
 * allowed; anything else (external URLs, protocol-relative `//host`, backslash tricks, control
 * characters) falls back to "/" so the sign-in page cannot be used as an open redirect.
 */
export function safeNextPath(next: string | null | undefined, fallback = "/"): string {
  if (!next) return fallback;
  if (next.length > 512) return fallback;
  if (!next.startsWith("/") || next.startsWith("//")) return fallback;
  // eslint-disable-next-line no-control-regex -- rejecting control characters is the point
  if (/[\\\u0000-\u001f\u007f]/.test(next)) return fallback;
  // Never bounce back into the auth pages.
  if (/^\/(sign-in|sign-up|forgot-password|reset-password)(\/|\?|$)/.test(next)) return fallback;
  try {
    const url = new URL(next, "http://localhost");
    if (url.origin !== "http://localhost") return fallback;
  } catch {
    return fallback;
  }
  return next;
}
