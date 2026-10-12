import type { Metadata } from "next";
import { ErrorState, PageHeader } from "@freelancer-os/ui";
import { MailboxPanel } from "@/components/integrations/mailbox-panel";
import { flashFrom } from "@/components/integrations/mailbox-model";
import { requireWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Integrations" };
export const dynamic = "force-dynamic";

export default async function IntegrationsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const flash = flashFrom(await searchParams);
  const { api, workspaceId, workspace } = await requireWorkspace();
  const path = { workspace_id: workspaceId };
  const [providers, accounts] = await Promise.all([
    api.GET("/api/v1/workspaces/{workspace_id}/email/providers", { params: { path } }),
    api.GET("/api/v1/workspaces/{workspace_id}/email/accounts", { params: { path } }),
  ]).catch(() => [null, null] as const);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Integrations"
        description="Connect where Freelancer OS reads replies and sends the messages you approve. Email is the only connector so far; calendars, sheets and others are planned."
      />
      {!providers?.data || !accounts?.data ? (
        <ErrorState
          title="Couldn't load your mailboxes"
          description="Your data is safe. Try again in a moment."
        />
      ) : (
        <MailboxPanel
          workspaceId={workspaceId}
          accounts={accounts.data}
          providers={providers.data}
          canEdit={workspace.role === "owner"}
          flash={flash}
        />
      )}
    </div>
  );
}
