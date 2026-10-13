const CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; form-action 'none'";

const STYLE = `
  html { color-scheme: light; }
  body { margin: 0; padding: 12px; background: #fff; color: #1a1a1a;
    font: 14px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    overflow-wrap: anywhere; word-wrap: break-word; }
  a { color: #1d4ed8; }
  blockquote { margin: 8px 0; padding-left: 12px; border-left: 3px solid #cbd5e1; color: #475569; }
  table { border-collapse: collapse; max-width: 100%; }
  td, th { border: 1px solid #cbd5e1; padding: 4px 8px; }
  pre { white-space: pre-wrap; }
`;

/** Anything that could run code. The API strips these; finding one here means something is wrong. */
const UNSAFE = [/<script/i, /javascript:/i, /<[^>]*[\s"'/]on[a-z]+\s*=/i];

export function isUnsafeHtml(html: string): boolean {
  return UNSAFE.some((pattern) => pattern.test(html));
}

const WITHHELD = "<p>This message&#39;s formatted view was withheld for safety.</p>";

/**
 * The full document shown inside the sandboxed frame. The HTML is already sanitised by the API;
 * this is defence in depth: a locked-down CSP, no images, and a refusal to show markup that
 * still contains script, `javascript:` or event-handler attributes.
 */
export function buildEmailDocument(html: string): string {
  const body = isUnsafeHtml(html) ? WITHHELD : html;
  return (
    `<!doctype html><html><head><meta charset="utf-8">` +
    `<meta http-equiv="Content-Security-Policy" content="${CSP}">` +
    `<base target="_blank"><style>${STYLE}</style></head><body>${body}</body></html>`
  );
}

/** Sanitised email HTML in a sandbox with no scripts and no access to this page. */
export function SafeHtmlFrame({ html }: { html: string }) {
  return (
    <iframe
      sandbox="allow-popups allow-popups-to-escape-sandbox"
      referrerPolicy="no-referrer"
      title="Formatted message"
      srcDoc={buildEmailDocument(html)}
      loading="lazy"
      className="h-80 w-full rounded-md border border-line bg-white"
    />
  );
}
