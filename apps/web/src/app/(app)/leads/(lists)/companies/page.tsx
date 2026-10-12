import type { Metadata } from "next";
import { ErrorState } from "@freelancer-os/ui";
import { CompaniesTable } from "@/components/leads/companies-table";
import { apiQuery, parseCompanyQuery } from "@/components/leads/company-model";
import { requireWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Companies" };
export const dynamic = "force-dynamic";

export default async function CompaniesPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = parseCompanyQuery(await searchParams);
  const { api, workspaceId, workspace } = await requireWorkspace();
  const list = await api
    .GET("/api/v1/workspaces/{workspace_id}/companies", {
      params: { path: { workspace_id: workspaceId }, query: apiQuery(query) },
    })
    .catch(() => null);

  if (!list?.data) {
    return (
      <ErrorState
        title="Couldn't load your companies"
        description="Your data is safe. Try again in a moment."
      />
    );
  }
  return (
    <CompaniesTable
      workspaceId={workspaceId}
      items={list.data.items}
      total={list.data.total}
      query={query}
      canEdit={workspace.role === "owner"}
    />
  );
}
