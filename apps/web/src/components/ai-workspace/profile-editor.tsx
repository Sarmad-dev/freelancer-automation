"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import type { components } from "@freelancer-os/contracts";
import { Badge, Button, Field, Input, Notice, Select, Textarea, useToast } from "@freelancer-os/ui";
import { browserApi, isSessionLost, redirectToSignIn, toFailure } from "@/lib/api-client";
import { PublicSummary } from "./public-summary";
import {
  TONES,
  diffToPatch,
  formFromProfile,
  type ProfileForm,
  type ProfileOut,
} from "./profile-model";

type Summary = components["schemas"]["ProfileSummary"];

const card = "rounded-lg border border-line bg-surface p-5";

function Section({
  id,
  title,
  description,
  badge,
  children,
}: {
  id: string;
  title: string;
  description?: string;
  badge?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={id} className={card}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id={id} className="text-base font-semibold text-fg">
          {title}
        </h2>
        {badge}
      </div>
      {description ? <p className="mt-1 text-sm text-muted">{description}</p> : null}
      <div className="mt-4 flex flex-col gap-4">{children}</div>
    </section>
  );
}

export function ProfileEditor({
  workspaceId,
  initial,
  initialSummary,
  facts,
}: {
  workspaceId: string;
  initial: ProfileOut;
  initialSummary: Summary;
  /** Number of approved, enabled facts the AI may use (from the AI context). */
  facts: number;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const [saved, setSaved] = useState(initial);
  const [baseline, setBaseline] = useState<ProfileForm>(() => formFromProfile(initial));
  const [form, setForm] = useState<ProfileForm>(() => formFromProfile(initial));
  const [summary, setSummary] = useState(initialSummary);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [banner, setBanner] = useState<{
    tone: "danger" | "warning";
    title: string;
    text: string;
    reload?: boolean;
  } | null>(null);
  const [pending, setPending] = useState(false);

  const patch = useMemo(() => diffToPatch(baseline, form), [baseline, form]);
  const dirty = Object.keys(patch).length > 0;

  // Leaving with unsaved edits asks first (the browser shows its own generic prompt).
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const set = <K extends keyof ProfileForm>(key: K, value: ProfileForm[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
    setErrors((e) => {
      if (!e[key]) return e;
      const rest = { ...e };
      delete rest[key];
      return rest;
    });
  };

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!dirty) return;
    setPending(true);
    setBanner(null);
    setErrors({});
    try {
      const api = browserApi();
      const path = { workspace_id: workspaceId };
      const { data, error, response } = await api.PATCH(
        "/api/v1/workspaces/{workspace_id}/profile",
        {
          params: { path },
          body: { ...patch, expected_version: saved.version },
        },
      );
      if (data) {
        setSaved(data);
        const next = formFromProfile(data);
        setBaseline(next);
        setForm(next);
        const fresh = await api.GET("/api/v1/workspaces/{workspace_id}/profile/summary", {
          params: { path },
        });
        if (fresh.data) setSummary(fresh.data);
        toast({ title: "Profile saved", description: `Version ${data.version}`, tone: "success" });
        router.refresh();
      } else {
        const f = toFailure(error, response);
        if (isSessionLost(f)) return redirectToSignIn("expired");
        if (f.code === "stale_version") {
          setBanner({
            tone: "warning",
            title: "Your profile changed elsewhere",
            text: f.message,
            reload: true,
          });
        } else if (Object.keys(f.fields).length > 0) {
          setErrors(f.fields);
          setBanner({
            tone: "danger",
            title: "Some fields need attention",
            text: "Fix the highlighted fields and save again.",
          });
        } else {
          setBanner({ tone: "danger", title: "Couldn't save", text: f.message });
        }
      }
    } catch {
      setBanner({ tone: "danger", title: "Couldn't save", text: toFailure(undefined).message });
    }
    setPending(false);
  }

  const err = (k: string) => (errors[k] ? { error: errors[k] } : {});

  return (
    <form
      onSubmit={onSubmit}
      className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]"
      aria-label="Freelancer profile"
    >
      <div className="flex flex-col gap-6">
        {banner ? (
          <Notice tone={banner.tone} title={banner.title}>
            {banner.text}
            {banner.reload ? (
              <>
                {" "}
                <button
                  type="button"
                  className="underline underline-offset-4"
                  onClick={() => window.location.reload()}
                >
                  Reload the latest version
                </button>
              </>
            ) : null}
          </Notice>
        ) : null}

        <Section
          id="sec-identity"
          title="Who you are"
          description="How you describe yourself. Shown in your public summary."
        >
          <Field label="Role" hint="e.g. Independent web developer" {...err("role_title")}>
            {(p) => (
              <Input
                {...p}
                value={form.role_title}
                onChange={(e) => set("role_title", e.target.value)}
                maxLength={120}
              />
            )}
          </Field>
          <Field
            label="Short summary"
            hint="One or two sentences, up to 500 characters."
            {...err("summary")}
          >
            {(p) => (
              <Textarea
                {...p}
                value={form.summary}
                onChange={(e) => set("summary", e.target.value)}
                maxLength={500}
              />
            )}
          </Field>
        </Section>

        <Section
          id="sec-offer"
          title="What you offer"
          description="One item per line. Drafts only mention what you list here."
        >
          <Field label="Services" hint="Up to 15." {...err("services")}>
            {(p) => (
              <Textarea
                {...p}
                value={form.services}
                onChange={(e) => set("services", e.target.value)}
              />
            )}
          </Field>
          <Field label="Skills" hint="Up to 30." {...err("skills")}>
            {(p) => (
              <Textarea
                {...p}
                value={form.skills}
                onChange={(e) => set("skills", e.target.value)}
              />
            )}
          </Field>
          <Field
            label="Industries"
            hint="Up to 15. Leave blank if you work across the board."
            {...err("industries")}
          >
            {(p) => (
              <Textarea
                {...p}
                value={form.industries}
                onChange={(e) => set("industries", e.target.value)}
              />
            )}
          </Field>
          <Field
            label="What sets you apart"
            hint="Up to 10. Only things that are true and you can back up."
            {...err("differentiators")}
          >
            {(p) => (
              <Textarea
                {...p}
                value={form.differentiators}
                onChange={(e) => set("differentiators", e.target.value)}
              />
            )}
          </Field>
        </Section>

        <Section id="sec-audience" title="Who you serve">
          <Field
            label="Ideal clients"
            hint="Who you most want to work with."
            {...err("target_clients")}
          >
            {(p) => (
              <Textarea
                {...p}
                value={form.target_clients}
                onChange={(e) => set("target_clients", e.target.value)}
                maxLength={500}
              />
            )}
          </Field>
          <Field
            label="Clients you don't take"
            hint="One per line. Private: used to filter and shape drafts, never shown."
            {...err("excluded_customers")}
          >
            {(p) => (
              <Textarea
                {...p}
                value={form.excluded_customers}
                onChange={(e) => set("excluded_customers", e.target.value)}
              />
            )}
          </Field>
        </Section>

        <Section
          id="sec-proof"
          title="Experience and proof"
          description="Only facts you can stand behind. Case studies and other reusable facts live under Knowledge, where each one is reviewed before use."
        >
          <Field label="Years of experience" {...err("years_experience")}>
            {(p) => (
              <Input
                {...p}
                type="number"
                min={0}
                max={60}
                inputMode="numeric"
                className="max-w-32"
                value={form.years_experience}
                onChange={(e) => set("years_experience", e.target.value)}
              />
            )}
          </Field>
          <Field label="Experience highlights" {...err("experience_summary")}>
            {(p) => (
              <Textarea
                {...p}
                value={form.experience_summary}
                onChange={(e) => set("experience_summary", e.target.value)}
                maxLength={1000}
              />
            )}
          </Field>
          <Field
            label="Portfolio links"
            hint="One full https:// link per line, up to 10. Private or local addresses aren't accepted."
            {...err("portfolio_urls")}
          >
            {(p) => (
              <Textarea
                {...p}
                inputMode="url"
                value={form.portfolio_urls}
                onChange={(e) => set("portfolio_urls", e.target.value)}
              />
            )}
          </Field>
          <p className="text-sm text-muted">
            Case studies and certifications: add them as{" "}
            <Link href="/ai-workspace/knowledge" className="text-fg underline underline-offset-4">
              knowledge items
            </Link>
            .
          </p>
        </Section>

        <Section id="sec-voice" title="Voice and contact">
          <Field label="Tone of voice" {...err("tone")}>
            {(p) => (
              <Select {...p} value={form.tone} onChange={(e) => set("tone", e.target.value)}>
                <option value="">Not set</option>
                {TONES.map(([value, label, hint]) => (
                  <option key={value} value={value}>
                    {label} · {hint}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field
            label="More about your voice"
            hint="Optional, up to 300 characters."
            {...err("tone_notes")}
          >
            {(p) => (
              <Textarea
                {...p}
                value={form.tone_notes}
                onChange={(e) => set("tone_notes", e.target.value)}
                maxLength={300}
              />
            )}
          </Field>
          <Field
            label="Preferred call to action"
            hint="e.g. Book a 20-minute intro call"
            {...err("preferred_cta")}
          >
            {(p) => (
              <Input
                {...p}
                value={form.preferred_cta}
                onChange={(e) => set("preferred_cta", e.target.value)}
                maxLength={200}
              />
            )}
          </Field>
        </Section>

        <Section
          id="sec-private"
          title="Pricing guidance"
          badge={<Badge tone="info">Private</Badge>}
          description="Notes for yourself and for drafts: how to talk about money. Never shown in your public summary and never quoted to recipients."
        >
          <Field label="Pricing guidance" {...err("pricing_guidance")}>
            {(p) => (
              <Textarea
                {...p}
                value={form.pricing_guidance}
                onChange={(e) => set("pricing_guidance", e.target.value)}
                maxLength={1000}
              />
            )}
          </Field>
        </Section>

        <div
          role="region"
          aria-label="Save changes"
          className="sticky bottom-0 z-10 -mx-4 flex flex-wrap items-center justify-between gap-3 border-t border-line bg-canvas/95 px-4 py-3 backdrop-blur md:-mx-8 md:px-8"
        >
          <p role="status" className="text-sm text-muted">
            {dirty ? (
              <span className="text-fg">
                <span aria-hidden>● </span>Unsaved changes
              </span>
            ) : (
              <>All changes saved · version {saved.version}</>
            )}
          </p>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              disabled={!dirty || pending}
              onClick={() => {
                setForm(baseline);
                setErrors({});
                setBanner(null);
              }}
            >
              Discard changes
            </Button>
            <Button type="submit" disabled={!dirty || pending} aria-busy={pending}>
              {pending ? "Saving…" : "Save profile"}
            </Button>
          </div>
        </div>
      </div>

      <aside
        aria-label="Previews"
        className="flex flex-col gap-6 lg:sticky lg:top-20 lg:self-start"
      >
        <section aria-labelledby="sec-preview" className={card}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 id="sec-preview" className="text-base font-semibold text-fg">
              Public summary
            </h2>
            {dirty ? (
              <Badge tone="warning">Shows saved version</Badge>
            ) : (
              <Badge tone="success">Up to date</Badge>
            )}
          </div>
          <p className="mt-1 mb-4 text-[13px] text-muted">
            Built only from what you&apos;ve entered. Nothing is written for you.
          </p>
          <PublicSummary summary={summary} />
        </section>

        <section aria-labelledby="sec-ai" className={card}>
          <h2 id="sec-ai" className="text-base font-semibold text-fg">
            What the AI may use
          </h2>
          <p className="mt-2 text-sm text-fg">
            This profile plus {facts} approved fact{facts === 1 ? "" : "s"}.
          </p>
          {saved.completeness.missing.length > 0 ? (
            <p className="mt-2 text-[13px] text-muted">
              Missing: {saved.completeness.missing.map((m) => m.label).join(", ")}. Drafts leave
              these out rather than guess.
            </p>
          ) : null}
          <Link
            href="/ai-workspace/knowledge"
            className="mt-3 inline-block text-sm text-fg underline underline-offset-4"
          >
            Review knowledge
          </Link>
        </section>
      </aside>
    </form>
  );
}
