import type { Metadata } from "next";
import { ErrorState } from "@freelancer-os/ui";
import { ScoringForm } from "@/components/leads/scoring-form";
import { requireWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Fit scoring" };
export const dynamic = "force-dynamic";

export default async function ScoringPage() {
  const { api, workspaceId, workspace } = await requireWorkspace();
  const config = await api
    .GET("/api/v1/workspaces/{workspace_id}/fit-scoring", {
      params: { path: { workspace_id: workspaceId } },
    })
    .catch(() => null);

  if (!config?.data) {
    return (
      <ErrorState
        title="Couldn't load fit scoring"
        description="Your data is safe. Try again in a moment."
      />
    );
  }
  return (
    <ScoringForm
      workspaceId={workspaceId}
      initial={config.data}
      canEdit={workspace.role === "owner"}
    />
  );
}
