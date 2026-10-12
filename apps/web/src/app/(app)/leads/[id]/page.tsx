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
  ]).catch(() => null);

  if (results?.[0].response.status === 404) notFound();
  const [lead, activities, tags, stages, companies, contacts] = results ?? [];
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
      canEdit={workspace.role === "owner"}
      now={new Date().toISOString()}
    />
  );
}
