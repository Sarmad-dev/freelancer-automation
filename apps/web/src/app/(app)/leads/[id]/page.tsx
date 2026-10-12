import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ErrorState } from "@freelancer-os/ui";
import { LeadDetail } from "@/components/leads/lead-detail";
import { requireWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Lead" };
export const dynamic = "force-dynamic";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function LeadPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();

  const { api, workspaceId, workspace } = await requireWorkspace();
  const path = { workspace_id: workspaceId };
  const results = await Promise.all([
    api.GET("/api/v1/workspaces/{workspace_id}/leads/{lead_id}", {
      params: { path: { ...path, lead_id: id } },
    }),
    api.GET("/api/v1/workspaces/{workspace_id}/leads/{lead_id}/activities", {
      params: { path: { ...path, lead_id: id }, query: { limit: 50 } },
    }),
    api.GET("/api/v1/workspaces/{workspace_id}/tags", {
      params: { path, query: { limit: 100, sort: "name" } },
    }),
    api.GET("/api/v1/workspaces/{workspace_id}/pipeline/stages", { params: { path } }),
    api.GET("/api/v1/workspaces/{workspace_id}/companies", {
      params: { path, query: { limit: 100, sort: "name" } },
    }),
    api.GET("/api/v1/workspaces/{workspace_id}/contacts", {
      params: { path, query: { limit: 100, sort: "full_name" } },
    }),
    // The deals and follow-ups panels are secondary: if they fail the rest of the page still works.
    api.GET("/api/v1/workspaces/{workspace_id}/opportunities", {
      params: { path, query: { lead_id: id, limit: 20, sort: "-updated_at" } },
    }),
    api.GET("/api/v1/workspaces/{workspace_id}/tasks", {
      params: { path, query: { lead_id: id, view: "open", limit: 20 } },
    }),
    api.GET("/api/v1/workspaces/{workspace_id}/tasks/summary", { params: { path } }),
  ]).catch(() => null);

  if (results?.[0].response.status === 404) notFound();
  const [lead, activities, tags, stages, companies, contacts, deals, tasks, summary] =
    results ?? [];
  if (
    !lead?.data ||
    !activities?.data ||
    !tags?.data ||
    !stages?.data ||
    !companies?.data ||
    !contacts?.data
  ) {
    return (
      <ErrorState
        title="Couldn't load this lead"
        description="Your data is safe. Try again in a moment."
      />
    );
  }
  return (
    <LeadDetail
      workspaceId={workspaceId}
      lead={lead.data}
      activities={activities.data}
      tags={tags.data.items}
      stages={stages.data.items}
      companies={companies.data.items}
      contacts={contacts.data.items}
      deals={deals?.data?.items ?? []}
      tasks={tasks?.data?.items ?? []}
      timezone={summary?.data?.timezone ?? "UTC"}
      canEdit={workspace.role === "owner"}
      now={new Date().toISOString()}
    />
  );
}
