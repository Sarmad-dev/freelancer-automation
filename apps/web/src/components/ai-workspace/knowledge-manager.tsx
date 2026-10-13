"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  Badge,
  Button,
  ConfirmDialog,
  Drawer,
  EmptyState,
  Field,
  Input,
  Notice,
  Select,
  Switch,
  Table,
  TableContainer,
  Td,
  Textarea,
  Th,
  useToast,
} from "@freelancer-os/ui";
import { browserApi, toFailure } from "@/lib/api-client";
import { describeFailure, type MutationFailure } from "@/lib/mutation-error";
import { formatDate, safeExternalUrl } from "@/lib/safe-url";
import {
  KINDS,
  PAGE_SIZE,
  SOURCE_LABELS,
  STATUSES,
  diffItem,
  emptyForm,
  formFromItem,
  kindLabel,
  queryHref,
  statusMeta,
  type ItemForm,
  type Kind,
  type KnowledgeOut,
  type KnowledgeQuery,
  type KnowledgeVersionOut,
} from "./knowledge-model";

type Failure = MutationFailure;

const failureFrom = describeFailure;

function ItemFields({
  form,
  setForm,
  errors,
  idPrefix,
}: {
  form: ItemForm;
  setForm: (f: ItemForm) => void;
  errors: Record<string, string>;
  idPrefix: string;
}) {
  const err = (k: string) => (errors[k] ? { error: errors[k] } : {});
  return (
    <div className="flex flex-col gap-4" data-testid={`${idPrefix}-fields`}>
      <Field label="Type" {...err("kind")}>
        {(p) => (
          <Select
            {...p}
            value={form.kind}
            onChange={(e) => setForm({ ...form, kind: e.target.value as Kind })}
          >
            {KINDS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field label="Title" required {...err("title")}>
        {(p) => (
          <Input
            {...p}
            value={form.title}
            maxLength={200}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
          />
        )}
      </Field>
      <Field
        label="What is true"
        required
        hint="Write only what you can stand behind. The AI may repeat this wording, so no guesses."
        {...err("content")}
      >
        {(p) => (
          <Textarea
            {...p}
            rows={6}
            value={form.content}
            maxLength={4000}
            onChange={(e) => setForm({ ...form, content: e.target.value })}
          />
        )}
      </Field>
      <Field
        label="Where it comes from"
        hint="A public link or a short label, e.g. “Client call notes, March”."
        {...err("source_ref")}
      >
        {(p) => (
          <Input
            {...p}
            value={form.source_ref}
            maxLength={500}
            onChange={(e) => setForm({ ...form, source_ref: e.target.value })}
          />
        )}
      </Field>
    </div>
  );
}

function SourceRef({ value }: { value: string | null }) {
  if (!value) return <span className="text-muted">None recorded</span>;
  const href = safeExternalUrl(value);
  return href ? (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer nofollow"
      className="break-all underline underline-offset-4"
    >
      {value}
    </a>
  ) : (
    <span className="break-words">{value}</span>
  );
}

export function KnowledgeManager({
  workspaceId,
  items,
  total,
  stats,
  query,
  canEdit,
}: {
  workspaceId: string;
  items: KnowledgeOut[];
  total: number;
  stats: Record<string, number>;
  query: KnowledgeQuery;
  canEdit: boolean;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const [openId, setOpenId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [importing, setImporting] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  const selected = items.find((i) => i.id === openId) ?? null;
  const filtered = Boolean(query.status || query.kind || query.q);
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const reviewCount = (stats.pending_review ?? 0) + (stats.draft ?? 0);

  async function toggle(item: KnowledgeOut, next: boolean) {
    setBusyId(item.id);
    setRowError(null);
    try {
      const { error, response } = await browserApi().PATCH(
        "/api/v1/workspaces/{workspace_id}/knowledge/{item_id}",
        {
          params: { path: { workspace_id: workspaceId, item_id: item.id } },
          body: { is_enabled: next },
        },
      );
      if (response.ok) {
        toast({
          title: next ? "Switched on" : "Switched off",
          description: next ? "The AI may use it once approved." : "The AI won't use it.",
          tone: "success",
        });
        router.refresh();
      } else {
        const out = failureFrom(error, response);
        if (out) setRowError(out.failure.text);
      }
    } catch {
      setRowError(toFailure(undefined).message);
    }
    setBusyId(null);
  }

  return (
    <div className="flex flex-col gap-5">
      {!canEdit ? (
        <Notice tone="info" title="View only">
          Only the workspace owner can add, edit or approve knowledge.
        </Notice>
      ) : null}
      {reviewCount > 0 ? (
        <Notice
          tone="warning"
          title={`${reviewCount} item${reviewCount === 1 ? "" : "s"} waiting for review`}
        >
          Nothing here is used by the AI until you approve it.{" "}
          <Link
            className="underline underline-offset-4"
            href={queryHref({ status: "pending_review", kind: "", q: "", page: 1 })}
          >
            Show items to review
          </Link>
        </Notice>
      ) : null}

      <div className="flex flex-wrap items-end gap-3">
        <form
          action="/ai-workspace/knowledge"
          method="get"
          role="search"
          aria-label="Filter knowledge"
          className="flex flex-1 flex-wrap items-end gap-3"
        >
          <Field label="Search" className="min-w-48 flex-1 sm:max-w-xs">
            {(p) => <Input {...p} name="q" type="search" defaultValue={query.q} maxLength={100} />}
          </Field>
          <Field label="Status">
            {(p) => (
              <Select {...p} name="status" defaultValue={query.status}>
                <option value="">All</option>
                {STATUSES.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                    {stats[s.value] !== undefined ? ` (${stats[s.value]})` : ""}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Type">
            {(p) => (
              <Select {...p} name="kind" defaultValue={query.kind}>
                <option value="">All</option>
                {KINDS.map((k) => (
                  <option key={k.value} value={k.value}>
                    {k.label}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Button type="submit" variant="secondary">
            Apply
          </Button>
          {filtered ? (
            <Link
              href="/ai-workspace/knowledge"
              className="inline-flex h-9 items-center px-2 text-sm text-muted underline underline-offset-4 hover:text-fg"
            >
              Clear filters
            </Link>
          ) : null}
        </form>
        {canEdit ? (
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setImporting(true)}>
              Import text
            </Button>
            <Button onClick={() => setAdding(true)}>Add item</Button>
          </div>
        ) : null}
      </div>

      {rowError ? (
        <Notice tone="danger" title="Couldn't update that item">
          {rowError}
        </Notice>
      ) : null}

      {items.length === 0 ? (
        filtered ? (
          <EmptyState
            title="Nothing matches those filters"
            description="Try a different search, or clear the filters."
          >
            <Link
              href="/ai-workspace/knowledge"
              className="inline-flex h-9 items-center rounded-md border border-line bg-elevated px-3 text-sm font-medium text-fg"
            >
              Clear filters
            </Link>
          </EmptyState>
        ) : (
          <EmptyState
            title="No knowledge yet"
            description="Add facts about your work (services, results, case studies, pricing rules). Each one is reviewed by you before any draft may use it. You don't need an AI provider for this."
          >
            {canEdit ? <Button onClick={() => setAdding(true)}>Add your first item</Button> : null}
          </EmptyState>
        )
      ) : (
        <TableContainer>
          <Table aria-label="Knowledge items">
            <caption className="sr-only">
              Knowledge items, {total} in total. Only approved items that are switched on are used
              by the AI.
            </caption>
            <thead>
              <tr>
                <Th>Title</Th>
                <Th>Type</Th>
                <Th>Source</Th>
                <Th>Status</Th>
                <Th>Used by AI</Th>
                <Th>Updated</Th>
                <Th>
                  <span className="sr-only">Actions</span>
                </Th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => {
                const meta = statusMeta(item.status);
                const approved = item.status === "approved";
                return (
                  <tr key={item.id}>
                    <Td className="max-w-xs font-medium">
                      <span className="line-clamp-2 break-words">{item.title}</span>
                    </Td>
                    <Td className="whitespace-nowrap">{kindLabel(item.kind)}</Td>
                    <Td className="whitespace-nowrap text-muted">
                      {SOURCE_LABELS[item.source_type] ?? item.source_type}
                    </Td>
                    <Td>
                      <Badge tone={meta.tone}>{meta.label}</Badge>
                    </Td>
                    <Td>
                      <div className="flex items-center gap-2">
                        <Switch
                          checked={item.is_enabled}
                          disabled={!canEdit || busyId === item.id}
                          label={`${item.is_enabled ? "Switch off" : "Switch on"}: ${item.title}`}
                          onCheckedChange={(next) => void toggle(item, next)}
                        />
                        <span className="text-xs text-muted">
                          {approved && item.is_enabled
                            ? "In use"
                            : !approved
                              ? "Not approved"
                              : "Off"}
                        </span>
                      </div>
                    </Td>
                    <Td className="whitespace-nowrap text-muted">
                      <time dateTime={item.updated_at}>{formatDate(item.updated_at)}</time>
                    </Td>
                    <Td className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setOpenId(item.id)}
                        aria-label={`${canEdit ? (approved ? "Edit" : "Review") : "View"}: ${item.title}`}
                      >
                        {canEdit ? (approved ? "Edit" : "Review") : "View"}
                      </Button>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        </TableContainer>
      )}

      {total > PAGE_SIZE ? (
        <nav aria-label="Pagination" className="flex items-center justify-between gap-4 text-sm">
          <p className="text-muted">
            Page {query.page} of {pageCount} · {total} items
          </p>
          <div className="flex gap-2">
            {query.page > 1 ? (
              <Link
                rel="prev"
                href={queryHref({ ...query, page: query.page - 1 })}
                className="inline-flex h-8 items-center rounded-md border border-line bg-elevated px-3 text-[13px] font-medium text-fg"
              >
                Previous
              </Link>
            ) : null}
            {query.page < pageCount ? (
              <Link
                rel="next"
                href={queryHref({ ...query, page: query.page + 1 })}
                className="inline-flex h-8 items-center rounded-md border border-line bg-elevated px-3 text-[13px] font-medium text-fg"
              >
                Next
              </Link>
            ) : null}
          </div>
        </nav>
      ) : null}

      {selected ? (
        <ItemDrawer
          key={`${selected.id}:${selected.version}:${selected.updated_at}`}
          workspaceId={workspaceId}
          item={selected}
          canEdit={canEdit}
          onClose={() => setOpenId(null)}
        />
      ) : null}
      {adding ? <AddDrawer workspaceId={workspaceId} onClose={() => setAdding(false)} /> : null}
      {importing ? (
        <ImportDrawer workspaceId={workspaceId} onClose={() => setImporting(false)} />
      ) : null}
    </div>
  );
}

/* ---------- Review / edit ---------- */

function ItemDrawer({
  workspaceId,
  item,
  canEdit,
  onClose,
}: {
  workspaceId: string;
  item: KnowledgeOut;
  canEdit: boolean;
  onClose: () => void;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const baseline = useMemo(() => formFromItem(item), [item]);
  const [form, setForm] = useState<ItemForm>(baseline);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [banner, setBanner] = useState<Failure | null>(null);
  const [pending, setPending] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [history, setHistory] = useState<KnowledgeVersionOut[] | null>(null);
  const [historyError, setHistoryError] = useState(false);

  const patch = diffItem(baseline, form);
  const dirty = Object.keys(patch).length > 0;
  const meta = statusMeta(item.status);
  const path = { workspace_id: workspaceId, item_id: item.id };
  const base = "/api/v1/workspaces/{workspace_id}/knowledge/{item_id}" as const;

  useEffect(() => {
    let live = true;
    browserApi()
      .GET("/api/v1/workspaces/{workspace_id}/knowledge/{item_id}/versions", {
        params: { path },
      })
      .then((r) => {
        if (!live) return;
        if (r.data) setHistory(r.data);
        else setHistoryError(true);
      })
      .catch(() => live && setHistoryError(true));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id, item.version]);

  async function run(
    action: () => Promise<{ error?: unknown; response: Response }>,
    done: { title: string; description?: string },
    closeAfter = true,
  ) {
    setPending(true);
    setBanner(null);
    setErrors({});
    try {
      const { error, response } = await action();
      if (response.ok) {
        toast({ ...done, tone: "success" });
        router.refresh();
        if (closeAfter) onClose();
      } else {
        const out = failureFrom(error, response);
        if (out) {
          setBanner(out.failure);
          setErrors(out.fields);
        }
      }
    } catch {
      setBanner({ title: "That didn't work", text: toFailure(undefined).message });
    }
    setPending(false);
  }

  const save = (e: FormEvent) => {
    e.preventDefault();
    if (!dirty || !canEdit) return;
    void run(
      () =>
        browserApi().PATCH(base, {
          params: { path },
          body: { ...patch, expected_version: item.version },
        }),
      {
        title: "Saved",
        description:
          item.status === "approved"
            ? "Edited facts go back to review before the AI uses them again."
            : "Review it, then approve.",
      },
    );
  };
  const approve = () =>
    run(
      () =>
        browserApi().POST("/api/v1/workspaces/{workspace_id}/knowledge/{item_id}/approve", {
          params: { path },
          body: { version: item.version },
        }),
      { title: "Approved", description: "The AI may now use this exact wording." },
    );
  const reject = () =>
    run(
      () =>
        browserApi().POST("/api/v1/workspaces/{workspace_id}/knowledge/{item_id}/reject", {
          params: { path },
        }),
      { title: "Rejected", description: "Kept for reference. The AI will not use it." },
    );
  const remove = () =>
    run(() => browserApi().DELETE(base, { params: { path } }), {
      title: "Deleted",
      description: "The item and its history are gone.",
    });

  const canApprove = canEdit && item.status !== "approved" && item.status !== "rejected" && !dirty;

  return (
    <>
      <Drawer
        open
        onOpenChange={(open) => !open && onClose()}
        title={
          canEdit
            ? item.status === "approved"
              ? "Edit knowledge"
              : "Review knowledge"
            : "Knowledge"
        }
        description="Check every word. Approval covers exactly this version."
        className="w-[min(34rem,100vw-2rem)]"
        footer={
          canEdit ? (
            <>
              <Button variant="danger" onClick={() => setConfirmDelete(true)} disabled={pending}>
                Delete
              </Button>
              <div className="flex-1" />
              {item.status !== "rejected" ? (
                <Button variant="secondary" onClick={() => void reject()} disabled={pending}>
                  Reject
                </Button>
              ) : null}
              <Button
                variant="secondary"
                type="submit"
                form="knowledge-edit"
                disabled={pending || !dirty}
              >
                Save changes
              </Button>
              {item.status !== "approved" && item.status !== "rejected" ? (
                <Button onClick={() => void approve()} disabled={pending || !canApprove}>
                  Approve this version
                </Button>
              ) : null}
            </>
          ) : undefined
        }
      >
        <div className="flex flex-col gap-5">
          {banner ? (
            <Notice tone={banner.reload ? "warning" : "danger"} title={banner.title}>
              {banner.text}
              {banner.reload ? (
                <>
                  {" "}
                  <button
                    type="button"
                    className="underline underline-offset-4"
                    onClick={() => {
                      router.refresh();
                      onClose();
                    }}
                  >
                    Close and reload
                  </button>
                </>
              ) : null}
            </Notice>
          ) : null}

          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
            <dt className="text-muted">Status</dt>
            <dd>
              <Badge tone={meta.tone}>{meta.label}</Badge>{" "}
              {item.status === "approved" && !item.is_enabled ? (
                <span className="text-muted">(switched off)</span>
              ) : null}
            </dd>
            <dt className="text-muted">Origin</dt>
            <dd>{SOURCE_LABELS[item.source_type] ?? item.source_type}</dd>
            <dt className="text-muted">Source</dt>
            <dd>
              <SourceRef value={item.source_ref} />
            </dd>
            <dt className="text-muted">Version</dt>
            <dd>{item.version}</dd>
            <dt className="text-muted">Last changed</dt>
            <dd>{formatDate(item.updated_at)}</dd>
            {item.approved_at ? (
              <>
                <dt className="text-muted">Approved</dt>
                <dd>{formatDate(item.approved_at)}</dd>
              </>
            ) : null}
          </dl>

          {item.source_type === "extracted" && item.status === "pending_review" ? (
            <Notice tone="info" title="Extracted, not yet verified">
              This was pulled from your material automatically. Compare it with the original, fix
              anything inaccurate, then approve.
            </Notice>
          ) : null}
          {item.status === "approved" && canEdit ? (
            <Notice tone="info" title="Editing sends it back to review">
              Saving a change to approved wording makes it “Needs review” until you approve the new
              version.
            </Notice>
          ) : null}

          <form id="knowledge-edit" onSubmit={save} aria-label="Knowledge item">
            {canEdit ? (
              <ItemFields form={form} setForm={setForm} errors={errors} idPrefix="edit" />
            ) : (
              <div className="flex flex-col gap-3 text-sm">
                <p className="font-medium text-fg">{item.title}</p>
                <p className="break-words whitespace-pre-wrap text-fg">{item.content}</p>
              </div>
            )}
          </form>
          {dirty ? (
            <p role="status" className="text-sm text-muted">
              Unsaved edits. Save before approving.
            </p>
          ) : null}

          <section aria-labelledby="history-h" className="border-t border-line pt-4">
            <h3 id="history-h" className="text-sm font-medium text-fg">
              History
            </h3>
            {historyError ? (
              <p className="mt-2 text-sm text-muted">Couldn&apos;t load history.</p>
            ) : history === null ? (
              <p className="mt-2 text-sm text-muted">Loading…</p>
            ) : (
              <ol className="mt-2 flex flex-col gap-2">
                {history.map((v) => (
                  <li key={v.version} className="rounded-md border border-line p-2.5 text-sm">
                    <p className="text-xs text-muted">
                      Version {v.version} · {formatDate(v.created_at)}
                      {v.version === item.version ? " · current" : ""}
                    </p>
                    <p className="mt-1 font-medium text-fg">{v.title}</p>
                    <p className="mt-0.5 line-clamp-3 break-words whitespace-pre-wrap text-muted">
                      {v.content}
                    </p>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>
      </Drawer>
      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title="Delete this item?"
        description="It will be removed along with its history. Drafts that already used it are not changed."
        confirmLabel="Delete"
        destructive
        onConfirm={() => void remove()}
      />
    </>
  );
}

/* ---------- Add ---------- */

function AddDrawer({ workspaceId, onClose }: { workspaceId: string; onClose: () => void }) {
  const router = useRouter();
  const { toast } = useToast();
  const [form, setForm] = useState<ItemForm>(emptyForm());
  const [approveNow, setApproveNow] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [banner, setBanner] = useState<Failure | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setPending(true);
    setBanner(null);
    setErrors({});
    try {
      const { error, response } = await browserApi().POST(
        "/api/v1/workspaces/{workspace_id}/knowledge",
        {
          params: { path: { workspace_id: workspaceId } },
          body: {
            kind: form.kind,
            title: form.title,
            content: form.content,
            ...(form.source_ref.trim() ? { source_ref: form.source_ref.trim() } : {}),
            approve_now: approveNow,
          },
        },
      );
      if (response.ok) {
        toast({
          title: approveNow ? "Added and approved" : "Added as a draft",
          description: approveNow ? undefined : "Approve it when you're happy with the wording.",
          tone: "success",
        });
        router.refresh();
        onClose();
        return;
      }
      const out = failureFrom(error, response);
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
      title="Add knowledge"
      description="One true statement per item works best."
      className="w-[min(34rem,100vw-2rem)]"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
          <Button type="submit" form="knowledge-add" disabled={pending}>
            {approveNow ? "Add and approve" : "Add as draft"}
          </Button>
        </>
      }
    >
      <form
        id="knowledge-add"
        onSubmit={submit}
        className="flex flex-col gap-4"
        aria-label="Add knowledge"
      >
        {banner ? (
          <Notice tone="danger" title={banner.title}>
            {banner.text}
          </Notice>
        ) : null}
        <ItemFields form={form} setForm={setForm} errors={errors} idPrefix="add" />
        <label className="flex items-start gap-3 text-sm text-fg">
          <input
            type="checkbox"
            className="mt-0.5 size-4 accent-[var(--fos-accent)]"
            checked={approveNow}
            onChange={(e) => setApproveNow(e.target.checked)}
          />
          <span>
            I&apos;ve checked this and it&apos;s accurate. Approve it now.
            <span className="block text-[13px] text-muted">
              Otherwise it&apos;s saved as a draft and the AI won&apos;t use it until you approve
              it.
            </span>
          </span>
        </label>
      </form>
    </Drawer>
  );
}

/* ---------- Import ---------- */

function ImportDrawer({ workspaceId, onClose }: { workspaceId: string; onClose: () => void }) {
  const router = useRouter();
  const { toast } = useToast();
  const [label, setLabel] = useState("");
  const [text, setText] = useState("");
  const [kind, setKind] = useState<Kind>("fact");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [banner, setBanner] = useState<Failure | null>(null);
  const [pending, setPending] = useState(false);
  const err = (k: string) => (errors[k] ? { error: errors[k] } : {});

  async function submit(e: FormEvent) {
    e.preventDefault();
    setPending(true);
    setBanner(null);
    setErrors({});
    try {
      const { data, error, response } = await browserApi().POST(
        "/api/v1/workspaces/{workspace_id}/knowledge/import-text",
        {
          params: { path: { workspace_id: workspaceId } },
          body: { source_label: label, text, kind },
        },
      );
      if (data) {
        const skipped = data.skipped_duplicates
          ? ` ${data.skipped_duplicates} duplicate${data.skipped_duplicates === 1 ? "" : "s"} skipped.`
          : "";
        toast({
          title:
            data.created === 0
              ? "Nothing new to review"
              : `${data.created} item${data.created === 1 ? "" : "s"} ready for review`,
          description:
            `${data.truncated ? "Only the first items were kept. " : ""}${skipped}`.trim() ||
            undefined,
          tone: data.created === 0 ? "info" : "success",
        });
        router.refresh();
        onClose();
        return;
      }
      const out = failureFrom(error, response);
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
      title="Import text"
      description="Paste notes, a bio or a case-study write-up. It's split into separate items, word for word."
      className="w-[min(34rem,100vw-2rem)]"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="knowledge-import"
            disabled={pending || !label.trim() || !text.trim()}
          >
            Split into items
          </Button>
        </>
      }
    >
      <form
        id="knowledge-import"
        onSubmit={submit}
        className="flex flex-col gap-4"
        aria-label="Import text"
      >
        <Notice tone="info" title="Nothing is used until you approve it">
          Imported items arrive as “Needs review”. No AI is involved: the text is only split into
          sentences and bullet points.
        </Notice>
        {banner ? (
          <Notice tone="danger" title={banner.title}>
            {banner.text}
          </Notice>
        ) : null}
        <Field
          label="Where is this from?"
          required
          hint="A short label or a public link."
          {...err("source_label")}
        >
          {(p) => (
            <Input
              {...p}
              value={label}
              maxLength={500}
              onChange={(e) => setLabel(e.target.value)}
            />
          )}
        </Field>
        <Field label="Type of items" {...err("kind")}>
          {(p) => (
            <Select {...p} value={kind} onChange={(e) => setKind(e.target.value as Kind)}>
              {KINDS.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field
          label="Text"
          required
          hint="Up to 20,000 characters. Up to 25 items are created."
          {...err("text")}
        >
          {(p) => (
            <Textarea
              {...p}
              rows={10}
              value={text}
              maxLength={20000}
              onChange={(e) => setText(e.target.value)}
            />
          )}
        </Field>
      </form>
    </Drawer>
  );
}
