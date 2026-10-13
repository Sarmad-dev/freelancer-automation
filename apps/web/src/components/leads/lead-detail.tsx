"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import {
  Badge,
  Button,
  Checkbox,
  ConfirmDialog,
  Field,
  Input,
  Notice,
  PageHeader,
  Select,
  useToast,
} from "@freelancer-os/ui";
import { browserApi, toFailure } from "@/lib/api-client";
import { describeFailure, type MutationFailure } from "@/lib/mutation-error";
import { FitBreakdown } from "./fit-breakdown";
import { DoNotContactBadge, FitBadge, SampleBadge, StatusBadge } from "./lead-badges";
import { LeadEditDrawer } from "./lead-edit-drawer";
import { LeadWork } from "./lead-work";
import type { OpportunityOut } from "@/components/pipeline/pipeline-model";
import type { TaskOut } from "@/components/tasks/task-model";
import { LeadTimeline } from "./lead-timeline";
import {
  BUDGETS,
  LEAD_STATUSES,
  formatDateTime,
  isOverdue,
  type ActivityOut,
  type CompanyOut,
  type ContactOut,
  type LeadDetail as Lead,
  type StageOut,
  type TagOut,
} from "./lead-model";

const card = "rounded-lg border border-line bg-surface p-5";
const MAX_TAGS = 20;
const EMAIL = /^[^\s<>"'`,;()\\]+@[^\s<>"'`,;()\\]+$/;

type Failure = MutationFailure;

function Empty() {
  return <span className="text-muted">Not set</span>;
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 break-words text-fg">{children}</dd>
    </>
  );
}

