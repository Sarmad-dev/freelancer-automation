"use client";

import { useState } from "react";
import { Badge, Button, Notice, type BadgeTone } from "@freelancer-os/ui";
import { formatDateTime } from "@/components/leads/lead-model";
import type { ThreadMessage } from "./inbox-model";
import { SafeHtmlFrame } from "./safe-html-frame";

const DELIVERY_TONE: Record<ThreadMessage["delivery_state"], BadgeTone> = {
  demo: "info",
  queued: "neutral",
  sent: "success",
  failed: "danger",
  unknown: "warning",
};

/** `20 KB`, `1.5 MB`. Unknown or invalid sizes give "". */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes) || bytes < 0) return "";
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  const mb = Math.round((bytes / (1024 * 1024)) * 10) / 10;
  return `${mb} MB`;
}

function ViewToggle({
  view,
  onChange,
}: {
  view: "text" | "html";
  onChange: (view: "text" | "html") => void;
}) {
  return (
    <div role="group" aria-label="Message view" className="flex gap-1">
      {(
        [
          ["text", "Text"],
          ["html", "Formatted"],
        ] as const
      ).map(([value, label]) => (
        <Button
          key={value}
          size="sm"
          variant={view === value ? "primary" : "secondary"}
          aria-pressed={view === value}
          onClick={() => onChange(value)}
        >
          {label}
        </Button>
      ))}
    </div>
  );
}

export function MessageCard({ message }: { message: ThreadMessage }) {
  const [view, setView] = useState<"text" | "html">("text");
  const outbound = message.direction === "outbound";
  const who = outbound ? "You" : message.from_address;
  const sent = formatDateTime(message.sent_at);
  const { body } = message;
  const html = body.html ?? "";
  const hasHtml = html.length > 0;

  return (
    <article
      aria-label={`${outbound ? "Message from you" : `Message from ${message.from_address}`}, ${sent}`}
      className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4"
    >
      <header className="flex flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="min-w-0 break-words text-sm font-semibold text-fg">{who}</span>
          {outbound ? (
            <Badge
              tone={DELIVERY_TONE[message.delivery_state]}
              title={message.delivery_label}
              className="max-w-full whitespace-normal"
            >
              {message.delivery_label}
            </Badge>
          ) : null}
          {message.is_bounce ? <Badge tone="danger">Delivery failure notice</Badge> : null}
          <time dateTime={message.sent_at} className="ml-auto text-[13px] text-muted">
            {sent}
          </time>
        </div>
        <p className="break-words text-[13px] text-muted">
          {message.from_address} → {message.to_addresses.join(", ")}
        </p>
      </header>

      {!body.available ? <Notice title="Only a short preview of this message is stored." /> : null}
      {hasHtml && body.available ? <ViewToggle view={view} onChange={setView} /> : null}

      {view === "html" && hasHtml && body.available ? (
        <SafeHtmlFrame html={html} />
      ) : body.text.trim() ? (
        <pre className="whitespace-pre-wrap break-words font-sans text-sm text-fg">{body.text}</pre>
      ) : (
        <p className="text-sm text-muted">There is no text in this message.</p>
      )}

      {body.images_blocked ? (
        <p className="text-[13px] text-muted">Images and other remote content are not loaded.</p>
      ) : null}
      {body.text_truncated ? (
        <p className="text-[13px] text-muted">This long message was shortened.</p>
      ) : null}

      {message.attachments.length > 0 ? (
        <div className="flex flex-col gap-1">
          <ul aria-label="Attachments" className="flex flex-col gap-1 text-[13px]">
            {message.attachments.map((a, i) => {
              const size = formatBytes(a.size);
              return (
                <li key={`${a.filename}-${i}`} className="break-words text-fg">
                  {a.filename}
                  <span className="text-muted">
                    {" "}
                    {a.mime_type}
                    {size ? `, ${size}` : ""}
                  </span>
                </li>
              );
            })}
          </ul>
          <p className="text-[13px] text-muted">
            Attachment contents aren&apos;t stored or opened here.
          </p>
        </div>
      ) : null}
    </article>
  );
}
