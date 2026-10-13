"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  Button,
  ConfirmDialog,
  EmptyState,
  Notice,
  Table,
  TableContainer,
  Td,
  Th,
  useToast,
} from "@freelancer-os/ui";
import { browserApi, toFailure } from "@/lib/api-client";
import { describeFailure } from "@/lib/mutation-error";
import { formatDate } from "@/lib/safe-url";
import { ArchivedBadge, WebsiteLink } from "./companies-table";
import { CompanyDrawer } from "./company-form";
import { provenance } from "./company-model";
import { DoNotContactBadge, FitBadge, SampleBadge, StatusBadge } from "./lead-badges";
import {
  formatDateTime,
  hrefWith,
  sizeLabel,
  type CompanyOut,
  type ContactOut,
  type LeadOut,
} from "./lead-model";

const linkClass = "underline underline-offset-4 hover:text-accent";
const none = <span className="text-muted">Not set</span>;

export function CompanyDetail({
  workspaceId,
  company,
  leads,
  leadsTotal,
  contacts,
  contactsTotal,
  canEdit,
}: {
  workspaceId: string;
  company: CompanyOut;
  /** null = the related list could not be loaded. */
  leads: LeadOut[] | null;
  leadsTotal: number;
  contacts: ContactOut[] | null;
  contactsTotal: number;
  canEdit: boolean;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const [editing, setEditing] = useState(false);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const archived = Boolean(company.archived_at);
  const prov = provenance(company);

  async function toggleArchive(restore: boolean) {
    setBusy(true);
    setError(null);
    try {
      const { error: body, response } = await browserApi().POST(
        restore
          ? "/api/v1/workspaces/{workspace_id}/companies/{company_id}/restore"
          : "/api/v1/workspaces/{workspace_id}/companies/{company_id}/archive",
        { params: { path: { workspace_id: workspaceId, company_id: company.id } } },
      );
      if (response.ok) {
        toast({
          title: restore ? "Company restored" : "Company archived",
          description: restore
            ? "It's back in your lists."
            : "Hidden from lists. You can restore it any time.",
          tone: "success",
        });
        router.refresh();
      } else {
        const out = describeFailure(body, response, "company");
        if (out) setError(out.failure.text);
      }
    } catch {
      setError(toFailure(undefined).message);
    }
    setBusy(false);
  }

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight break-words text-fg">
              {company.name}
            </h1>
            {company.is_sample ? <SampleBadge /> : null}
            {archived ? <ArchivedBadge /> : null}
          </div>
          <p className="mt-1 text-sm text-muted">
            Updated <time dateTime={company.updated_at}>{formatDate(company.updated_at)}</time>
          </p>
        </div>
        {canEdit ? (
          <div className="flex flex-wrap items-center gap-2">
            {archived ? (
              <Button variant="secondary" disabled={busy} onClick={() => void toggleArchive(true)}>
                Restore
              </Button>
            ) : (
              <>
                <Button variant="secondary" onClick={() => setEditing(true)}>
                  Edit
                </Button>
                <Button variant="secondary" disabled={busy} onClick={() => setConfirmArchive(true)}>
                  Archive
                </Button>
              </>
            )}
          </div>
        ) : null}
      </header>

      {!canEdit ? (
        <Notice tone="info" title="View only">
          Only the workspace owner can change companies.
        </Notice>
      ) : null}
      {archived ? (
        <Notice tone="warning" title="This company is archived">
          It is hidden from lists and can&apos;t be edited.
          {canEdit ? " Restore it to make changes." : ""}
        </Notice>
      ) : null}
      {error ? (
        <Notice tone="danger" title="That didn't work">
          {error}
        </Notice>
      ) : null}

      <section
        aria-labelledby="company-summary"
        className="rounded-lg border border-line bg-surface p-5"
      >
        <h2 id="company-summary" className="text-base font-semibold text-fg">
          Summary
        </h2>
        <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-[10rem_1fr]">
          <dt className="text-muted">Website</dt>
          <dd className="min-w-0">
            {company.website ? <WebsiteLink website={company.website} /> : none}
          </dd>
          <dt className="text-muted">Domain</dt>
          <dd className="break-all">{company.domain || none}</dd>
          <dt className="text-muted">Industry</dt>
          <dd className="break-words">{company.industry || none}</dd>
          <dt className="text-muted">Size</dt>
          <dd>{sizeLabel(company.size_label) || none}</dd>
          <dt className="text-muted">Location</dt>
          <dd className="break-words">{company.location || none}</dd>
          <dt className="text-muted">Notes</dt>
          <dd className="break-words whitespace-pre-wrap">{company.notes || none}</dd>
          <dt className="text-muted">Where it came from</dt>
          <dd className="break-words">
            {prov.manual ? (
              "Added manually"
            ) : (
              <>
                {prov.source}
                {prov.retrievedAt ? (
                  <>
                    {" · retrieved "}
                    <time dateTime={prov.retrievedAt}>{formatDateTime(prov.retrievedAt)}</time>
                  </>
                ) : null}
              </>
            )}
          </dd>
          <dt className="text-muted">Added</dt>
          <dd>
            <time dateTime={company.created_at}>{formatDateTime(company.created_at)}</time>
          </dd>
        </dl>
      </section>

      <section aria-labelledby="company-leads" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="company-leads" className="text-base font-semibold text-fg">
            Leads
          </h2>
          {leadsTotal > 0 ? (
            <Link
              href={hrefWith("/leads", { company_id: company.id })}
              className={`${linkClass} text-sm`}
            >
              {leadsTotal > (leads?.length ?? 0)
                ? `See all ${leadsTotal} leads`
                : "Open in the leads list"}
            </Link>
          ) : null}
        </div>
        {leads === null ? (
          <Notice tone="warning" title="Couldn't load leads">
            Your data is safe. Reload the page to try again.
          </Notice>
        ) : leads.length === 0 ? (
          <EmptyState
            titleAs="h3"
            title="No leads for this company yet"
            description="Leads you link to this company will show up here."
          />
        ) : (
          <TableContainer>
            <Table>
              <caption className="sr-only">Active leads for {company.name}</caption>
              <thead>
                <tr>
                  <Th>Lead</Th>
                  <Th>Status</Th>
                  <Th>Fit</Th>
                  <Th>Next action</Th>
                </tr>
              </thead>
              <tbody>
                {leads.map((l) => (
                  <tr key={l.id}>
                    <Td className="max-w-72 font-medium">
                      <Link href={`/leads/${l.id}`} className={`${linkClass} break-words`}>
                        {l.title}
                      </Link>
                    </Td>
                    <Td>
                      <StatusBadge status={l.status} />
                    </Td>
                    <Td>
                      <FitBadge band={l.fit_band} score={l.fit_score} />
                    </Td>
                    <Td className="break-words">
                      {l.next_action ? (
                        <>
                          {l.next_action}
                          {l.next_action_at ? (
                            <span className="text-muted">
                              {" · "}
                              <time dateTime={l.next_action_at}>
                                {formatDateTime(l.next_action_at)}
                              </time>
                            </span>
                          ) : null}
                        </>
                      ) : (
                        <span className="text-muted">None planned</span>
                      )}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </TableContainer>
        )}
      </section>

      <section aria-labelledby="company-contacts" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="company-contacts" className="text-base font-semibold text-fg">
            Contacts
          </h2>
          {contactsTotal > 0 ? (
            <Link
              href={hrefWith("/leads/contacts", { company_id: company.id })}
              className={`${linkClass} text-sm`}
            >
              {contactsTotal > (contacts?.length ?? 0)
                ? `See all ${contactsTotal} contacts`
                : "Open in the contacts list"}
            </Link>
          ) : null}
        </div>
        {contacts === null ? (
          <Notice tone="warning" title="Couldn't load contacts">
            Your data is safe. Reload the page to try again.
          </Notice>
        ) : contacts.length === 0 ? (
          <EmptyState
            titleAs="h3"
            title="No contacts for this company yet"
            description="People you link to this company will show up here."
          />
        ) : (
          <TableContainer>
            <Table>
              <caption className="sr-only">Contacts at {company.name}</caption>
              <thead>
                <tr>
                  <Th>Name</Th>
                  <Th>Role</Th>
                  <Th>Email</Th>
                </tr>
              </thead>
              <tbody>
                {contacts.map((c) => (
                  <tr key={c.id}>
                    <Td className="max-w-64 font-medium">
                      <Link href={`/leads/contacts/${c.id}`} className={`${linkClass} break-words`}>
                        {c.full_name}
                      </Link>
                    </Td>
                    <Td className="break-words">
                      {c.role_title || <span className="text-muted">—</span>}
                    </Td>
                    <Td>
                      <div className="flex flex-wrap items-center gap-2">
                        {c.email ? (
                          <span className="break-all">{c.email}</span>
                        ) : (
                          <span className="text-muted">—</span>
                        )}
                        {c.do_not_contact ? <DoNotContactBadge /> : null}
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </TableContainer>
        )}
      </section>

      {editing && canEdit && !archived ? (
        <CompanyDrawer
          key={company.updated_at}
          workspaceId={workspaceId}
          company={company}
          onClose={() => setEditing(false)}
        />
      ) : null}
      <ConfirmDialog
        open={confirmArchive}
        onOpenChange={setConfirmArchive}
        title="Archive this company?"
        description="Hidden from lists. Its leads and contacts keep the link."
        confirmLabel="Archive"
        destructive
        onConfirm={() => void toggleArchive(false)}
      />
    </div>
  );
}
