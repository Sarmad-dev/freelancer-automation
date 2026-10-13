import Link from "next/link";
import { ConversationList } from "./conversation-list";
import { ThreadView } from "./thread-view";
import {
  inboxHref,
  type ConversationDetail,
  type ConversationSummary,
  type InboxCounts,
  type InboxQuery,
} from "./inbox-model";

/**
 * Two panes on wide screens (list | thread). On small screens one at a time: the list, or the open thread with a way back.
 */
export function InboxView({
  workspaceId,
  items,
  total,
  counts,
  query,
  thread,
  threadMissing,
  hasMailbox,
  canEdit,
}: {
  workspaceId: string;
  items: readonly ConversationSummary[];
  total: number;
  counts: InboxCounts;
  query: InboxQuery;
  thread: ConversationDetail | null;
  /** A conversation id was asked for but could not be loaded (gone, or not in this workspace). */
  threadMissing: boolean;
  hasMailbox: boolean;
  canEdit: boolean;
}) {
  const open = query.selected !== "";
  const backHref = inboxHref(query, { selected: "" });
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
      <div className={open ? "hidden lg:block" : ""}>
        <ConversationList
          items={items}
          total={total}
          query={query}
          counts={counts}
          hasMailbox={hasMailbox}
        />
      </div>
      <div className={open ? "" : "hidden lg:block"}>
        {thread ? (
          <ThreadView
            key={thread.id}
            workspaceId={workspaceId}
            thread={thread}
            canEdit={canEdit}
            backHref={backHref}
          />
        ) : threadMissing ? (
          <div role="alert" className="rounded-lg border border-line bg-surface p-6">
            <p className="font-medium text-fg">That conversation isn&apos;t available</p>
            <p className="mt-1 text-sm text-muted">
              It may have been deleted, or it belongs to another workspace.
            </p>
            <Link
              href={backHref}
              className="mt-3 inline-block text-sm font-medium text-accent underline"
            >
              Back to the list
            </Link>
          </div>
        ) : (
          <div className="hidden rounded-lg border border-dashed border-line p-10 text-center text-sm text-muted lg:block">
            Choose a conversation to read it.
          </div>
        )}
      </div>
    </div>
  );
}
