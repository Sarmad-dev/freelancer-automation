"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState, type FormEvent } from "react";
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
import {
  BUDGETS,
  type CompanyOut,
  type ContactOut,
  type LeadDetail,
  type LeadPatch,
} from "./lead-model";

export interface LeadForm {
  title: string;
  company_id: string;
  contact_id: string;
  source: string;
  industry: string;
  location: string;
  budget_signal: string;
  next_action: string;
  /** `YYYY-MM-DDTHH:mm`, in UTC (the page shows every time in UTC). */
  next_action_at: string;
  notes: string;
}

export function formFromLead(lead: LeadDetail): LeadForm {
  return {
    title: lead.title,
    company_id: lead.company?.id ?? "",
    contact_id: lead.contact?.id ?? "",
    source: lead.source ?? "",
    industry: lead.industry ?? "",
    location: lead.location ?? "",
    budget_signal: lead.budget_signal ?? "",
    next_action: lead.next_action ?? "",
    next_action_at: lead.next_action_at ? lead.next_action_at.slice(0, 16) : "",
    notes: lead.notes ?? "",
  };
}

const OPTIONAL_TEXT = ["source", "industry", "location", "next_action", "notes"] as const;

/** Only changed fields are sent. A cleared optional field is sent as null. */
export function diffLead(base: LeadForm, next: LeadForm): LeadPatch {
  const patch: LeadPatch = {};
  if (base.title.trim() !== next.title.trim()) patch.title = next.title.trim();
  for (const key of OPTIONAL_TEXT) {
    if (base[key].trim() !== next[key].trim()) patch[key] = next[key].trim() || null;
  }
  if (base.company_id !== next.company_id) patch.company_id = next.company_id || null;
  if (base.contact_id !== next.contact_id) patch.contact_id = next.contact_id || null;
  if (base.budget_signal !== next.budget_signal) {
    patch.budget_signal = (next.budget_signal || null) as LeadPatch["budget_signal"];
  }
  if (base.next_action_at !== next.next_action_at) {
    const when = next.next_action_at ? new Date(`${next.next_action_at}:00Z`) : null;
    patch.next_action_at = when && !Number.isNaN(when.getTime()) ? when.toISOString() : null;
  }
  return patch;
}

export function LeadEditDrawer({
  workspaceId,
  lead,
  companies,
  contacts,
  onClose,
}: {
  workspaceId: string;
  lead: LeadDetail;
  companies: CompanyOut[];
  contacts: ContactOut[];
  onClose: () => void;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const baseline = useMemo(() => formFromLead(lead), [lead]);
  const [form, setForm] = useState<LeadForm>(baseline);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [banner, setBanner] = useState<MutationFailure | null>(null);
  const [pending, setPending] = useState(false);

  const patch = diffLead(baseline, form);
  const dirty = Object.keys(patch).length > 0;
  const set = (key: keyof LeadForm, value: string) => setForm((f) => ({ ...f, [key]: value }));
  const err = (k: string) => (errors[k] ? { error: errors[k] } : {});

  // The linked record may be missing from the first page of the picker; never drop it silently.
  const companyOptions = useMemo(() => {
    const list = companies.map((c) => ({ id: c.id, name: c.name }));
    if (lead.company && !list.some((c) => c.id === lead.company?.id)) list.unshift(lead.company);
    return list;
  }, [companies, lead.company]);
  const contactOptions = useMemo(() => {
    const list = contacts.map((c) => ({ id: c.id, name: c.full_name, email: c.email }));
    if (lead.contact && !list.some((c) => c.id === lead.contact?.id)) {
      list.unshift({
        id: lead.contact.id,
        name: lead.contact.full_name,
        email: lead.contact.email,
      });
    }
    return list;
  }, [contacts, lead.contact]);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!dirty || pending) return;
    if (!form.title.trim()) {
      setErrors({ title: "Give the lead a title." });
      return;
    }
    setPending(true);
    setBanner(null);
    setErrors({});
    try {
      const { error, response } = await browserApi().PATCH(
        "/api/v1/workspaces/{workspace_id}/leads/{lead_id}",
        { params: { path: { workspace_id: workspaceId, lead_id: lead.id } }, body: patch },
      );
      if (response.ok) {
        toast({ title: "Saved", description: "The lead was updated.", tone: "success" });
        router.refresh();
        onClose();
      } else {
        const out = describeFailure(error, response, "lead");
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

  return (
    <Drawer
      open
      onOpenChange={(open) => !open && onClose()}
      title="Edit lead"
      description="Change the details. Status and stage are changed from the lead page."
      className="w-[min(34rem,100vw-2rem)]"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
          <Button type="submit" form="lead-edit" disabled={pending || !dirty} aria-busy={pending}>
            {pending ? "Saving…" : "Save changes"}
          </Button>
        </>
      }
    >
      <form
        id="lead-edit"
        onSubmit={(e) => void save(e)}
        aria-label="Lead details"
        className="flex flex-col gap-4"
      >
        {banner ? (
          <Notice tone={banner.reload ? "warning" : "danger"} title={banner.title}>
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
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Company" {...err("company_id")}>
            {(p) => (
              <Select
                {...p}
                value={form.company_id}
                onChange={(e) => set("company_id", e.target.value)}
              >
                <option value="">None</option>
                {companyOptions.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Contact" {...err("contact_id")}>
            {(p) => (
              <Select
                {...p}
                value={form.contact_id}
                onChange={(e) => set("contact_id", e.target.value)}
              >
                <option value="">None</option>
                {contactOptions.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.email ? `${c.name} (${c.email})` : c.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        </div>
        <Field
          label="Source"
          hint="Where this lead came from, e.g. “Referral”. Leave blank if unknown."
          {...err("source")}
        >
          {(p) => (
            <Input
              {...p}
              value={form.source}
              maxLength={100}
              onChange={(e) => set("source", e.target.value)}
            />
          )}
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
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
              onChange={(e) => set("budget_signal", e.target.value)}
            >
              <option value="">Not set</option>
              {BUDGETS.map((b) => (
                <option key={b.value} value={b.value}>
                  {b.label}
                </option>
              ))}
            </Select>
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
          <Field label="Next action date" hint="Time is in UTC." {...err("next_action_at")}>
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
        <Field label="Notes" hint="Plain text. Up to 4,000 characters." {...err("notes")}>
          {(p) => (
            <Textarea
              {...p}
              rows={6}
              value={form.notes}
              maxLength={4000}
              onChange={(e) => set("notes", e.target.value)}
            />
          )}
        </Field>
      </form>
    </Drawer>
  );
}
