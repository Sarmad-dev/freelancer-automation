import type { Metadata } from "next";
import Link from "next/link";
import { Button, Field, Input, Notice, Textarea } from "@freelancer-os/ui";

export const metadata: Metadata = { title: "Onboarding" };

const STEPS = [
  "Role",
  "Services",
  "Skills",
  "Target clients",
  "Industries",
  "Portfolio",
  "Experience",
  "Tone",
  "Time zone",
  "Goal",
] as const;

export default function OnboardingPage() {
  const current = 0;
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-fg">Set up your profile</h1>
        <p className="mt-1 text-sm text-muted">
          Tell us how you work so drafts and fit scores reflect your real services. You can skip and
          come back anytime.
        </p>
      </div>

      <Notice tone="info" title="Preview only">
        Saving progress, validation and demo mode are built in the onboarding phase. The form below
        is disabled.
      </Notice>

      <nav aria-label="Onboarding progress">
        <p className="text-sm text-muted">
          Step {current + 1} of {STEPS.length}: <span className="text-fg">{STEPS[current]}</span>
        </p>
        <div
          role="progressbar"
          aria-label="Onboarding progress"
          aria-valuemin={0}
          aria-valuemax={STEPS.length}
          aria-valuenow={current + 1}
          className="mt-2 h-1.5 overflow-hidden rounded-full bg-elevated"
        >
          <div
            className="h-full bg-accent"
            style={{ width: `${((current + 1) / STEPS.length) * 100}%` }}
          />
        </div>
        <ol className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
          {STEPS.map((s, i) => (
            <li
              key={s}
              {...(i === current ? { "aria-current": "step" as const } : {})}
              className={i === current ? "font-medium text-fg" : undefined}
            >
              {s}
            </li>
          ))}
        </ol>
      </nav>

      <form aria-label="Onboarding step: Role (preview)" className="flex flex-col gap-4">
        <fieldset disabled className="flex flex-col gap-4">
          <legend className="sr-only">Your role</legend>
          <Field label="What best describes you?">
            {(p) => <Input {...p} placeholder="e.g. Independent web developer" />}
          </Field>
          <Field
            label="One-line summary"
            hint="Used to describe you in drafts, only after you approve it."
          >
            {(p) => <Textarea {...p} />}
          </Field>
          <div className="flex justify-between gap-2">
            <Button variant="secondary">Back</Button>
            <Button type="submit">Continue</Button>
          </div>
        </fieldset>
      </form>

      <p className="text-center text-sm">
        <Link href="/" className="text-fg underline underline-offset-4">
          Skip for now
        </Link>
      </p>
    </div>
  );
}
