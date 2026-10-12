"use client";

import { Field, Input, Select, Textarea } from "@freelancer-os/ui";
import { FORM_LIMITS, type ContactForm } from "./contact-model";

export interface CompanyChoice {
  id: string;
  name: string;
}

/** The fields shared by "New contact" and "Edit contact". Errors are keyed by API field name. */
export function ContactFields({
  form,
  setForm,
  errors,
  companies,
  idPrefix,
}: {
  form: ContactForm;
  setForm: (form: ContactForm) => void;
  errors: Record<string, string>;
  companies: readonly CompanyChoice[];
  idPrefix: string;
}) {
  const err = (key: string) => (errors[key] ? { error: errors[key] } : {});
  const set = (patch: Partial<ContactForm>) => setForm({ ...form, ...patch });
  // A company that is not in the picker (archived, or beyond the first page) must not silently disappear.
  const missing = form.company_id && !companies.some((c) => c.id === form.company_id);
  return (
    <div className="flex flex-col gap-4" data-testid={`${idPrefix}-fields`}>
      <Field label="Full name" required {...err("full_name")}>
        {(p) => (
          <Input
            {...p}
            value={form.full_name}
            maxLength={FORM_LIMITS.full_name}
            autoComplete="off"
            onChange={(e) => set({ full_name: e.target.value })}
          />
        )}
      </Field>
      <Field label="Email" {...err("email")}>
        {(p) => (
          <Input
            {...p}
            type="text"
            inputMode="email"
            autoComplete="off"
            value={form.email}
            maxLength={FORM_LIMITS.email}
            onChange={(e) => set({ email: e.target.value })}
          />
        )}
      </Field>
      <Field label="Phone" {...err("phone")}>
        {(p) => (
          <Input
            {...p}
            type="tel"
            autoComplete="off"
            value={form.phone}
            maxLength={FORM_LIMITS.phone}
            onChange={(e) => set({ phone: e.target.value })}
          />
        )}
      </Field>
      <Field label="Role" {...err("role_title")}>
        {(p) => (
          <Input
            {...p}
            value={form.role_title}
            maxLength={FORM_LIMITS.role_title}
            autoComplete="off"
            onChange={(e) => set({ role_title: e.target.value })}
          />
        )}
      </Field>
      <Field label="Company" {...err("company_id")}>
        {(p) => (
          <Select
            {...p}
            value={form.company_id}
            onChange={(e) => set({ company_id: e.target.value })}
          >
            <option value="">None</option>
            {missing ? <option value={form.company_id}>Current company</option> : null}
            {companies.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field
        label="Source"
        hint="Where you found them, e.g. a public page. Leave empty for a contact you added yourself."
        {...err("source")}
      >
        {(p) => (
          <Input
            {...p}
            value={form.source}
            maxLength={FORM_LIMITS.source}
            autoComplete="off"
            onChange={(e) => set({ source: e.target.value })}
          />
        )}
      </Field>
      <Field label="Notes" {...err("notes")}>
        {(p) => (
          <Textarea
            {...p}
            rows={5}
            value={form.notes}
            maxLength={FORM_LIMITS.notes}
            onChange={(e) => set({ notes: e.target.value })}
          />
        )}
      </Field>
    </div>
  );
}
