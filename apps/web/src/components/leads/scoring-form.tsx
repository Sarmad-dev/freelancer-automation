"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import {
  Button,
  Checkbox,
  Field,
  Input,
  Notice,
  Switch,
  Textarea,
  useToast,
} from "@freelancer-os/ui";
import { browserApi, toFailure } from "@/lib/api-client";
import { describeFailure } from "@/lib/mutation-error";
import { COMPANY_SIZES, type CompanySize, type FitConfigOut } from "./lead-model";
import {
  CRITERION_INFO,
  CRITERION_KEYS,
  MAX_ITEMS,
  MAX_WEIGHT,
  MIN_WEIGHT,
  defaultForm,
  formFromConfig,
  formToCriteria,
  mapServerFields,
  sameForm,
  validateForm,
  weightShares,
  type CriterionForm,
  type CriterionKey,
  type FormErrors,
  type ScoringForm as FormState,
} from "./scoring-model";

const card = "rounded-lg border border-line bg-surface p-5";
const LIST_HINT = `One per line, up to ${MAX_ITEMS}. Blank lines and repeats are ignored.`;

interface Banner {
  tone: "danger" | "warning";
  title: string;
  text: string;
  items?: string[];
  reload?: boolean;
}

const leads = (n: number) => `${n} lead${n === 1 ? "" : "s"}`;

function CriterionSection({
  id,
  criterion,
  editable,
  form,
  error,
  onChange,
  children,
}: {
  id: CriterionKey;
  criterion: CriterionForm;
  editable: boolean;
  form: FormState;
  error?: string | undefined;
  onChange: (patch: Partial<CriterionForm>) => void;
  children?: ReactNode;
}) {
  const info = CRITERION_INFO[id];
  const headingId = `crit-${id}`;
  const { shares } = weightShares(form);
  const share = shares.find((s) => s.key === id);
  const fieldsOff = !editable || !criterion.enabled;
  return (
    <section aria-labelledby={headingId} className={card}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 id={headingId} className="text-base font-semibold text-fg">
            {info.title}
          </h3>
          <p className="mt-1 text-sm text-muted">{info.description}</p>
        </div>
        <div className="flex items-center gap-2 text-sm text-fg">
          <span>Use this criterion</span>
          <Switch
            label={`Use ${info.title} criterion`}
            checked={criterion.enabled}
            disabled={!editable}
            onCheckedChange={(enabled) => onChange({ enabled })}
          />
          <span className="w-7 text-muted">{criterion.enabled ? "On" : "Off"}</span>
        </div>
      </div>
      {!criterion.enabled ? (
        <p className="mt-3 text-[13px] text-muted">
          Turned off: this criterion is ignored when scoring. Your settings below are kept.
        </p>
      ) : null}
      <div className={`mt-4 flex flex-col gap-4 ${criterion.enabled ? "" : "opacity-70"}`}>
        <Field
          label={`${info.title} weight`}
          hint={`How much this counts compared with the others, from ${MIN_WEIGHT} (minor) to ${MAX_WEIGHT} (decisive).${
            share ? ` Currently ${share.percent}% of the total.` : ""
          }`}
          {...(error ? { error } : {})}
        >
          {(p) => (
            <Input
              {...p}
              type="number"
              inputMode="numeric"
              min={MIN_WEIGHT}
              max={MAX_WEIGHT}
              step={1}
              className="max-w-24"
              value={criterion.weight}
              disabled={fieldsOff}
              onChange={(e) => onChange({ weight: e.target.value })}
            />
          )}
        </Field>
        {children}
      </div>
    </section>
  );
}

