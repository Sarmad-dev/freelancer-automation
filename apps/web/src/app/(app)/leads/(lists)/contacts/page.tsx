import type { Metadata } from "next";
import { ErrorState } from "@freelancer-os/ui";
import { ContactsTable } from "@/components/leads/contacts-table";
import { apiQuery, parseContactQuery } from "@/components/leads/contact-model";
import { requireWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Contacts" };
export const dynamic = "force-dynamic";

export default async function ContactsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = parseContactQuery(await searchParams);
  const { api, workspaceId, workspace } = await requireWorkspace();
  const path = { workspace_id: workspaceId };
  const [list, companies] = await Promise.all([
    api.GET("/api/v1/workspaces/{workspace_id}/contacts", {
      params: { path, query: apiQuery(query) },
    }),
    api.GET("/api/v1/workspaces/{workspace_id}/companies", {
      params: { path, query: { limit: 100, sort: "name" } },
    }),
  ]).catch(() => [null, null] as const);

  if (!list?.data) {
    return (
      <ErrorState
        title="Couldn't load your contacts"
        description="Your data is safe. Try again in a moment."
      />
    );
  }
  return (
    <ContactsTable
      workspaceId={workspaceId}
      contacts={list.data.items}
      total={list.data.total}
      query={query}
      companies={(companies?.data?.items ?? []).map((c) => ({ id: c.id, name: c.name }))}
      canEdit={workspace.role === "owner"}
    />
  );
}
