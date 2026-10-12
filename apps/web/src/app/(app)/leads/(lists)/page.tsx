import type { Metadata } from "next";
import { ErrorState } from "@freelancer-os/ui";
import { LeadsTable } from "@/components/leads/leads-table";
import { apiQuery, parseLeadQuery } from "@/components/leads/lead-list-model";
import { requireWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Leads" };
export const dynamic = "force-dynamic";

export default async function LeadsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = parseLeadQuery(await searchParams);
  const { api, workspaceId, workspace } = await requireWorkspace();
  const path = { workspace_id: workspaceId };
  const [list, tags] = await Promise.all([
    api.GET("/api/v1/workspaces/{workspace_id}/leads", {
      params: { path, query: apiQuery(query) },
    }),
    // Tags only feed filters and bulk actions, so the list still works without them.
    api
      .GET("/api/v1/workspaces/{workspace_id}/tags", {
        params: { path, query: { limit: 100, sort: "name" } },
      })
      .catch(() => null),
  ]).catch(() => [null, null] as const);

  if (!list?.data) {
    return (
      <ErrorState
        title="Couldn't load your leads"
        description="Your data is safe. Try again in a moment."
      />
    );
  }
  return (
    <LeadsTable
      workspaceId={workspaceId}
      items={list.data.items}
      total={list.data.total}
      query={query}
      tags={tags?.data?.items ?? []}
      canEdit={workspace.role === "owner"}
      nowIso={new Date().toISOString()}
    />
  );
}