export function ScoringForm({
  workspaceId,
  initial,
  canEdit,
}: {
  workspaceId: string;
  initial: FitConfigOut;
  canEdit: boolean;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const [saved, setSaved] = useState({ version: initial.version, updatedAt: initial.updated_at });
  const [baseline, setBaseline] = useState<FormState>(() => formFromConfig(initial.criteria));
  const [form, setForm] = useState<FormState>(() => formFromConfig(initial.criteria));
  const [errors, setErrors] = useState<FormErrors>({});
  const [banner, setBanner] = useState<Banner | null>(null);
  const [rescore, setRescore] = useState(true);
  const [pending, setPending] = useState(false);
  const [recalculating, setRecalculating] = useState(false);

  const dirty = useMemo(() => !sameForm(baseline, form), [baseline, form]);
  const isDefaults = useMemo(() => sameForm(form, defaultForm()), [form]);
  const neverSaved = saved.version === 0;
  const { shares, total } = useMemo(() => weightShares(form), [form]);

  // Leaving with unsaved edits asks first (the browser shows its own generic prompt).
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const update = (key: CriterionKey, patch: Partial<CriterionForm>) => {
    setForm((f) => ({ ...f, [key]: { ...f[key], ...patch } }));
    setErrors((e) => {
      const touched = Object.keys(patch).map((field) => `${key}.${field}`);
      const next = { ...e };
      let changed = false;
      for (const k of [...touched, key, ...(patch.enabled !== undefined ? ["form"] : [])]) {
        if (k in next) {
          delete next[k];
          changed = true;
        }
      }
      return changed ? next : e;
    });
  };

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!canEdit || pending) return;
    const problems = validateForm(form);
    if (Object.keys(problems).length > 0) {
      setErrors(problems);
      setBanner({
        tone: "danger",
        title: "Fix these before saving",
        text:
          problems.form ??
          "Some criteria have values that can't be saved. The fields are marked below.",
      });
      return;
    }
    setPending(true);
    setBanner(null);
    setErrors({});
    try {
      const { data, error, response } = await browserApi().PUT(
        "/api/v1/workspaces/{workspace_id}/fit-scoring",
        {
          params: { path: { workspace_id: workspaceId } },
          body: {
            criteria: formToCriteria(form),
            expected_version: saved.version,
            rescore,
          },
        },
      );
      if (data) {
        const next = formFromConfig(data.criteria);
        setSaved({ version: data.version, updatedAt: data.updated_at });
        setBaseline(next);
        setForm(next);
        const n = data.rescored;
        toast({
          title: n == null ? "Saved." : `Saved. ${leads(n)} recalculated.`,
          description:
            n == null
              ? "Existing leads keep their current scores until you recalculate them."
              : "Each lead now reflects your updated criteria.",
          tone: "success",
        });
        router.refresh();
      } else {
        const d = describeFailure(error, response, "scoring setup");
        if (d) {
          const mapped = mapServerFields(d.fields);
          setErrors(mapped.errors);
          const message =
            Object.keys(d.fields).length > 0 ? toFailure(error, response).message : d.failure.text;
          setBanner({
            tone: d.failure.reload ? "warning" : "danger",
            title: d.failure.title,
            text: message,
            ...(mapped.other.length > 0 ? { items: mapped.other } : {}),
            ...(d.failure.reload ? { reload: true } : {}),
          });
        }
      }
    } catch {
      setBanner({
        tone: "danger",
        title: "That didn't work",
        text: "Can't reach the server. Check your connection and try again.",
      });
    }
    setPending(false);
  }

  async function recalculate() {
    setRecalculating(true);
    setBanner(null);
    try {
      const { data, error, response } = await browserApi().POST(
        "/api/v1/workspaces/{workspace_id}/fit-scoring/rescore",
        { params: { path: { workspace_id: workspaceId } } },
      );
      if (data) {
        toast({
          title: `${leads(data.rescored)} recalculated.`,
          description: "Used your saved criteria and profile.",
          tone: "success",
        });
        router.refresh();
      } else {
        const d = describeFailure(error, response, "scoring setup");
        if (d) setBanner({ tone: "danger", title: "Couldn't recalculate", text: d.failure.text });
      }
    } catch {
      setBanner({
        tone: "danger",
        title: "Couldn't recalculate",
        text: "Can't reach the server. Check your connection and try again.",
      });
    }
    setRecalculating(false);
  }

  const err = (k: string) => (errors[k] ? { error: errors[k] } : {});
  const off = (key: CriterionKey) => !canEdit || !form[key].enabled;

  const toggleSize = (size: CompanySize, on: boolean) => {
    const current = form.company_size.sizes;
    update("company_size", {
      sizes: COMPANY_SIZES.map((s) => s.value).filter((v) =>
        v === size ? on : current.includes(v),
      ),
    });
  };

  return (
    <form
      onSubmit={onSubmit}
      noValidate
      className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]"
      aria-label="Fit scoring criteria"
    >
      <div className="flex flex-col gap-6">
        <section aria-labelledby="scoring-how" className={card}>
          <h2 id="scoring-how" className="text-base font-semibold text-fg">
            How fit scoring works
          </h2>
          <div className="mt-2 flex flex-col gap-2 text-sm text-muted">
            <p>
              The score is a simple, rule-based estimate built from your own criteria below. There
              is no AI and nothing is fetched from outside: it only looks at what you have entered
              about a lead, its title, notes, and its company&apos;s notes and details.
            </p>
            <p>
              Each criterion you turn on answers <strong className="text-fg">Matches</strong>,{" "}
              <strong className="text-fg">Partly</strong>,{" "}
              <strong className="text-fg">Doesn&apos;t match</strong> or{" "}
              <strong className="text-fg">Unknown</strong>, and shows its evidence. Unknown answers
              carry no weight: they are not counted as misses.
            </p>
            <p>
              The score is rounded to the nearest 5 so it doesn&apos;t look more exact than it is.
              When too little is known there is no number at all, only &ldquo;Not enough
              information&rdquo;. Bands: Strong fit is 70 or more, Possible fit is 45 to 69, Weak
              fit is under 45.
            </p>
            <p>
              A lead that mentions a client type you said you don&apos;t take is capped at 25. You
              manage that list in your{" "}
              <Link href="/ai-workspace/profile" className="text-fg underline underline-offset-4">
                profile
              </Link>{" "}
              under &ldquo;Clients you don&apos;t take&rdquo;.
            </p>
            <p>
              Matching works on whole words, with light handling of word endings. It does not
              understand meaning, so add the words you expect to see as keywords to avoid false
              misses.
            </p>
          </div>
        </section>

        {neverSaved ? (
          <Notice tone="info" title="Using the built-in defaults">
            These are the built-in defaults. Saving creates your own criteria.
          </Notice>
        ) : null}
        {!canEdit ? (
          <Notice tone="info" title="View only">
            Only the workspace owner can change fit scoring. You can see how it is set up here.
          </Notice>
        ) : null}
        {banner ? (
          <Notice tone={banner.tone} title={banner.title}>
            {banner.text}
            {banner.items ? (
              <ul className="mt-1 list-disc pl-5">
                {banner.items.map((m) => (
                  <li key={m}>{m}</li>
                ))}
              </ul>
            ) : null}
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

        <h2 className="text-lg font-semibold text-fg">Your criteria</h2>

        <CriterionSection
          id="service_match"
          criterion={form.service_match}
          editable={canEdit}
          form={form}
          error={errors["service_match.weight"]}
          onChange={(p) => update("service_match", p)}
        >
          <Field
            label="Extra keywords"
            hint={`Words that signal work you want, in addition to the services in your profile. ${LIST_HINT}`}
            {...err("service_match.keywords")}
          >
            {(p) => (
              <Textarea
                {...p}
                value={form.service_match.keywords}
                disabled={off("service_match")}
                onChange={(e) => update("service_match", { keywords: e.target.value })}
              />
            )}
          </Field>
          <p className="text-[13px] text-muted">
            The services in your{" "}
            <Link href="/ai-workspace/profile" className="text-fg underline underline-offset-4">
              profile
            </Link>{" "}
            are always used too.
          </p>
        </CriterionSection>

        <CriterionSection
          id="industry"
          criterion={form.industry}
          editable={canEdit}
          form={form}
          error={errors["industry.weight"]}
          onChange={(p) => update("industry", p)}
        >
          <Field
            label="Preferred industries"
            hint={`Leave empty to use the industries from your profile. ${LIST_HINT}`}
            {...err("industry.preferred")}
          >
            {(p) => (
              <Textarea
                {...p}
                value={form.industry.preferred}
                disabled={off("industry")}
                onChange={(e) => update("industry", { preferred: e.target.value })}
              />
            )}
          </Field>
          <Field
            label="Industries to avoid"
            hint={`Leads in these count against the fit. ${LIST_HINT}`}
            {...err("industry.avoid")}
          >
            {(p) => (
              <Textarea
                {...p}
                value={form.industry.avoid}
                disabled={off("industry")}
                onChange={(e) => update("industry", { avoid: e.target.value })}
              />
            )}
          </Field>
        </CriterionSection>

        <CriterionSection
          id="geography"
          criterion={form.geography}
          editable={canEdit}
          form={form}
          error={errors["geography.weight"]}
          onChange={(p) => update("geography", p)}
        >
          <Field
            label="Preferred places"
            hint={`Places, regions, or words such as "Remote". Compared as words against the lead's or company's location. ${LIST_HINT}`}
            {...err("geography.preferred")}
          >
            {(p) => (
              <Textarea
                {...p}
                value={form.geography.preferred}
                disabled={off("geography")}
                onChange={(e) => update("geography", { preferred: e.target.value })}
              />
            )}
          </Field>
        </CriterionSection>

        <CriterionSection
          id="company_size"
          criterion={form.company_size}
          editable={canEdit}
          form={form}
          error={errors["company_size.weight"]}
          onChange={(p) => update("company_size", p)}
        >
          <fieldset
            className="flex flex-col gap-2"
            disabled={off("company_size")}
            aria-describedby="size-hint"
          >
            <legend className="text-sm font-medium text-fg">Preferred company sizes</legend>
            <p id="size-hint" className="text-[13px] text-muted">
              Number of people. Sizes next to the ones you pick count as a partial match.
            </p>
            {errors["company_size"] ? (
              <p className="text-[13px] text-danger">{errors["company_size"]}</p>
            ) : null}
            <div className="grid gap-2 sm:grid-cols-2">
              {COMPANY_SIZES.map((s) => (
                <Checkbox
                  key={s.value}
                  label={s.label}
                  checked={form.company_size.sizes.includes(s.value)}
                  disabled={off("company_size")}
                  onCheckedChange={(v) => toggleSize(s.value, v === true)}
                />
              ))}
            </div>
          </fieldset>
        </CriterionSection>

        <CriterionSection
          id="budget"
          criterion={form.budget}
          editable={canEdit}
          form={form}
          error={errors["budget.weight"]}
          onChange={(p) => update("budget", p)}
        >
          <p className="text-sm text-muted">
            No settings here. A lead with a high budget signal matches, medium is partial, low
            doesn&apos;t match, and a lead without one is unknown. You set the signal on each lead.
          </p>
        </CriterionSection>

        {canEdit ? (
          <div
            role="region"
            aria-label="Save changes"
            className="sticky bottom-0 z-10 -mx-4 flex flex-col gap-3 border-t border-line bg-canvas/95 px-4 py-3 backdrop-blur md:-mx-8 md:px-8"
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p role="status" className="text-sm text-muted">
                {dirty ? (
                  <span className="text-fg">
                    <span aria-hidden>● </span>Unsaved changes
                  </span>
                ) : neverSaved ? (
                  <>Built-in defaults · not saved yet</>
                ) : (
                  <>All changes saved · version {saved.version}</>
                )}
              </p>
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="ghost"
                  disabled={pending || isDefaults}
                  onClick={() => {
                    setForm(defaultForm());
                    setErrors({});
                    setBanner(null);
                  }}
                >
                  Reset to defaults
                </Button>
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
                <Button
                  type="submit"
                  disabled={(!dirty && !neverSaved) || pending}
                  aria-busy={pending}
                >
                  {pending ? "Saving…" : "Save criteria"}
                </Button>
              </div>
            </div>
            <Checkbox
              label="Recalculate existing leads now"
              description="Applies the saved criteria to every active lead as part of saving."
              checked={rescore}
              onCheckedChange={(v) => setRescore(v === true)}
            />
          </div>
        ) : null}
      </div>

      <aside
        aria-label="Weighting"
        className="flex flex-col gap-6 lg:sticky lg:top-20 lg:self-start"
      >
        <section aria-labelledby="scoring-split" className={card}>
          <h2 id="scoring-split" className="text-base font-semibold text-fg">
            How your weighting is split
          </h2>
          {shares.length === 0 ? (
            <p className="mt-2 text-sm text-muted">No criteria are turned on.</p>
          ) : (
            <>
              <p className="mt-1 text-[13px] text-muted">
                Shares of the total weight, {total} in all. Rounded, so they may not add to exactly
                100%.
              </p>
              <ul className="mt-3 flex flex-col gap-3">
                {shares.map((s) => (
                  <li key={s.key} className="text-sm text-fg">
                    <div className="flex justify-between gap-2">
                      <span>{s.title}</span>
                      <span>
                        {s.weight} of {total} · {s.percent}%
                      </span>
                    </div>
                    <div aria-hidden className="mt-1 h-1.5 rounded-full bg-elevated">
                      <div
                        className="h-1.5 rounded-full bg-accent"
                        style={{ width: `${s.percent}%` }}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            </>
          )}
          {CRITERION_KEYS.some((k) => !form[k].enabled) ? (
            <p className="mt-3 text-[13px] text-muted">
              Turned off:{" "}
              {CRITERION_KEYS.filter((k) => !form[k].enabled)
                .map((k) => CRITERION_INFO[k].title)
                .join(", ")}
              .
            </p>
          ) : null}
        </section>

        {canEdit ? (
          <section aria-labelledby="scoring-recalc" className={card}>
            <h2 id="scoring-recalc" className="text-base font-semibold text-fg">
              Recalculate leads
            </h2>
            <p className="mt-1 text-[13px] text-muted">
              Re-scores every active lead with your <em>saved</em> criteria and your current
              profile.
              {dirty ? " Save your changes first if you want them included." : ""}
            </p>
            <Button
              variant="secondary"
              className="mt-3"
              disabled={recalculating || pending}
              aria-busy={recalculating}
              onClick={recalculate}
            >
              {recalculating ? "Recalculating…" : "Recalculate all leads"}
            </Button>
          </section>
        ) : null}
      </aside>
    </form>
  );
}
