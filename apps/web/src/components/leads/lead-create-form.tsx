"use client";

import { useEffect, useId, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import {
  Button,
  Drawer,
  Field,
  Input,
  Notice,
  Select,
  Textarea,
  useToast,
} from "@freelancer-os/ui";
import { browserApi, toFailure } from "@/lib/api-client";
import { describeFailure, type MutationFailure } from "@/lib/mutation-error";
import { localToIso } from "./lead-list-model";
import { BUDGETS, LEAD_STATUSES, type LeadCreate, type TagOut } from "./lead-model";

interface Form {
  title: string;
  company_name: string;
  company_website: string;
  contact_name: string;
  contact_email: string;
  status: LeadCreate["status"];
  source: string;
  industry: string;
  location: string;
  budget_signal: "" | "low" | "medium" | "high";
  notes: string;
  next_action: string;
  next_action_at: string;
  tag_ids: string[];
}

const EMPTY: Form = {
  title: "",
  company_name: "",
  company_website: "",
  contact_name: "",
  contact_email: "",
  status: "new",
  source: "",
  industry: "",
  location: "",
  budget_signal: "",
  notes: "",
  next_action: "",
  next_action_at: "",
  tag_ids: [],
};

/** Only what the person filled in: blanks are left out so the server applies its own defaults. */
export function buildLeadBody(form: Form): LeadCreate {
  const body: LeadCreate = { title: form.title.trim(), status: form.status };
  const text = [
    "company_name",
    "company_website",
    "contact_name",
    "contact_email",
    "source",
    "industry",
    "location",
    "notes",
    "next_action",
  ] as const;
  for (const key of text) {
    const value = form[key].trim();
    if (value) body[key] = value;
  }
  if (form.budget_signal) body.budget_signal = form.budget_signal;
  const at = localToIso(form.next_action_at);
  if (at) body.next_action_at = at;
  if (form.tag_ids.length > 0) body.tag_ids = form.tag_ids;
  return body;
}

/** The "New lead" drawer. Mount it to open it; it asks to be closed via `onClose`. */
export function LeadCreateForm({
  workspaceId,
  tags,
  onClose,
}: {
  workspaceId: string;
  tags: TagOut[];
  onClose: () => void;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const listId = useId();
  const [form, setForm] = useState<Form>(EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [banner, setBanner] = useState<MutationFailure | null>(null);
  const [pending, setPending] = useState(false);
  const [companies, setCompanies] = useState<string[]>([]);

  useEffect(() => {
    let live = true;
    browserApi()
      .GET("/api/v1/workspaces/{workspace_id}/companies", {
        params: { path: { workspace_id: workspaceId }, query: { limit: 100, sort: "name" } },
      })
      .then((r) => {
        if (live && r.data) setCompanies(r.data.items.map((c) => c.name));
      })
      // Suggestions are a convenience; typing a name still works without them.
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [workspaceId]);

  const set = <K extends keyof Form>(key: K, value: Form[K]) =>
    setForm((f) => ({ ...f, [key]: value }));
  const err = (key: string) => (errors[key] ? { error: errors[key] } : {});

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBanner(null);
    if (!form.title.trim()) {
      setErrors({ title: "Enter a title for this lead." });
      setBanner({
        title: "Some fields need attention",
        text: "Fix the highlighted fields and try again.",
      });
      return;
    }
    setPending(true);
    setErrors({});
    try {
      const { error, response } = await browserApi().POST(
        "/api/v1/workspaces/{workspace_id}/leads",
        {
          params: { path: { workspace_id: workspaceId } },
          body: buildLeadBody(form),
        },
      );
      if (response.ok) {
        toast({ title: "Lead added", description: form.title.trim(), tone: "success" });
        router.refresh();
        onClose();
        return;
      }
      const out = describeFailure(error, response, "lead");
      if (out) {
        setBanner(out.failure);
        setErrors(out.fields);
      }
    } catch {
      setBanner({ title: "That didn't work", text: toFailure(undefined).message });
    }
    setPending(false);
  }

  const tagError =
    errors["tag_ids"] ?? Object.entries(errors).find(([k]) => k.startsWith("tag_ids"))?.[1];

  return (
    <Drawer
      open
      onOpenChange={(open) => !open && onClose()}
      title="New lead"
      description="Only a title is needed. Add what you know now and the rest later."
      className="w-[min(34rem,100vw-2rem)]"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
          <Button type="submit" form="lead-create" disabled={pending}>
            {pending ? "Adding…" : "Add lead"}
          </Button>
        </>
      }
    >
      <form
        id="lead-create"
        aria-label="New lead"
        onSubmit={submit}
        noValidate
        className="flex flex-col gap-4"
      >
        {banner ? (
          <Notice tone="danger" title={banner.title}>
            {banner.text}
          </Notice>
        ) : null}

        <Field label="Title" required {...err("title")}>
          {(p) => (
            <Input
              {...p}
              value={form.title}
              maxLength={200}
              onChange={(e) => set("title", e.target.value)}
            />
          )}
        </Field>

        <Field
          label="Company name"
          hint="Pick an existing company or type a new one."
          {...err("company_name")}
        >
          {(p) => (
            <>
              <Input
                {...p}
                list={listId}
                autoComplete="off"
                value={form.company_name}
                maxLength={200}
                onChange={(e) => set("company_name", e.target.value)}
              />
              <datalist id={listId}>
                {companies.map((name) => (
                  <option key={name} value={name} />
                ))}
              </datalist>
            </>
          )}
        </Field>
        <Field label="Company website" {...err("company_website")}>
          {(p) => (
            <Input
              {...p}
              type="url"
              inputMode="url"
              placeholder="https://example.com"
              value={form.company_website}
              onChange={(e) => set("company_website", e.target.value)}
            />
          )}
        </Field>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Contact name" {...err("contact_name")}>
            {(p) => (
              <Input
                {...p}
                value={form.contact_name}
                maxLength={200}
                onChange={(e) => set("contact_name", e.target.value)}
              />
            )}
          </Field>
          <Field label="Contact email" {...err("contact_email")}>
            {(p) => (
              <Input
                {...p}
                type="email"
                value={form.contact_email}
                onChange={(e) => set("contact_email", e.target.value)}
              />
            )}
          </Field>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Status" {...err("status")}>
            {(p) => (
              <Select
                {...p}
                value={form.status}
                onChange={(e) => set("status", e.target.value as Form["status"])}
              >
                {LEAD_STATUSES.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Source" {...err("source")}>
            {(p) => (
              <Input
                {...p}
                placeholder="manual"
                value={form.source}
                maxLength={100}
                onChange={(e) => set("source", e.target.value)}
              />
            )}
          </Field>
          <Field label="Industry" {...err("industry")}>
            {(p) => (
              <Input
                {...p}
                value={form.industry}
                maxLength={100}
                onChange={(e) => set("industry", e.target.value)}
              />
            )}
          </Field>
          <Field label="Location" {...err("location")}>
            {(p) => (
              <Input
                {...p}
                value={form.location}
                maxLength={200}
                onChange={(e) => set("location", e.target.value)}
              />
            )}
          </Field>
        </div>

        <Field label="Budget signal" {...err("budget_signal")}>
          {(p) => (
            <Select
              {...p}
              value={form.budget_signal}
              onChange={(e) => set("budget_signal", e.target.value as Form["budget_signal"])}
            >
              <option value="">Not known</option>
              {[...BUDGETS].reverse().map((b) => (
                <option key={b.value} value={b.value}>
                  {b.label}
                </option>
              ))}
            </Select>
          )}
        </Field>

        <Field label="Notes" {...err("notes")}>
          {(p) => (
            <Textarea
              {...p}
              rows={4}
              value={form.notes}
              onChange={(e) => set("notes", e.target.value)}
            />
          )}
        </Field>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Next action" {...err("next_action")}>
            {(p) => (
              <Input
                {...p}
                value={form.next_action}
                maxLength={300}
                onChange={(e) => set("next_action", e.target.value)}
              />
            )}
          </Field>
          <Field label="Next action date (UTC)" {...err("next_action_at")}>
            {(p) => (
              <Input
                {...p}
                type="datetime-local"
                value={form.next_action_at}
                onChange={(e) => set("next_action_at", e.target.value)}
              />
            )}
          </Field>
        </div>

        {tags.length > 0 ? (
          <fieldset className="flex flex-col gap-2">
            <legend className="text-sm font-medium text-fg">Tags</legend>
            <div className="flex flex-wrap gap-x-4 gap-y-2">
              {tags.map((tag) => (
                <label key={tag.id} className="flex items-center gap-2 text-sm text-fg">
                  <input
                    type="checkbox"
                    className="size-4 accent-[var(--fos-accent)]"
                    checked={form.tag_ids.includes(tag.id)}
                    onChange={(e) =>
                      set(
                        "tag_ids",
                        e.target.checked
                          ? [...form.tag_ids, tag.id]
                          : form.tag_ids.filter((id) => id !== tag.id),
                      )
                    }
                  />
                  {tag.name}
                </label>
              ))}
            </div>
            {tagError ? <p className="text-[13px] text-danger">{tagError}</p> : null}
          </fieldset>
        ) : null}
      </form>
    </Drawer>
  );
}
