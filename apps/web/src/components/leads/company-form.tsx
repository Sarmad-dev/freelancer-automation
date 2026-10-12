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
  createBody,
  diffCompany,
  emptyCompanyForm,
  formFromCompany,
  validateCompanyForm,
  type CompanyForm,
  type CompanyOut,
} from "./company-model";
import { COMPANY_SIZES, type CompanySize } from "./lead-model";

export function CompanyFields({
  form,
  setForm,
  errors,
  idPrefix,
}: {
  form: CompanyForm;
  setForm: (f: CompanyForm) => void;
  errors: Record<string, string>;
  idPrefix: string;
}) {
  const err = (k: string) => (errors[k] ? { error: errors[k] } : {});
  return (
    <div className="flex flex-col gap-4" data-testid={`${idPrefix}-fields`}>
      <Field label="Name" required {...err("name")}>
        {(p) => (
          <Input
            {...p}
            value={form.name}
            maxLength={200}
            autoComplete="off"
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        )}
      </Field>
      <Field
        label="Website"
        hint="Used to spot duplicates. Leave it blank if you don't know it."
        {...err("website")}
      >
        {(p) => (
          <Input
            {...p}
            type="text"
            inputMode="url"
            value={form.website}
            maxLength={500}
            autoComplete="off"
            placeholder="https://example.com"
            onChange={(e) => setForm({ ...form, website: e.target.value })}
          />
        )}
      </Field>
      <Field label="Industry" {...err("industry")}>
        {(p) => (
          <Input
            {...p}
            value={form.industry}
            maxLength={100}
            autoComplete="off"
            onChange={(e) => setForm({ ...form, industry: e.target.value })}
          />
        )}
      </Field>
      <Field label="Size" {...err("size_label")}>
        {(p) => (
          <Select
            {...p}
            value={form.size_label}
            onChange={(e) => setForm({ ...form, size_label: e.target.value as CompanySize | "" })}
          >
            <option value="">Not set</option>
            {COMPANY_SIZES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field label="Location" {...err("location")}>
        {(p) => (
          <Input
            {...p}
            value={form.location}
            maxLength={200}
            autoComplete="off"
            onChange={(e) => setForm({ ...form, location: e.target.value })}
          />
        )}
      </Field>
      <Field label="Notes" hint="Only you and your workspace see these." {...err("notes")}>
        {(p) => (
          <Textarea
            {...p}
            rows={5}
            value={form.notes}
            maxLength={5000}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
          />
        )}
      </Field>
    </div>
  );
}

/**
 * One drawer for both flows: pass `company` to edit it (only changed fields are sent), leave it out to
 * create a new one (only filled fields are sent).
 */
export function CompanyDrawer({
  workspaceId,
  company,
  onClose,
}: {
  workspaceId: string;
  company?: CompanyOut;
  onClose: () => void;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const editing = Boolean(company);
  const baseline = useMemo(
    () => (company ? formFromCompany(company) : emptyCompanyForm()),
    [company],
  );
  const [form, setForm] = useState<CompanyForm>(baseline);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [banner, setBanner] = useState<MutationFailure | null>(null);
  const [pending, setPending] = useState(false);

  const patch = diffCompany(baseline, form);
  const dirty = Object.keys(patch).length > 0;
  const formId = editing ? "company-edit" : "company-add";

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (pending) return;
    setBanner(null);
    const local = validateCompanyForm(form);
    if (Object.keys(local).length > 0) {
      setErrors(local);
      setBanner({
        title: "Some fields need attention",
        text: "Fix the highlighted fields and try again.",
      });
      return;
    }
    setErrors({});
    if (editing && !dirty) return;
    setPending(true);
    try {
      const path = { workspace_id: workspaceId };
      const { error, response } =
        editing && company
          ? await browserApi().PATCH("/api/v1/workspaces/{workspace_id}/companies/{company_id}", {
              params: { path: { ...path, company_id: company.id } },
              body: patch,
            })
          : await browserApi().POST("/api/v1/workspaces/{workspace_id}/companies", {
              params: { path },
              body: createBody(form),
            });
      if (response.ok) {
        toast({ title: editing ? "Company saved" : "Company added", tone: "success" });
        router.refresh();
        onClose();
        return;
      }
      const out = describeFailure(error, response, "company");
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
      title={editing ? "Edit company" : "New company"}
      description={
        editing
          ? "Blank fields are cleared. Only what you change is saved."
          : "Only the name is needed. You can fill in the rest later."
      }
      className="w-[min(34rem,100vw-2rem)]"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
          <Button type="submit" form={formId} disabled={pending || (editing && !dirty)}>
            {editing ? "Save changes" : "Add company"}
          </Button>
        </>
      }
    >
      <form
        id={formId}
        onSubmit={submit}
        noValidate
        className="flex flex-col gap-4"
        aria-label={editing ? "Edit company" : "New company"}
      >
        {banner ? (
          <Notice tone={banner.reload ? "warning" : "danger"} title={banner.title}>
            {banner.text}
          </Notice>
        ) : null}
        <CompanyFields
          form={form}
          setForm={setForm}
          errors={errors}
          idPrefix={editing ? "edit" : "add"}
        />
      </form>
    </Drawer>
  );
}
