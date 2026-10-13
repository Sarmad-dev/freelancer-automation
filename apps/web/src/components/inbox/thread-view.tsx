"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Badge, Button, useToast } from "@freelancer-os/ui";
import { browserApi, toFailure } from "@/lib/api-client";
import { describeFailure } from "@/lib/mutation-error";
import { ClassificationCard } from "./classification-card";
import type { ConversationDetail } from "./inbox-model";
import { MessageCard } from "./message-card";
import { ReplyEditor } from "./reply-editor";
import { StopBanner } from "./stop-banner";

export function ThreadView({
  workspaceId,
  thread,
  canEdit,
  backHref,
}: {
  workspaceId: string;
  thread: ConversationDetail;
  canEdit: boolean;
  /** Where "Back to the list" goes (small screens show one pane at a time). */
  backHref: string;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);
  const markedRead = useRef<string | null>(null);
  const { id, unread } = thread;

  // Opening an unread conversation marks it read, once (the ref also covers React strict mode).
  useEffect(() => {
    if (!unread || !canEdit || markedRead.current === id) return;
    markedRead.current = id;
    browserApi()
      .POST("/api/v1/workspaces/{workspace_id}/inbox/conversations/{conversation_id}/read", {
        params: { path: { workspace_id: workspaceId, conversation_id: id } },
      })
      .then(({ response }) => {
        if (response.ok) router.refresh();
      })
      .catch(() => undefined);
  }, [unread, canEdit, id, workspaceId, router]);

  async function markUnread() {
    if (busy) return;
    setBusy(true);
    try {
      const { error, response } = await browserApi().POST(
        "/api/v1/workspaces/{workspace_id}/inbox/conversations/{conversation_id}/unread",
        { params: { path: { workspace_id: workspaceId, conversation_id: id } } },
      );
      if (response.ok) {
        toast({ title: "Marked unread", tone: "success" });
        router.refresh();
      } else {
        const out = describeFailure(error, response, "conversation");
        if (out) {
          toast({
            title: "Couldn't mark it unread",
            description: out.failure.text,
            tone: "danger",
          });
        }
      }
    } catch {
      toast({
        title: "Couldn't mark it unread",
        description: toFailure(undefined).message,
        tone: "danger",
      });
    } finally {
      setBusy(false);
    }
  }

  const subject = thread.subject?.trim() || "(no subject)";
  const { counterpart } = thread;

  return (
    <section aria-label={`Conversation: ${subject}`} className="flex min-w-0 flex-col gap-4">
      <Link
        href={backHref}
        className="inline-flex w-fit items-center gap-1 text-sm font-medium text-accent underline lg:hidden"
      >
        <span aria-hidden>←</span> Back to the list
      </Link>

      <header className="flex flex-col gap-2">
        <h2 className="break-words text-lg font-semibold text-fg">{subject}</h2>
        <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-[13px] sm:grid-cols-2">
          <div className="flex min-w-0 gap-2">
            <dt className="text-muted">With</dt>
            <dd className="min-w-0 break-words text-fg">
              {counterpart.name ? (
                <>
                  {counterpart.name} <span className="text-muted">{counterpart.address}</span>
                </>
              ) : (
                counterpart.address || "Unknown sender"
              )}
            </dd>
          </div>
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <dt className="text-muted">Mailbox</dt>
            <dd className="min-w-0 break-words text-fg">{thread.account_email}</dd>
            {thread.is_demo ? <Badge tone="info">Demo</Badge> : null}
          </div>
          {thread.lead ? (
            <div className="flex min-w-0 gap-2">
              <dt className="text-muted">Lead</dt>
              <dd className="min-w-0 break-words">
                <Link href={`/leads/${thread.lead.id}`} className="text-accent underline">
                  {thread.lead.title}
                </Link>
              </dd>
            </div>
          ) : null}
          {thread.company ? (
            <div className="flex min-w-0 gap-2">
              <dt className="text-muted">Company</dt>
              <dd className="min-w-0 break-words text-fg">{thread.company.name}</dd>
            </div>
          ) : null}
          <div className="flex gap-2">
            <dt className="text-muted">Messages</dt>
            <dd className="text-fg">{thread.message_count}</dd>
          </div>
        </dl>
        {canEdit && !unread ? (
          <div>
            <Button variant="secondary" size="sm" onClick={() => void markUnread()} disabled={busy}>
              Mark unread
            </Button>
          </div>
        ) : null}
      </header>

      {thread.stop ? (
        <StopBanner workspaceId={workspaceId} stop={thread.stop} canEdit={canEdit} />
      ) : null}
      <ClassificationCard workspaceId={workspaceId} thread={thread} canEdit={canEdit} />

      <ol aria-label="Messages" className="flex flex-col gap-3">
        {thread.messages.map((m) => (
          <li key={m.id}>
            <MessageCard message={m} />
          </li>
        ))}
      </ol>

      <ReplyEditor workspaceId={workspaceId} thread={thread} canEdit={canEdit} />
    </section>
  );
}
