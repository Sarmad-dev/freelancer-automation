import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ErrorState } from "@freelancer-os/ui";
import { ContactDetail } from "@/components/leads/contact-detail";
import { CONTACTS_PATH, isUuid } from "@/components/leads/contact-model";
import { requireWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Contact" };
export const dynamic = "force-dynamic";

export default async function ContactPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isUuid(id)) notFound();
  const { api, workspaceId, workspace } = await requireWorkspace();
  const path = { workspace_id: workspaceId };

  const [contact, leads, companies] = await Promise.all([
    api.GET("/api/v1/workspaces/{workspace_id}/contacts/{contact_id}", {
      params: { path: { ...path, contact_id: id } },
    }),
    api.GET("/api/v1/workspaces/{workspace_id}/leads", {
      params: { path, query: { contact_id: id, archived: "active", limit: 25 } },
    }),
    api.GET("/api/v1/workspaces/{workspace_id}/companies", {
      params: { path, query: { limit: 100, sort: "name" } },
    }),
  ]).catch(() => [null, null, null] as const);

  if (contact?.response.status === 404) notFound();

  return (
    <div className="flex flex-col gap-4">
      <Link
        href={CONTACTS_PATH}
        className="w-fit text-sm text-muted underline underline-offset-4 hover:text-fg"
      >
        ← Back to contacts
      </Link>
      {contact?.data ? (
        <ContactDetail
          workspaceId={workspaceId}
          contact={contact.data}
          leads={leads?.data?.items ?? []}
          leadTotal={leads?.data?.total ?? 0}
          companies={(companies?.data?.items ?? []).map((c) => ({ id: c.id, name: c.name }))}
          canEdit={workspace.role === "owner"}
        />
      ) : (
        <ErrorState
          title="Couldn't load this contact"
          description="Your data is safe. Try again in a moment."
        />
      )}
    </div>
  );
}
