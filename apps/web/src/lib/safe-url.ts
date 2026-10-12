/**
 * Only plain http(s) URLs may become links. The API already validates stored URLs; this is the last line of
 * defence in the browser so a bad value (or a future bug) can never render as `javascript:` or `data:`.
 */
export function safeExternalUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    if (url.username || url.password) return null;
    return url.toString();
  } catch {
    return null;
  }
}

/** Deterministic date for server- and client-rendered output (avoids hydration mismatches across time zones). */
export function formatDate(iso: string): string {
  return iso.slice(0, 10);
}
