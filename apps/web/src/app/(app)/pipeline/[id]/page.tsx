import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ErrorState } from "@freelancer-os/ui";
import { DealDetail } from "@/components/pipeline/deal-detail";
import { requireWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Deal" };
export const dynamic = "force-dynamic";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function DealPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();

  const { api, workspaceId, workspace } = await requireWorkspace();
  const path = { workspace_id: workspaceId };
  const dealPath = { ...path, opportunity_id: id };
  const results = await Promise.all([
    api.GET("/api/v1/workspaces/{workspace_id}/opportunities/{opportunity_id}", {
      params: { path: dealPath },
    }),
    api.GET("/api/v1/workspaces/{workspace_id}/opportunities/{opportunity_id}/activities", {
      params: { path: dealPath, query: { limit: 50 } },
    }),
    api.GET("/api/v1/workspaces/{workspace_id}/pipeline/stages", { params: { path } }),
    api.GET("/api/v1/workspaces/{workspace_id}/tasks", {
      params: { path, query: { opportunity_id: id, view: "open", limit: 50 } },
    }),
    api.GET("/api/v1/workspaces/{workspace_id}/tasks", {
      params: { path, query: { opportunity_id: id, view: "done", limit: 10 } },
    }),
  ]).catch(() => null);

  if (results?.[0].response.status === 404) notFound();
  const [deal, activities, stages, openTasks, doneTasks] = results ?? [];
  if (!deal?.data || !activities?.data || !stages?.data || !openTasks?.data || !doneTasks?.data) {
    return (
      <ErrorState
        title="Couldn't load this deal"
        description="Your data is safe. Try again in a moment."
      />
    );
  }
  return (
    <DealDetail
      workspaceId={workspaceId}
      deal={deal.data}
      stages={stages.data.items}
      activities={activities.data}
      openTasks={openTasks.data}
      doneTasks={doneTasks.data}
      canEdit={workspace.role === "owner"}
      today={new Date().toISOString().slice(0, 10)}
    />
  );
}
