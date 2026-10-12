import type { Metadata } from "next";
import { ErrorState } from "@freelancer-os/ui";
import { KnowledgeManager } from "@/components/ai-workspace/knowledge-manager";
import { PAGE_SIZE, parseQuery } from "@/components/ai-workspace/knowledge-model";
import { requireWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Knowledge" };
export const dynamic = "force-dynamic";

export default async function KnowledgePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = parseQuery(await searchParams);
  const { api, workspaceId, workspace } = await requireWorkspace();
  const path = { workspace_id: workspaceId };
  const [list, stats] = await Promise.all([
    api.GET("/api/v1/workspaces/{workspace_id}/knowledge", {
      params: {
        path,
        query: {
          limit: PAGE_SIZE,
          offset: (query.page - 1) * PAGE_SIZE,
          ...(query.status ? { status: query.status } : {}),
          ...(query.kind ? { kind: query.kind } : {}),
          ...(query.q ? { q: query.q } : {}),
        },
      },
    }),
    api.GET("/api/v1/workspaces/{workspace_id}/knowledge/stats", { params: { path } }),
  ]).catch(() => [null, null] as const);

  if (!list?.data || !stats?.data) {
    return (
      <ErrorState
        title="Couldn't load your knowledge"
        description="Your data is safe. Try again in a moment."
      />
    );
  }
  return (
    <KnowledgeManager
      workspaceId={workspaceId}
      items={list.data.items}
      total={list.data.total}
      stats={stats.data}
      query={query}
      canEdit={workspace.role === "owner"}
    />
  );
}
