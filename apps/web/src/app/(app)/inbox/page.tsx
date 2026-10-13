import type { Metadata } from "next";
import { ErrorState, PageHeader } from "@freelancer-os/ui";
import { InboxView } from "@/components/inbox/inbox-view";
import { apiQuery, parseInboxQuery } from "@/components/inbox/inbox-model";
import { requireWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Inbox" };
export const dynamic = "force-dynamic";

export default async function InboxPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = parseInboxQuery(await searchParams);
  const { api, workspaceId, workspace } = await requireWorkspace();
  const path = { workspace_id: workspaceId };

  const loaded = await Promise.all([
    api.GET("/api/v1/workspaces/{workspace_id}/inbox/conversations", {
      params: { path, query: apiQuery(query) },
    }),
    api.GET("/api/v1/workspaces/{workspace_id}/inbox/counts", { params: { path } }),
    api.GET("/api/v1/workspaces/{workspace_id}/email/accounts", { params: { path } }),
    query.selected
      ? api.GET("/api/v1/workspaces/{workspace_id}/inbox/conversations/{conversation_id}", {
          params: { path: { ...path, conversation_id: query.selected } },
        })
      : Promise.resolve(null),
  ]).catch(() => null);

  const list = loaded?.[0].data;
  const counts = loaded?.[1].data;
  const accounts = loaded?.[2].data;
  const detail = loaded?.[3] ?? null;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Inbox"
        description="Replies to your outreach, sorted and explained. Nothing is sent from here until you approve it."
      />
      {!list || !counts || !accounts ? (
        <ErrorState
          title="Couldn't load your inbox"
          description="Your data is safe. Try again in a moment."
        />
      ) : (
        <InboxView
          workspaceId={workspaceId}
          items={list.items}
          total={list.total}
          counts={counts}
          query={query}
          thread={detail?.data ?? null}
          threadMissing={Boolean(query.selected) && !detail?.data}
          hasMailbox={accounts.length > 0}
          canEdit={workspace.role === "owner"}
        />
      )}
    </div>
  );
}
