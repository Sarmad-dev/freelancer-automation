"use client";

import {
  ArrowRightLeft,
  Cog,
  ListChecks,
  Mail,
  Phone,
  StickyNote,
  Users,
  type LucideIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Button, Field, Input, Notice, Select, Textarea, useToast } from "@freelancer-os/ui";
import { browserApi, toFailure } from "@/lib/api-client";
import { describeFailure, type MutationFailure } from "@/lib/mutation-error";
import { formatDateTime, type ActivityOut } from "@/components/leads/lead-model";
import type { PipelineStage } from "./pipeline-model";

export const DEAL_ACTIVITY_PAGE_SIZE = 50;

const KINDS: Record<string, { label: string; icon: LucideIcon }> = {
  note: { label: "Note", icon: StickyNote },
  call: { label: "Call", icon: Phone },
  meeting: { label: "Meeting", icon: Users },
  email: { label: "Email", icon: Mail },
  task: { label: "Task", icon: ListChecks },
  stage_change: { label: "Stage change", icon: ArrowRightLeft },
  system: { label: "System", icon: Cog },
};

const LOGGABLE = [
  { value: "note", label: "Note" },
  { value: "call", label: "Call" },
  { value: "meeting", label: "Meeting" },
] as const;
type LoggableKind = (typeof LOGGABLE)[number]["value"];

function kindMeta(kind: string): { label: string; icon: LucideIcon } {
  return KINDS[kind] ?? { label: kind.replace(/_/g, " "), icon: StickyNote };
}

