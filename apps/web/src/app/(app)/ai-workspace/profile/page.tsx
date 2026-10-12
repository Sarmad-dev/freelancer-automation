import type { Metadata } from "next";
import { ErrorState } from "@freelancer-os/ui";
import { ProfileEditor } from "@/components/ai-workspace/profile-editor";
import { requireWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Profile" };
export const dynamic = "force-dynamic";

export default async function ProfilePage() {
  const { api, workspaceId } = await requireWorkspace();
  const path = { workspace_id: workspaceId };
  const [profile, summary, context] = await Promise.all([
    api.GET("/api/v1/workspaces/{workspace_id}/profile", { params: { path } }),
    api.GET("/api/v1/workspaces/{workspace_id}/profile/summary", { params: { path } }),
    api.GET("/api/v1/workspaces/{workspace_id}/ai-context", { params: { path } }),
  ]).catch(() => [null, null, null] as const);

  if (!profile?.data || !summary?.data || !context?.data) {
    return (
      <ErrorState
        title="Couldn't load your profile"
        description="Your data is safe. Try again in a moment."
      />
    );
  }
  return (
    <ProfileEditor
      workspaceId={workspaceId}
      initial={profile.data}
      initialSummary={summary.data}
      facts={context.data.facts.length}
    />
  );
}
