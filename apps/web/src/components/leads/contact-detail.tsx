"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import {
  Badge,
  Button,
  ConfirmDialog,
  Drawer,
  Notice,
  PageHeader,
  useToast,
} from "@freelancer-os/ui";
import { browserApi, toFailure } from "@/lib/api-client";
import { describeFailure, type MutationFailure } from "@/lib/mutation-error";
import { formatDate } from "@/lib/safe-url";
import { ContactFields, type CompanyChoice } from "./contact-form";
import {
  diffContact,
  formFromContact,
  isManualSource,
  mailHref,
  telHref,
  type ContactForm,
} from "./contact-model";
import { DoNotContactBadge, FitBadge, SampleBadge, StatusBadge } from "./lead-badges";
import { formatDateTime, type ContactOut, type LeadOut } from "./lead-model";

const DNC_MESSAGE =
  "This email is on your do-not-contact list. Nothing will be sent to it, by you or by any automation.";

export function ContactDetail({
  workspaceId,
  contact,
  leads,
  leadTotal,
  companies,
  canEdit,
}: {
  workspaceId: string;
  contact: ContactOut;
  leads: LeadOut[];
  leadTotal: number;
  companies: CompanyChoice[];
  canEdit: boolean;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const [editing, setEditing] = useState(false);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<MutationFailure | null>(null);
  const archived = Boolean(contact.archived_at);

  async function transition(kind: "archive" | "restore") {
    setBusy(true);
    setActionError(null);
    try {
      const path = { workspace_id: workspaceId, contact_id: contact.id };
      const { error, response } =
        kind === "archive"
          ? await browserApi().POST(
              "/api/v1/workspaces/{workspace_id}/contacts/{contact_id}/archive",
              {
                params: { path },
              },
            )
          : await browserApi().POST(
              "/api/v1/workspaces/{workspace_id}/contacts/{contact_id}/restore",
              {
                params: { path },
              },
            );
      if (response.ok) {
        toast({
          title: kind === "archive" ? "Contact archived" : "Contact restored",
          description:
            kind === "archive" ? "Hidden from lists. Their leads keep the link." : undefined,
          tone: "success",
        });
        router.refresh();
      } else {
        const out = describeFailure(error, response, "contact");
        if (out) setActionError(out.failure);
      }
    } catch {
      setActionError({ title: "That didn't work", text: toFailure(undefined).message });
    }
    setBusy(false);
  }

  const mail = contact.do_not_contact ? null : mailHref(contact.email);
  const tel = telHref(contact.phone);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={contact.full_name}
        badge={
          contact.is_sample || archived || contact.do_not_contact ? (
            <span className="flex flex-wrap items-center gap-1.5">
              {contact.is_sample ? <SampleBadge /> : null}
              {archived ? <Badge>Archived</Badge> : null}
              {contact.do_not_contact ? <DoNotContactBadge /> : null}
            </span>
          ) : undefined
        }
        actions={
          canEdit ? (
            <>
              <Button variant="secondary" onClick={() => setEditing(true)} disabled={archived}>
                Edit
              </Button>
              {archived ? (
                <Button
                  variant="secondary"
                  onClick={() => void transition("restore")}
                  disabled={busy}
                >
                  Restore
                </Button>
              ) : (
                <Button variant="secondary" onClick={() => setConfirmArchive(true)} disabled={busy}>
                  Archive
                </Button>
              )}
            </>
          ) : undefined
        }
      />

      {!canEdit ? (
        <Notice tone="info" title="View only">
          Only the workspace owner can edit or archive contacts.
        </Notice>
      ) : null}
      {contact.do_not_contact ? (
        <Notice tone="warning" title="Do not contact">
          {DNC_MESSAGE}
        </Notice>
      ) : null}
      {archived ? (
        <Notice tone="info" title="This contact is archived">
          {canEdit
            ? "It is hidden from lists and can't be edited. Restore it to make changes."
            : "It is hidden from lists and can't be edited."}
        </Notice>
      ) : null}
      {actionError ? (
        <Notice tone="danger" title={actionError.title}>
          {actionError.text}
        </Notice>
      ) : null}

      <section
        aria-labelledby="contact-summary-h"
        className="rounded-lg border border-line bg-surface p-5"
      >
        <h2 id="contact-summary-h" className="text-base font-semibold text-fg">
          Details
        </h2>
        <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-[10rem_1fr]">
          <Row label="Email">
            {contact.email ? (
              mail ? (
                <a href={mail} className="break-all underline underline-offset-4">
                  {contact.email}
                </a>
              ) : (
                <span className="break-all">{contact.email}</span>
              )
            ) : null}
          </Row>
          <Row label="Phone">
            {contact.phone ? (
              tel ? (
                <a href={tel} className="underline underline-offset-4">
                  {contact.phone}
                </a>
              ) : (
                <span className="break-words">{contact.phone}</span>
              )
            ) : null}
          </Row>
          <Row label="Role">{contact.role_title}</Row>
          <Row label="Company">
            {contact.company_id && contact.company_name ? (
              <Link
                href={`/leads/companies/${contact.company_id}`}
                className="break-words underline underline-offset-4"
              >
                {contact.company_name}
              </Link>
            ) : null}
          </Row>
          <Row label="Notes">
            {contact.notes ? (
              <span className="break-words whitespace-pre-wrap">{contact.notes}</span>
            ) : null}
          </Row>
          <Row label="Where from">
            <span className="break-words">
              {isManualSource(contact.source) ? "Added manually" : `Source: ${contact.source}`}
              {contact.source_retrieved_at
                ? ` · Retrieved ${formatDateTime(contact.source_retrieved_at)}`
                : ""}
            </span>
            {contact.is_sample ? (
              <span className="block text-muted">Fictional demo data, not a real person.</span>
            ) : null}
          </Row>
          <Row label="Last updated">
            <time dateTime={contact.updated_at}>{formatDate(contact.updated_at)}</time>
          </Row>
        </dl>
      </section>

      <section aria-labelledby="contact-leads-h" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="contact-leads-h" className="text-base font-semibold text-fg">
            Leads for this contact
          </h2>
          {leadTotal > 0 ? (
            <Link
              href={`/leads?contact_id=${contact.id}`}
              className="text-sm underline underline-offset-4"
            >
              View in Leads{leadTotal > leads.length ? ` (${leadTotal})` : ""}
            </Link>
          ) : null}
        </div>
        {leads.length === 0 ? (
          <p className="rounded-lg border border-dashed border-line px-4 py-6 text-sm text-muted">
            No active leads are linked to this contact yet.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {leads.map((lead) => (
              <li
                key={lead.id}
                className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-lg border border-line bg-surface px-4 py-3 text-sm"
              >
                <div className="min-w-0">
                  <Link
                    href={`/leads/${lead.id}`}
                    className="font-medium break-words underline underline-offset-4"
                  >
                    {lead.title}
                  </Link>
                  <p className="mt-0.5 text-muted">
                    {lead.next_action ? (
                      <>
                        Next: <span className="break-words">{lead.next_action}</span>
                        {lead.next_action_at ? ` · ${formatDate(lead.next_action_at)}` : ""}
                      </>
                    ) : (
                      "No next action"
                    )}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  <StatusBadge status={lead.status} />
                  <FitBadge band={lead.fit_band} score={lead.fit_score} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {editing ? (
        <EditDrawer
          key={contact.updated_at}
          workspaceId={workspaceId}
          contact={contact}
          companies={companies}
          onClose={() => setEditing(false)}
        />
      ) : null}
      <ConfirmDialog
        open={confirmArchive}
        onOpenChange={setConfirmArchive}
        title="Archive this contact?"
        description="Hidden from lists. Their leads keep the link."
        confirmLabel="Archive"
        destructive
        onConfirm={() => void transition("archive")}
      />
    </div>
  );
}

function Row({ label, children }: { label: string; children?: ReactNode }) {
  return (
    <>
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 text-fg">
        {children || <span className="text-muted">Not recorded</span>}
      </dd>
    </>
  );
}

/* ---------- Edit ---------- */

function EditDrawer({
  workspaceId,
  contact,
  companies,
  onClose,
}: {
  workspaceId: string;
  contact: ContactOut;
  companies: CompanyChoice[];
  onClose: () => void;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const baseline = useMemo(() => formFromContact(contact), [contact]);
  const [form, setForm] = useState<ContactForm>(baseline);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [banner, setBanner] = useState<MutationFailure | null>(null);
  const [pending, setPending] = useState(false);

  const patch = diffContact(baseline, form);
  const dirty = Object.keys(patch).length > 0;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!form.full_name.trim()) {
      setErrors({ full_name: "A contact needs a name." });
      setBanner({
        title: "Some fields need attention",
        text: "Fix the highlighted fields and try again.",
      });
      return;
    }
    if (!dirty) return;
    setPending(true);
    setBanner(null);
    setErrors({});
    try {
      const { error, response } = await browserApi().PATCH(
        "/api/v1/workspaces/{workspace_id}/contacts/{contact_id}",
        {
          params: { path: { workspace_id: workspaceId, contact_id: contact.id } },
          body: patch,
        },
      );
      if (response.ok) {
        toast({ title: "Saved", tone: "success" });
        router.refresh();
        onClose();
        return;
      }
      const out = describeFailure(error, response, "contact");
      if (out) {
        setBanner(out.failure);
        setErrors(out.fields);
      }
    } catch {
      setBanner({ title: "That didn't work", text: toFailure(undefined).message });
    }
    setPending(false);
  }

  return (
    <Drawer
      open
      onOpenChange={(open) => !open && onClose()}
      title="Edit contact"
      description="Only what you change is saved. Clear a field to remove it."
      className="w-[min(30rem,100vw-2rem)]"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
          <Button type="submit" form="contact-edit" disabled={pending || !dirty}>
            Save changes
          </Button>
        </>
      }
    >
      <form
        id="contact-edit"
        onSubmit={submit}
        noValidate
        className="flex flex-col gap-4"
        aria-label="Edit contact"
      >
        {banner ? (
          <Notice tone={banner.reload ? "warning" : "danger"} title={banner.title}>
            {banner.text}
          </Notice>
        ) : null}
        <ContactFields
          form={form}
          setForm={setForm}
          errors={errors}
          companies={companies}
          idPrefix="edit"
        />
      </form>
    </Drawer>
  );
}