function detailText(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function Entry({
  activity,
  isOwner,
  stageNames,
}: {
  activity: ActivityOut;
  isOwner: boolean;
  stageNames: Map<string, string>;
}) {
  const meta = kindMeta(activity.kind);
  const Icon = meta.icon;
  const fromKey = detailText(activity.details?.from);
  const toKey = detailText(activity.details?.to);
  const from = fromKey ? (stageNames.get(fromKey) ?? fromKey) : null;
  const to = toKey ? (stageNames.get(toKey) ?? toKey) : null;
  const actor = activity.actor_user_id ? (isOwner ? "You" : "Workspace owner") : "System";
  return (
    <li className="flex gap-3 rounded-md border border-line p-3">
      <span
        aria-hidden
        className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-elevated text-muted"
      >
        <Icon className="size-4" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-[13px] text-muted">
          <span className="font-medium text-fg">{meta.label}</span>
          {" · "}
          <time dateTime={activity.occurred_at}>{formatDateTime(activity.occurred_at)}</time>
          {" · "}
          {actor}
        </p>
        <p className="mt-0.5 text-sm font-medium break-words text-fg">{activity.summary}</p>
        {activity.kind === "stage_change" && (from || to) ? (
          <p className="mt-0.5 text-sm break-words text-muted">
            {from && to ? `${from} → ${to}` : to ? `Moved to ${to}` : `Moved from ${from}`}
          </p>
        ) : null}
        {activity.body ? (
          <p className="mt-1 text-sm break-words whitespace-pre-wrap text-fg">{activity.body}</p>
        ) : null}
      </div>
    </li>
  );
}

/** Newest-first activity list, with a form to log a note, call or meeting (owner only). */
export function DealTimeline({
  workspaceId,
  dealId,
  activities,
  total,
  stages,
  canLog,
  isOwner,
}: {
  workspaceId: string;
  dealId: string;
  activities: ActivityOut[];
  total: number;
  stages: readonly Pick<PipelineStage, "key" | "name">[];
  canLog: boolean;
  isOwner: boolean;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const [items, setItems] = useState(activities);
  const [count, setCount] = useState(total);
  const [seen, setSeen] = useState(activities);
  // The server sent fresh data (after router.refresh()): start from it.
  if (activities !== seen) {
    setSeen(activities);
    setItems(activities);
    setCount(total);
  }

  const [kind, setKind] = useState<LoggableKind>("note");
  const [summary, setSummary] = useState("");
  const [details, setDetails] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [banner, setBanner] = useState<MutationFailure | null>(null);
  const [pending, setPending] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState<string | null>(null);

  const stageNames = new Map(stages.map((s) => [s.key, s.name]));
  const path = { workspace_id: workspaceId, opportunity_id: dealId };

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (pending) return;
    if (!summary.trim()) {
      setErrors({ summary: "Say what happened." });
      return;
    }
    setPending(true);
    setBanner(null);
    setErrors({});
    try {
      const { data, error, response } = await browserApi().POST(
        "/api/v1/workspaces/{workspace_id}/opportunities/{opportunity_id}/activities",
        {
          params: { path },
          body: {
            kind,
            summary: summary.trim(),
            ...(details.trim() ? { body: details.trim() } : {}),
          },
        },
      );
      if (response.ok && data) {
        setItems((prev) => [data, ...prev.filter((a) => a.id !== data.id)]);
        setCount((c) => c + 1);
        setSummary("");
        setDetails("");
        toast({
          title: "Logged",
          description: `${kindMeta(kind).label} added to the timeline.`,
          tone: "success",
        });
        router.refresh();
      } else {
        const out = describeFailure(error, response, "deal");
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

  async function loadMore() {
    setLoadingMore(true);
    setMoreError(null);
    try {
      const { data, error, response } = await browserApi().GET(
        "/api/v1/workspaces/{workspace_id}/opportunities/{opportunity_id}/activities",
        { params: { path, query: { limit: DEAL_ACTIVITY_PAGE_SIZE, offset: items.length } } },
      );
      if (response.ok && data) {
        setItems((prev) => {
          const known = new Set(prev.map((a) => a.id));
          return [...prev, ...data.items.filter((a) => !known.has(a.id))];
        });
        setCount(data.total);
      } else {
        const out = describeFailure(error, response, "deal");
        if (out) setMoreError(out.failure.text);
      }
    } catch {
      setMoreError(toFailure(undefined).message);
    }
    setLoadingMore(false);
  }

  return (
    <section
      aria-labelledby="deal-timeline-h"
      className="rounded-lg border border-line bg-surface p-5"
    >
      <h2 id="deal-timeline-h" className="text-base font-semibold text-fg">
        Activity
      </h2>

      {canLog ? (
        <form
          onSubmit={(e) => void submit(e)}
          aria-label="Log activity"
          aria-busy={pending}
          className="mt-4 flex flex-col gap-3 rounded-md border border-line bg-canvas p-3"
        >
          {banner ? (
            <Notice tone="danger" title={banner.title}>
              {banner.text}
            </Notice>
          ) : null}
          <div className="grid gap-3 sm:grid-cols-[10rem_1fr]">
            <Field label="What happened" {...(errors.kind ? { error: errors.kind } : {})}>
              {(p) => (
                <Select
                  {...p}
                  value={kind}
                  onChange={(e) => setKind(e.target.value as LoggableKind)}
                >
                  {LOGGABLE.map((k) => (
                    <option key={k.value} value={k.value}>
                      {k.label}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label="Summary" required {...(errors.summary ? { error: errors.summary } : {})}>
              {(p) => (
                <Input
                  {...p}
                  value={summary}
                  maxLength={200}
                  onChange={(e) => setSummary(e.target.value)}
                />
              )}
            </Field>
          </div>
          <Field label="Details (optional)" {...(errors.body ? { error: errors.body } : {})}>
            {(p) => (
              <Textarea
                {...p}
                rows={3}
                value={details}
                maxLength={4000}
                onChange={(e) => setDetails(e.target.value)}
              />
            )}
          </Field>
          <div>
            <Button type="submit" disabled={pending} aria-busy={pending}>
              {pending ? "Logging…" : "Add to timeline"}
            </Button>
          </div>
        </form>
      ) : null}

      {items.length === 0 ? (
        <p className="mt-4 text-sm text-muted">Nothing has happened on this deal yet.</p>
      ) : (
        <ol className="mt-4 flex flex-col gap-2" aria-label="Activity, newest first">
          {items.map((a) => (
            <Entry key={a.id} activity={a} isOwner={isOwner} stageNames={stageNames} />
          ))}
        </ol>
      )}

      {moreError ? (
        <div className="mt-3">
          <Notice tone="danger" title="Couldn't load older activity">
            {moreError}
          </Notice>
        </div>
      ) : null}
      {items.length < count ? (
        <div className="mt-3 flex items-center gap-3">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => void loadMore()}
            disabled={loadingMore}
            aria-busy={loadingMore}
          >
            {loadingMore ? "Loading…" : "Show older activity"}
          </Button>
          <span className="text-[13px] text-muted">
            Showing {items.length} of {count}
          </span>
        </div>
      ) : null}
    </section>
  );
}
