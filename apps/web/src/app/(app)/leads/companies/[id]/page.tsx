import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ErrorState } from "@freelancer-os/ui";
import { CompanyDetail } from "@/components/leads/company-detail";
import { COMPANIES_PATH, isUuid } from "@/components/leads/company-model";
import { requireWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Company" };
export const dynamic = "force-dynamic";

export default async function CompanyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isUuid(id)) notFound();
  const { api, workspaceId, workspace } = await requireWorkspace();
  const path = { workspace_id: workspaceId };

  const company = await api
    .GET("/api/v1/workspaces/{workspace_id}/companies/{company_id}", {
      params: { path: { ...path, company_id: id } },
    })
    .catch(() => null);
  if (company?.response.status === 404) notFound();

  const back = (
    <Link
      href={COMPANIES_PATH}
      className="text-sm text-muted underline underline-offset-4 hover:text-fg"
    >
      ← Back to companies
    </Link>
  );

  if (!company?.data) {
    return (
      <div className="flex flex-col gap-6">
        {back}
        <ErrorState
          title="Couldn't load this company"
          description="Your data is safe. Try again in a moment."
        />
      </div>
    );
  }

  const [leads, contacts] = await Promise.all([
    api
      .GET("/api/v1/workspaces/{workspace_id}/leads", {
        params: { path, query: { company_id: id, archived: "active", limit: 25 } },
      })
      .catch(() => null),
    api
      .GET("/api/v1/workspaces/{workspace_id}/contacts", {
        params: { path, query: { company_id: id, limit: 50 } },
      })
      .catch(() => null),
  ]);

  return (
    <div className="flex flex-col gap-6">
      {back}
      <CompanyDetail
        workspaceId={workspaceId}
        company={company.data}
        leads={leads?.data?.items ?? null}
        leadsTotal={leads?.data?.total ?? 0}
        contacts={contacts?.data?.items ?? null}
        contactsTotal={contacts?.data?.total ?? 0}
        canEdit={workspace.role === "owner"}
      />
    </div>
  );
}
