"use client";

import type { ConversationDetail } from "./inbox-model";

/** PLACEHOLDER: replaced by the thread implementation. */
export function ThreadView({
  thread,
}: {
  workspaceId: string;
  thread: ConversationDetail;
  canEdit: boolean;
  /** Where "Back to the list" goes (small screens show one pane at a time). */
  backHref: string;
}) {
  return <div>{thread.subject}</div>;
}