export function LeadDetail({
  workspaceId,
  lead: initialLead,
  activities,
  tags,
  stages,
  companies,
  contacts,
  deals,
  tasks,
  timezone,
  canEdit,
  now,
}: {
  workspaceId: string;
  lead: Lead;
  activities: { items: ActivityOut[]; total: number };
  tags: TagOut[];
  stages: StageOut[];
  companies: CompanyOut[];
  contacts: ContactOut[];
  deals: OpportunityOut[];
  tasks: TaskOut[];
  /** Zone used to show new tasks' times (the workspace's). */
  timezone: string;
  canEdit: boolean;
  /** ISO time from the server, so "overdue" is computed the same on server and client. */
  now: string;
}) {
  const router = useRouter();
  const { toast } = useToast();

  // Render from what the last mutation returned; take the server's data again once it refreshes.
  const [lead, setLead] = useState(initialLead);
  const [seen, setSeen] = useState(initialLead);
  if (initialLead !== seen) {
    setSeen(initialLead);
    setLead(initialLead);
  }

  const [busy, setBusy] = useState<string | null>(null);
  const [banner, setBanner] = useState<Failure | null>(null);
  const [fitError, setFitError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [confirmArchive, setConfirmArchive] = useState(false);

  const archived = lead.archived_at != null;
  const editable = canEdit && !archived;
  const overdue = isOverdue(lead, new Date(now));
  const path = { workspace_id: workspaceId, lead_id: lead.id };

  /** One way to run a mutation that answers with the updated lead. */
  async function mutate(
    key: string,
    run: () => Promise<{ data?: Lead; error?: unknown; response: Response }>,
    done: { title: string; description?: string },
    onFail: (f: Failure) => void = setBanner,
  ): Promise<boolean> {
    setBusy(key);
    setBanner(null);
    setFitError(null);
    let ok = false;
    try {
      const { data, error, response } = await run();
      if (response.ok && data) {
        setLead(data);
        toast({ ...done, tone: "success" });
        router.refresh();
        ok = true;
      } else {
        const out = describeFailure(error, response, "lead");
        if (out) onFail(out.failure);
      }
    } catch {
      onFail({ title: "That didn't work", text: toFailure(undefined).message });
    }
    setBusy(null);
    return ok;
  }

  const api = "/api/v1/workspaces/{workspace_id}/leads/{lead_id}" as const;

  const changeStatus = (status: string) =>
    mutate(
      "status",
      () =>
        browserApi().PATCH(api, {
          params: { path },
          body: { status: status as (typeof LEAD_STATUSES)[number]["value"] },
        }),
      { title: "Status updated" },
    );
  const changeStage = (stageId: string) =>
    mutate(
      "stage",
      () => browserApi().PATCH(api, { params: { path }, body: { stage_id: stageId } }),
      { title: "Stage updated" },
    );
  const archive = () =>
    mutate(
      "archive",
      () =>
        browserApi().POST("/api/v1/workspaces/{workspace_id}/leads/{lead_id}/archive", {
          params: { path },
        }),
      { title: "Lead archived", description: "It's read-only now. You can restore it any time." },
    );
  const restore = () =>
    mutate(
      "archive",
      () =>
        browserApi().POST("/api/v1/workspaces/{workspace_id}/leads/{lead_id}/restore", {
          params: { path },
        }),
      { title: "Lead restored" },
    );
  const rescore = () =>
    mutate(
      "score",
      () =>
        browserApi().POST("/api/v1/workspaces/{workspace_id}/leads/{lead_id}/score", {
          params: { path },
        }),
      { title: "Score recalculated" },
      (f) => setFitError(f.text),
    );

  const company = lead.company;
  const contact = lead.contact;
  const contactEmail = contact?.email && EMAIL.test(contact.email) ? contact.email : null;
  const budget = BUDGETS.find((b) => b.value === lead.budget_signal)?.label ?? lead.budget_signal;

  return (
    <div className="flex flex-col gap-6">
      <Link
        href="/leads"
        className="inline-flex w-fit items-center gap-1.5 text-sm text-muted underline-offset-4 hover:text-fg hover:underline"
      >
        <ArrowLeft className="size-4" aria-hidden />
        Back to leads
      </Link>

      <PageHeader
        title={lead.title}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <StatusBadge status={lead.status} />
            <FitBadge band={lead.fit_band} score={lead.fit_score} />
            {lead.is_sample ? <SampleBadge /> : null}
            {lead.do_not_contact ? <DoNotContactBadge /> : null}
            {archived ? <Badge tone="neutral">Archived</Badge> : null}
          </span>
        }
        actions={
          canEdit ? (
            <>
              <Button
                variant="secondary"
                onClick={() => setEditing(true)}
                disabled={archived || busy !== null}
              >
                Edit
              </Button>
              {archived ? (
                <Button
                  variant="secondary"
                  onClick={() => void restore()}
                  disabled={busy !== null}
                  aria-busy={busy === "archive"}
                >
                  {busy === "archive" ? "Restoring…" : "Restore"}
                </Button>
              ) : (
                <Button
                  variant="secondary"
                  onClick={() => setConfirmArchive(true)}
                  disabled={busy !== null}
                  aria-busy={busy === "archive"}
                >
                  {busy === "archive" ? "Archiving…" : "Archive"}
                </Button>
              )}
            </>
          ) : undefined
        }
      />

      {lead.do_not_contact ? (
        <Notice tone="danger" title="Do not contact">
          This contact is on your do-not-contact list. Nothing will be sent to them, by you or by
          any automation.
        </Notice>
      ) : null}
      {archived ? (
        <Notice tone="info" title="This lead is archived">
          Archived leads are read-only.{" "}
          {canEdit ? "Restore it to make changes." : "The workspace owner can restore it."}
        </Notice>
      ) : null}
      {!canEdit ? (
        <Notice tone="info" title="View only">
          Only the workspace owner can change leads.
        </Notice>
      ) : null}
      {banner ? (
        <Notice tone="danger" title={banner.title}>
          {banner.text}
        </Notice>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="flex min-w-0 flex-col gap-6">
          <section aria-labelledby="summary-h" className={card}>
            <h2 id="summary-h" className="text-base font-semibold text-fg">
              Details
            </h2>
            <dl className="mt-4 grid grid-cols-[auto_minmax(0,1fr)] gap-x-6 gap-y-2 text-sm">
              <Row label="Company">
                {company ? (
                  <Link
                    href={`/leads/companies/${company.id}`}
                    className="underline underline-offset-4"
                  >
                    {company.name}
                  </Link>
                ) : (
                  <Empty />
                )}
              </Row>
              <Row label="Contact">
                {contact ? (
                  <span className="flex flex-col">
                    <Link
                      href={`/leads/contacts/${contact.id}`}
                      className="w-fit underline underline-offset-4"
                    >
                      {contact.full_name}
                    </Link>
                    {contact.email ? (
                      contactEmail ? (
                        <a
                          href={`mailto:${contactEmail}`}
                          className="w-fit underline underline-offset-4"
                        >
                          {contactEmail}
                        </a>
                      ) : (
                        <span>{contact.email}</span>
                      )
                    ) : null}
                  </span>
                ) : (
                  <Empty />
                )}
              </Row>
              <Row label="Source">
                {lead.source ? (
                  <>
                    {lead.source}
                    {lead.source_retrieved_at
                      ? ` · retrieved ${formatDateTime(lead.source_retrieved_at)}`
                      : ""}
                  </>
                ) : (
                  <span className="text-muted">Not recorded</span>
                )}
              </Row>
              <Row label="Industry">{lead.industry ?? <Empty />}</Row>
              <Row label="Location">{lead.location ?? <Empty />}</Row>
              <Row label="Budget signal">{budget ?? <Empty />}</Row>
              <Row label="Next action">
                {lead.next_action || lead.next_action_at ? (
                  <span className="flex flex-wrap items-center gap-2">
                    <span>{lead.next_action ?? "No description"}</span>
                    {lead.next_action_at ? (
                      <span className="text-muted">
                        <time dateTime={lead.next_action_at}>
                          {formatDateTime(lead.next_action_at)}
                        </time>
                      </span>
                    ) : null}
                    {overdue ? <Badge tone="danger">Overdue</Badge> : null}
                  </span>
                ) : (
                  <Empty />
                )}
              </Row>
              <Row label="Created">
                <time dateTime={lead.created_at}>{formatDateTime(lead.created_at)}</time>
              </Row>
              <Row label="Updated">
                <time dateTime={lead.updated_at}>{formatDateTime(lead.updated_at)}</time>
              </Row>
            </dl>
            <h3 className="mt-5 text-sm font-medium text-fg">Notes</h3>
            {lead.notes ? (
              <p className="mt-1 text-sm break-words whitespace-pre-wrap text-fg">{lead.notes}</p>
            ) : (
              <p className="mt-1 text-sm text-muted">No notes.</p>
            )}
          </section>

          <FitBreakdown
            explanation={lead.fit_explanation}
            score={lead.fit_score}
            band={lead.fit_band}
            stale={lead.fit_stale}
            canEdit={editable}
            onRescore={() => void rescore()}
            rescoring={busy === "score"}
            rescoreError={fitError}
          />

          <LeadTimeline
            workspaceId={workspaceId}
            leadId={lead.id}
            activities={activities.items}
            total={activities.total}
            canLog={editable}
            isOwner={canEdit}
          />
        </div>

        <div className="flex min-w-0 flex-col gap-6">
          <section aria-labelledby="pipeline-h" className={card}>
            <h2 id="pipeline-h" className="text-base font-semibold text-fg">
              Status and stage
            </h2>
            <div
              className="mt-4 flex flex-col gap-4"
              aria-busy={busy === "status" || busy === "stage"}
            >
              <Field label="Status">
                {(p) => (
                  <Select
                    {...p}
                    value={lead.status}
                    disabled={!editable || busy !== null}
                    onChange={(e) => void changeStatus(e.target.value)}
                  >
                    {LEAD_STATUSES.some((s) => s.value === lead.status) ? null : (
                      <option value={lead.status}>{lead.status}</option>
                    )}
                    {LEAD_STATUSES.map((s) => (
                      <option key={s.value} value={s.value}>
                        {s.label}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              <Field label="Pipeline stage">
                {(p) => (
                  <Select
                    {...p}
                    value={lead.stage?.id ?? ""}
                    disabled={!editable || busy !== null}
                    onChange={(e) => e.target.value && void changeStage(e.target.value)}
                  >
                    {lead.stage ? null : (
                      <option value="" disabled>
                        No stage
                      </option>
                    )}
                    {stages.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              <p className="text-[13px] text-muted">
                Status and stage move together, and each change is logged in the activity.
              </p>
            </div>
          </section>

          <LeadWork
            workspaceId={workspaceId}
            leadId={lead.id}
            leadTitle={lead.title}
            deals={deals}
            tasks={tasks}
            stages={stages}
            timezone={timezone}
            canEdit={editable}
          />

          <TagsSection
            key={lead.tags.map((t) => t.id).join(",")}
            workspaceId={workspaceId}
            lead={lead}
            allTags={tags}
            canEdit={editable}
            busy={busy !== null}
            onSave={(ids) =>
              mutate(
                "tags",
                () =>
                  browserApi().PUT("/api/v1/workspaces/{workspace_id}/leads/{lead_id}/tags", {
                    params: { path },
                    body: { tag_ids: ids },
                  }),
                { title: "Tags saved" },
              )
            }
          />
        </div>
      </div>

      {editing && editable ? (
        <LeadEditDrawer
          key={lead.updated_at}
          workspaceId={workspaceId}
          lead={lead}
          companies={companies}
          contacts={contacts}
          onClose={() => setEditing(false)}
        />
      ) : null}
      <ConfirmDialog
        open={confirmArchive}
        onOpenChange={setConfirmArchive}
        title="Archive this lead?"
        description="It disappears from your lead list and becomes read-only. Nothing is deleted, and you can restore it any time."
        confirmLabel="Archive"
        destructive
        onConfirm={() => void archive()}
      />
    </div>
  );
}

/* ---------- Tags ---------- */

function TagsSection({
  workspaceId,
  lead,
  allTags,
  canEdit,
  busy,
  onSave,
}: {
  workspaceId: string;
  lead: Lead;
  allTags: TagOut[];
  canEdit: boolean;
  busy: boolean;
  onSave: (ids: string[]) => Promise<boolean>;
}) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(() => new Set(lead.tags.map((t) => t.id)));
  const [created, setCreated] = useState<{ id: string; name: string }[]>([]);
  const [newName, setNewName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<string | undefined>();
  const [adding, setAdding] = useState(false);

  const options = useMemo(() => {
    const map = new Map<string, string>();
    for (const t of allTags) map.set(t.id, t.name);
    for (const t of lead.tags) map.set(t.id, t.name);
    for (const t of created) map.set(t.id, t.name);
    return [...map]
      .map(([id, name]) => ({ id, name }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [allTags, lead.tags, created]);

  const tooMany = selected.size > MAX_TAGS;

  async function addTag(e: FormEvent) {
    e.preventDefault();
    const name = newName.trim();
    if (!name || adding) return;
    setAdding(true);
    setError(null);
    setFieldError(undefined);
    try {
      const {
        data,
        error: err,
        response,
      } = await browserApi().POST("/api/v1/workspaces/{workspace_id}/tags", {
        params: { path: { workspace_id: workspaceId } },
        body: { name },
      });
      if (response.ok && data) {
        setCreated((c) => [...c, { id: data.id, name: data.name }]);
        setSelected((s) => new Set(s).add(data.id));
        setNewName("");
        toast({
          title: "Tag created",
          description: "Tick Save tags to add it to this lead.",
          tone: "success",
        });
      } else {
        const out = describeFailure(err, response, "tag");
        if (out) {
          if (out.fields.name) setFieldError(out.fields.name);
          else setError(out.failure.text);
        }
      }
    } catch {
      setError(toFailure(undefined).message);
    }
    setAdding(false);
  }

  async function save() {
    setError(null);
    const ok = await onSave([...selected]);
    if (ok) setOpen(false);
    else setError("The tags weren't saved. See the message at the top of the page.");
  }

  return (
    <section aria-labelledby="tags-h" className={card}>
      <div className="flex items-center justify-between gap-2">
        <h2 id="tags-h" className="text-base font-semibold text-fg">
          Tags
        </h2>
        {canEdit && !open ? (
          <Button variant="ghost" size="sm" onClick={() => setOpen(true)} disabled={busy}>
            Edit tags
          </Button>
        ) : null}
      </div>

      {lead.tags.length === 0 ? (
        <p className="mt-3 text-sm text-muted">No tags yet.</p>
      ) : (
        <ul className="mt-3 flex flex-wrap gap-2" aria-label="Tags on this lead">
          {lead.tags.map((t) => (
            <li key={t.id}>
              <Link
                href={`/leads?tag_id=${encodeURIComponent(t.id)}`}
                className="rounded-full"
                title={`Show leads tagged ${t.name}`}
              >
                <Badge tone="neutral" className="hover:border-muted">
                  {t.name}
                </Badge>
              </Link>
            </li>
          ))}
        </ul>
      )}

      {open && canEdit ? (
        <div className="mt-4 flex flex-col gap-3 border-t border-line pt-4">
          {error ? (
            <Notice tone="danger" title="Couldn't update tags">
              {error}
            </Notice>
          ) : null}
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-sm font-medium text-fg">Choose tags</legend>
            {options.length === 0 ? (
              <p className="text-sm text-muted">
                You haven&apos;t made any tags yet. Add one below.
              </p>
            ) : (
              options.map((t) => (
                <Checkbox
                  key={t.id}
                  label={t.name}
                  checked={selected.has(t.id)}
                  disabled={busy}
                  onCheckedChange={(checked) =>
                    setSelected((s) => {
                      const next = new Set(s);
                      if (checked === true) next.add(t.id);
                      else next.delete(t.id);
                      return next;
                    })
                  }
                />
              ))
            )}
            {tooMany ? (
              <p role="alert" className="text-[13px] text-danger">
                A lead can have at most {MAX_TAGS} tags.
              </p>
            ) : null}
          </fieldset>
          <form
            onSubmit={(e) => void addTag(e)}
            aria-label="Add a tag"
            className="flex items-end gap-2"
          >
            <Field
              label="New tag"
              className="flex-1"
              {...(fieldError ? { error: fieldError } : {})}
            >
              {(p) => (
                <Input
                  {...p}
                  value={newName}
                  maxLength={50}
                  onChange={(e) => setNewName(e.target.value)}
                />
              )}
            </Field>
            <Button type="submit" variant="secondary" disabled={adding || !newName.trim()}>
              Add tag
            </Button>
          </form>
          <div className="flex gap-2">
            <Button onClick={() => void save()} disabled={busy || tooMany} aria-busy={busy}>
              Save tags
            </Button>
            <Button
              variant="secondary"
              onClick={() => {
                setSelected(new Set(lead.tags.map((t) => t.id)));
                setOpen(false);
                setError(null);
              }}
              disabled={busy}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
