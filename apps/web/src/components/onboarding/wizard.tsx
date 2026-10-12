"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import type { OnboardingState } from "@freelancer-os/contracts";
import { Button, Checkbox, Field, Input, Notice, Select, Textarea } from "@freelancer-os/ui";
import {
  browserApi,
  isSessionLost,
  redirectToSignIn,
  toFailure,
  type ApiFailure,
} from "@/lib/api-client";
import { hardNavigate } from "@/lib/navigation";
import {
  FIELD_FOR_API,
  GOALS,
  STEP_COPY,
  TONES,
  draftFromProfile,
  payloadFor,
  type Draft,
} from "./steps";

function timeZoneOptions(current: string): string[] {
  let zones: string[] = [];
  try {
    zones =
      (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf?.(
        "timeZone",
      ) ?? [];
  } catch {
    zones = [];
  }
  const set = new Set(["UTC", ...zones]);
  set.add(current);
  return [...set].sort();
}

export function OnboardingWizard({
  workspaceId,
  initial,
}: {
  workspaceId: string;
  initial: OnboardingState;
}) {
  const [state, setState] = useState(initial);
  const [step, setStep] = useState<string>(initial.current_step);
  const [draft, setDraft] = useState<Draft>(() => draftFromProfile(initial.profile));
  const [errors, setErrors] = useState<Partial<Record<keyof Draft, string>>>({});
  const [banner, setBanner] = useState<{
    tone: "danger" | "warning" | "info";
    title: string;
    text: string;
  } | null>(null);
  const [pending, setPending] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const firstRender = useRef(true);

  // Move focus to the step heading when the step changes (screen-reader and keyboard users).
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    heading.current?.focus();
  }, [step]);

  const index = state.steps.findIndex((s) => s.id === step);
  const meta = state.steps[index];
  const copy = STEP_COPY[step];
  const isLast = index === state.steps.length - 1;
  const optional = meta ? !meta.required : false;
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => {
    setDraft((d) => ({ ...d, [key]: value }));
    setErrors((e) => ({ ...e, [key]: undefined }));
  };

  function handleFailure(f: ApiFailure) {
    if (isSessionLost(f)) return redirectToSignIn("expired");
    const mapped: Partial<Record<keyof Draft, string>> = {};
    for (const [api, message] of Object.entries(f.fields)) {
      const key =
        step === "experience" && api === "summary" ? "experience_summary" : FIELD_FOR_API[api];
      if (key) mapped[key] = message;
    }
    setErrors(mapped);
    if (Object.keys(mapped).length === 0) {
      setBanner({ tone: "danger", title: "Couldn't save", text: f.message });
    } else setBanner(null);
  }

  async function saveCurrent(): Promise<OnboardingState | null> {
    const { data, error, response } = await browserApi().PUT(
      "/api/v1/workspaces/{workspace_id}/onboarding/step",
      {
        params: { path: { workspace_id: workspaceId } },
        body: payloadFor(step, draft),
      },
    );
    if (data) return data;
    handleFailure(toFailure(error, response));
    return null;
  }

  async function run(action: () => Promise<void>) {
    setPending(true);
    setBanner(null);
    try {
      await action();
    } catch {
      setBanner({ tone: "danger", title: "Couldn't save", text: toFailure(undefined).message });
    }
    setPending(false);
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (step === "experience" && draft.years.trim() === "") {
      setErrors({ years: "Enter your years of experience (0 if you're just starting out)." });
      return;
    }
    await run(async () => {
      const next = await saveCurrent();
      if (!next) return;
      setState(next);
      setErrors({});
      if (!isLast) {
        setStep(next.steps[index + 1]?.id ?? step);
        return;
      }
      const done = await browserApi().POST(
        "/api/v1/workspaces/{workspace_id}/onboarding/complete",
        {
          params: { path: { workspace_id: workspaceId } },
        },
      );
      if (done.data) {
        hardNavigate("/");
        return;
      }
      const f = toFailure(done.error, done.response);
      if (isSessionLost(f)) return redirectToSignIn("expired");
      const missing = Object.keys(f.fields);
      if (missing.length > 0) {
        setBanner({
          tone: "warning",
          title: "A few required steps are still open",
          text: f.message,
        });
        setStep(missing[0] ?? step);
      } else setBanner({ tone: "danger", title: "Couldn't finish", text: f.message });
    });
  }

  async function finishLater() {
    await run(async () => {
      const { data, error, response } = await browserApi().POST(
        "/api/v1/workspaces/{workspace_id}/onboarding/skip",
        {
          params: { path: { workspace_id: workspaceId } },
        },
      );
      if (data) {
        hardNavigate("/");
        return;
      }
      handleFailure(toFailure(error, response));
    });
  }

  async function toggleDemo(enabled: boolean) {
    await run(async () => {
      const { data, error, response } = await browserApi().PUT(
        "/api/v1/workspaces/{workspace_id}/demo-mode",
        {
          params: { path: { workspace_id: workspaceId } },
          body: { enabled },
        },
      );
      if (data) setState((s) => ({ ...s, demo_mode: data.demo_mode }));
      else handleFailure(toFailure(error, response));
    });
  }

  function field(
    label: string,
    key: keyof Draft,
    render: (p: Parameters<Parameters<typeof Field>[0]["children"]>[0]) => ReactNode,
    hint?: string,
  ) {
    return (
      <Field
        label={label}
        {...(hint ? { hint } : {})}
        {...(errors[key] ? { error: errors[key] } : {})}
      >
        {render}
      </Field>
    );
  }

  function fields(): ReactNode {
    switch (step) {
      case "role":
        return (
          <>
            {field("What best describes you?", "role_title", (p) => (
              <Input
                {...p}
                value={draft.role_title}
                onChange={(e) => set("role_title", e.target.value)}
                placeholder="e.g. Independent web developer"
                maxLength={120}
                required
              />
            ))}
            {field(
              "One-line summary (optional)",
              "summary",
              (p) => (
                <Textarea
                  {...p}
                  value={draft.summary}
                  onChange={(e) => set("summary", e.target.value)}
                  maxLength={500}
                />
              ),
              "Used to describe you in drafts, only after you approve it.",
            )}
          </>
        );
      case "services":
        return field(
          "Services",
          "services",
          (p) => (
            <Textarea
              {...p}
              value={draft.services}
              onChange={(e) => set("services", e.target.value)}
              placeholder={"Web development\nPerformance audits"}
            />
          ),
          "One per line, up to 15.",
        );
      case "skills":
        return field(
          "Skills",
          "skills",
          (p) => (
            <Textarea
              {...p}
              value={draft.skills}
              onChange={(e) => set("skills", e.target.value)}
              placeholder={"TypeScript\nPostgreSQL"}
            />
          ),
          "One per line, up to 30.",
        );
      case "target_clients":
        return field(
          "Ideal client",
          "description",
          (p) => (
            <Textarea
              {...p}
              value={draft.description}
              onChange={(e) => set("description", e.target.value)}
              maxLength={500}
            />
          ),
          "For example: seed-stage SaaS founders who need a reliable front-end partner.",
        );
      case "industries":
        return field(
          "Industries",
          "industries",
          (p) => (
            <Textarea
              {...p}
              value={draft.industries}
              onChange={(e) => set("industries", e.target.value)}
              placeholder={"SaaS\nFintech"}
            />
          ),
          "One per line, up to 15.",
        );
      case "portfolio":
        return field(
          "Links",
          "urls",
          (p) => (
            <Textarea
              {...p}
              value={draft.urls}
              onChange={(e) => set("urls", e.target.value)}
              placeholder="https://your-site.example/work"
              inputMode="url"
            />
          ),
          "One full https:// link per line, up to 10. Private or local addresses aren't accepted.",
        );
      case "experience":
        return (
          <>
            {field("Years of experience", "years", (p) => (
              <Input
                {...p}
                type="number"
                min={0}
                max={60}
                inputMode="numeric"
                value={draft.years}
                onChange={(e) => set("years", e.target.value)}
                className="max-w-32"
              />
            ))}
            {field(
              "Highlights (optional)",
              "experience_summary",
              (p) => (
                <Textarea
                  {...p}
                  value={draft.experience_summary}
                  onChange={(e) => set("experience_summary", e.target.value)}
                  maxLength={1000}
                />
              ),
              "Only include results you can back up.",
            )}
          </>
        );
      case "tone":
        return (
          <>
            <fieldset
              className="flex flex-col gap-2"
              aria-describedby={errors.tone ? "tone-error" : undefined}
            >
              <legend className="mb-1.5 text-sm font-medium text-fg">Tone</legend>
              {TONES.map(([value, label, hint]) => (
                <label
                  key={value}
                  className="flex cursor-pointer items-start gap-3 rounded-md border border-line bg-surface p-3 has-[:checked]:border-accent"
                >
                  <input
                    type="radio"
                    name="tone"
                    value={value}
                    checked={draft.tone === value}
                    onChange={() => set("tone", value)}
                    className="mt-1 accent-[var(--fos-accent)]"
                    required
                  />
                  <span>
                    <span className="block text-sm text-fg">{label}</span>
                    <span className="block text-[13px] text-muted">{hint}</span>
                  </span>
                </label>
              ))}
              {errors.tone ? (
                <p id="tone-error" className="text-[13px] text-danger">
                  {errors.tone}
                </p>
              ) : null}
            </fieldset>
            {field("Anything else about your voice? (optional)", "tone_notes", (p) => (
              <Textarea
                {...p}
                value={draft.tone_notes}
                onChange={(e) => set("tone_notes", e.target.value)}
                maxLength={300}
              />
            ))}
          </>
        );
      case "timezone":
        return (
          <>
            {field("Time zone", "timezone", (p) => (
              <Select
                {...p}
                value={draft.timezone}
                onChange={(e) => set("timezone", e.target.value)}
              >
                {timeZoneOptions(draft.timezone).map((z) => (
                  <option key={z} value={z}>
                    {z}
                  </option>
                ))}
              </Select>
            ))}
            <Button
              variant="secondary"
              size="sm"
              className="self-start"
              onClick={() =>
                set("timezone", Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC")
              }
            >
              Use my device&apos;s time zone
            </Button>
          </>
        );
      case "goal":
        return (
          <>
            <fieldset
              className="flex flex-col gap-2"
              aria-describedby={errors.goal ? "goal-error" : undefined}
            >
              <legend className="mb-1.5 text-sm font-medium text-fg">Main goal</legend>
              {GOALS.map(([value, label]) => (
                <label
                  key={value}
                  className="flex cursor-pointer items-center gap-3 rounded-md border border-line bg-surface p-3 has-[:checked]:border-accent"
                >
                  <input
                    type="radio"
                    name="goal"
                    value={value}
                    checked={draft.goal === value}
                    onChange={() => set("goal", value)}
                    className="accent-[var(--fos-accent)]"
                    required
                  />
                  <span className="text-sm text-fg">{label}</span>
                </label>
              ))}
              {errors.goal ? (
                <p id="goal-error" className="text-[13px] text-danger">
                  {errors.goal}
                </p>
              ) : null}
            </fieldset>
            <div className="rounded-md border border-line bg-surface p-3">
              <Checkbox
                label="Explore in demo mode"
                description="Nothing real is connected or sent. Handy for trying things out first. You can change this any time."
                checked={state.demo_mode}
                onCheckedChange={(v) => void toggleDemo(v === true)}
                disabled={pending}
              />
            </div>
          </>
        );
      default:
        return null;
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-fg">Set up your profile</h1>
        <p className="mt-1 text-sm text-muted">
          Tell us how you work so drafts and fit scores reflect your real services. You can stop and
          come back anytime.
        </p>
      </div>

      <nav aria-label="Onboarding steps">
        <p className="text-sm text-muted" aria-live="polite">
          Step {index + 1} of {state.total_count}: <span className="text-fg">{meta?.label}</span>
          {optional ? " (optional)" : ""} · {state.completed_count} saved
        </p>
        <div
          role="progressbar"
          aria-label="Steps saved"
          aria-valuemin={0}
          aria-valuemax={state.total_count}
          aria-valuenow={state.completed_count}
          className="mt-2 h-1.5 overflow-hidden rounded-full bg-elevated"
        >
          <div
            className="h-full bg-accent transition-[width]"
            style={{ width: `${(state.completed_count / state.total_count) * 100}%` }}
          />
        </div>
        <ol className="mt-3 flex flex-wrap gap-1.5">
          {state.steps.map((s) => (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => {
                  setStep(s.id);
                  setErrors({});
                  setBanner(null);
                }}
                {...(s.id === step ? { "aria-current": "step" as const } : {})}
                className={`rounded-full border px-2.5 py-1 text-xs ${s.id === step ? "border-accent text-fg" : "border-line text-muted hover:text-fg"}`}
              >
                {s.label}
                <span className="sr-only">
                  {s.completed ? " (saved)" : s.required ? " (required, not saved)" : " (optional)"}
                </span>
                {s.completed ? <span aria-hidden> ✓</span> : null}
              </button>
            </li>
          ))}
        </ol>
      </nav>

      {banner ? (
        <Notice tone={banner.tone} title={banner.title}>
          {banner.text}
        </Notice>
      ) : null}

      <form onSubmit={onSubmit} aria-labelledby="step-title" className="flex flex-col gap-4">
        <div>
          <h2
            id="step-title"
            ref={heading}
            tabIndex={-1}
            className="text-lg font-semibold text-fg outline-none"
          >
            {copy?.title}
          </h2>
          <p className="mt-1 text-sm text-muted">{copy?.description}</p>
        </div>
        {fields()}
        <div className="flex flex-wrap items-center justify-between gap-2 pt-2">
          <Button
            variant="secondary"
            disabled={index === 0 || pending}
            onClick={() => {
              setStep(state.steps[index - 1]?.id ?? step);
              setErrors({});
              setBanner(null);
            }}
          >
            Back
          </Button>
          <div className="flex gap-2">
            {optional && !isLast ? (
              <Button
                variant="ghost"
                disabled={pending}
                onClick={() => {
                  setStep(state.steps[index + 1]?.id ?? step);
                  setErrors({});
                }}
              >
                Skip this step
              </Button>
            ) : null}
            <Button type="submit" disabled={pending} aria-busy={pending}>
              {pending ? "Saving…" : isLast ? "Finish" : "Save and continue"}
            </Button>
          </div>
        </div>
      </form>

      <div className="flex flex-col items-center gap-1 text-center text-sm">
        <button
          type="button"
          onClick={() => void finishLater()}
          disabled={pending}
          className="text-fg underline underline-offset-4"
        >
          Save and finish later
        </button>
        <p className="text-muted">
          Your answers are kept. You can pick up where you left off from the banner on Home.
        </p>
        <Link href="/" className="sr-only focus:not-sr-only">
          Leave without saving
        </Link>
      </div>
    </div>
  );
}
