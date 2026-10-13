"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useRef, useState } from "react";
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  Field,
  Input,
  Notice,
  Select,
  useToast,
} from "@freelancer-os/ui";
import { SampleBadge } from "@/components/leads/lead-badges";
import { browserApi, toFailure } from "@/lib/api-client";
import { describeFailure } from "@/lib/mutation-error";
import {
  PAGE_SIZE,
  TASKS_PATH,
  defaultSort,
  hasTaskFilters,
  overdueText,
  pageHref,
  sortsFor,
  tabHref,
  type TaskQuery,
} from "./task-list-model";
import { TaskRescheduleDialog } from "./task-reschedule-dialog";
import { TaskDrawer } from "./task-drawer";
import {
  PRIORITIES,
  TASK_VIEWS,
  formatDue,
  priorityLabel,
  timeZoneOptions,
  type TaskOut,
  type TaskSummary,
  type TaskViewName,
} from "./task-model";

const NOTHING: ReadonlySet<string> = new Set();

type ActionKind = "complete" | "reopen" | "dismiss";

const ACTION_TEXT: Record<ActionKind, { done: string; failed: string }> = {
  complete: { done: "Task completed", failed: "Couldn't complete this task" },
  reopen: { done: "Task reopened", failed: "Couldn't reopen this task" },
  dismiss: { done: "Task dismissed", failed: "Couldn't dismiss this task" },
};

const linkButton =
  "inline-flex h-8 items-center rounded-md border border-line bg-elevated px-3 text-[13px] font-medium text-fg";

const EMPTY: Record<TaskViewName, { title: string; description: string }> = {
  today: {
    title: "Nothing due today",
    description: "Tasks that are still due before midnight in your time zone show up here.",
  },
  overdue: {
    title: "You're all caught up",
    description: "Nothing is past its due time.",
  },
  upcoming: {
    title: "Nothing coming up",
    description: "Tasks due after today appear here.",
  },
  undated: {
    title: "No tasks without a date",
    description: "Every open task has a due date.",
  },
  done: {
    title: "No finished tasks yet",
    description: "Tasks you complete are kept here.",
  },
};

const VIEW_LABEL: Record<TaskViewName, string> = Object.fromEntries(
  TASK_VIEWS.map((v) => [v.value, v.label]),
) as Record<TaskViewName, string>;

export function TasksView({
  workspaceId,
  tasks,
  total,
  summary,
  query,
  now,
  canEdit,
}: {
  workspaceId: string;
  tasks: TaskOut[];
  total: number;
  summary: TaskSummary;
  query: TaskQuery;
  /** Server time (ISO). "How long overdue" and the reschedule presets are worked out from it. */
  now: string;
  canEdit: boolean;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<TaskOut | null>(null);
  const [rescheduling, setRescheduling] = useState<TaskOut | null>(null);
  const [dismissing, setDismissing] = useState<TaskOut | null>(null);
  /** Rows taken off the list while their request is out. Put back if it fails. */
  const [hiding, setHiding] = useState<{ for: TaskOut[]; ids: ReadonlySet<string> }>({
    for: tasks,
    ids: new Set(),
  });
  const [pending, setPending] = useState<ReadonlySet<string>>(new Set());
  const [failures, setFailures] = useState<Record<string, { title: string; text: string }>>({});
  const inFlight = useRef(new Set<string>());
  const listHeading = useRef<HTMLHeadingElement>(null);

  // New data from the server replaces whatever we were hiding.
  const hidden: ReadonlySet<string> = hiding.for === tasks ? hiding.ids : NOTHING;
  const setHidden = (update: (ids: ReadonlySet<string>) => ReadonlySet<string>) =>
    setHiding((h) => ({ for: tasks, ids: update(h.for === tasks ? h.ids : NOTHING) }));

  const visible = useMemo(() => tasks.filter((t) => !hidden.has(t.id)), [tasks, hidden]);
  const zone = summary.timezone;
  const zones = useMemo(() => timeZoneOptions(zone), [zone]);
  const filtered = hasTaskFilters(query);
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const everything =
    summary.overdue + summary.today + summary.upcoming + summary.undated + summary.done;
  const counts: Record<TaskViewName, number> = {
    overdue: summary.overdue,
    today: summary.today,
    upcoming: summary.upcoming,
    undated: summary.undated,
    done: summary.done,
  };

  const toggle = (set: ReadonlySet<string>, id: string, on: boolean): ReadonlySet<string> => {
    const next = new Set(set);
    if (on) next.add(id);
    else next.delete(id);
    return next;
  };

  async function act(task: TaskOut, kind: ActionKind) {
    if (inFlight.current.has(task.id)) return; // repeat clicks while a request is out do nothing
    inFlight.current.add(task.id);
    setPending((p) => toggle(p, task.id, true));
    setFailures(({ [task.id]: _gone, ...rest }) => rest);
    setHidden((h) => toggle(h, task.id, true)); // optimistic: put back below if the request fails
    listHeading.current?.focus();
    let failure: { title: string; text: string } | null = null;
    try {
      const api = browserApi();
      const params = { params: { path: { workspace_id: workspaceId, task_id: task.id } } };
      const { error, response } =
        kind === "complete"
          ? await api.POST("/api/v1/workspaces/{workspace_id}/tasks/{task_id}/complete", params)
          : kind === "reopen"
            ? await api.POST("/api/v1/workspaces/{workspace_id}/tasks/{task_id}/reopen", params)
            : await api.POST("/api/v1/workspaces/{workspace_id}/tasks/{task_id}/dismiss", params);
      if (response.ok) {
        toast({ title: ACTION_TEXT[kind].done, description: task.title, tone: "success" });
        router.refresh();
      } else {
        const out = describeFailure(error, response, "task");
        // null = the session ended and the browser is already on its way to sign-in.
        failure = out
          ? { title: ACTION_TEXT[kind].failed, text: out.failure.text }
          : { title: ACTION_TEXT[kind].failed, text: "Your session ended. Sign in again." };
      }
    } catch {
      failure = { title: ACTION_TEXT[kind].failed, text: toFailure(undefined).message };
    }
    inFlight.current.delete(task.id);
    setPending((p) => toggle(p, task.id, false));
    if (failure) {
      const shown = failure;
      setHidden((h) => toggle(h, task.id, false)); // rollback
      setFailures((f) => ({ ...f, [task.id]: shown }));
    }
  }

  const stateLine = (
    <div className="flex flex-col gap-1 text-[13px] text-muted">
      <p>
        Overdue means a task is already past its due time. Today means it is still due before
        midnight in the time zone below.
      </p>
    </div>
  );

  return (
    <div className="flex flex-col gap-5">
      {!canEdit ? (
        <Notice tone="info" title="View only">
          Only the workspace owner can add, change or complete tasks.
        </Notice>
      ) : null}

      <nav aria-label="Task views">
        <ul className="flex flex-wrap gap-2">
          {TASK_VIEWS.map((v) => {
            const active = v.value === query.view;
            return (
              <li key={v.value}>
                <Link
                  href={tabHref(query, v.value)}
                  {...(active ? { "aria-current": "page" as const } : {})}
                  className={
                    active
                      ? "inline-flex h-9 items-center rounded-md border border-accent bg-accent/10 px-3 text-sm font-semibold text-fg"
                      : "inline-flex h-9 items-center rounded-md border border-line bg-elevated px-3 text-sm text-fg hover:brightness-110"
                  }
                >
                  {`${v.label} (${counts[v.value]})`}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {stateLine}

      <div className="flex flex-wrap items-end gap-3">
        <form
          action={TASKS_PATH}
          method="get"
          aria-label="Time zone"
          className="flex flex-wrap items-end gap-3"
        >
          {query.view !== "today" ? <input type="hidden" name="view" value={query.view} /> : null}
          {query.priority ? <input type="hidden" name="priority" value={query.priority} /> : null}
          {query.q ? <input type="hidden" name="q" value={query.q} /> : null}
          {query.sort ? <input type="hidden" name="sort" value={query.sort} /> : null}
          <Field
            label="Showing today in"
            hint="Today means your local day in this time zone."
            className="min-w-56"
          >
            {(p) => (
              <Select {...p} name="tz" defaultValue={zone}>
                {zones.map((z) => (
                  <option key={z} value={z}>
                    {z}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Button type="submit" variant="secondary">
            Change zone
          </Button>
        </form>
        {canEdit ? (
          <Button className="ml-auto" onClick={() => setCreating(true)}>
            New task
          </Button>
        ) : null}
      </div>

      <form
        action={TASKS_PATH}
        method="get"
        role="search"
        aria-label="Filter tasks"
        className="flex flex-wrap items-end gap-3"
      >
        {query.view !== "today" ? <input type="hidden" name="view" value={query.view} /> : null}
        {query.tz ? <input type="hidden" name="tz" value={query.tz} /> : null}
        <Field label="Search" className="min-w-48 flex-1 sm:max-w-xs">
          {(p) => (
            <Input
              {...p}
              name="q"
              type="search"
              defaultValue={query.q}
              maxLength={100}
              placeholder="Title or details"
            />
          )}
        </Field>
        <Field label="Priority">
          {(p) => (
            <Select {...p} name="priority" defaultValue={query.priority}>
              <option value="">Any priority</option>
              {PRIORITIES.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Sort by">
          {(p) => (
            <Select {...p} name="sort" defaultValue={query.sort || defaultSort(query.view)}>
              {sortsFor(query.view).map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
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
            href={tabHref({ ...query, q: "", priority: "", sort: "" }, query.view)}
            className="inline-flex h-9 items-center px-2 text-sm text-muted underline underline-offset-4 hover:text-fg"
          >
            Clear filters
          </Link>
        ) : null}
      </form>

      {visible.length === 0 ? (
        tasks.length > 0 ? (
          <EmptyState
            title="That's the last one on this page"
            description="Everything here is done. Pick another view or reload for what's next."
          />
        ) : query.page > 1 && total > 0 ? (
          <EmptyState title="Nothing on this page" description="There are fewer tasks than that.">
            <Link href={pageHref(query, 1)} className={linkButton}>
              Back to the first page
            </Link>
          </EmptyState>
        ) : filtered ? (
          <EmptyState
            title="No tasks match those filters"
            description="Try a different search, or clear the filters."
          >
            <Link
              href={tabHref({ ...query, q: "", priority: "", sort: "" }, query.view)}
              className={linkButton}
            >
              Clear filters
            </Link>
          </EmptyState>
        ) : everything === 0 ? (
          <EmptyState
            title="No tasks yet"
            description="Add a follow-up or a reminder so nothing slips."
          >
            {canEdit ? <Button onClick={() => setCreating(true)}>New task</Button> : null}
          </EmptyState>
        ) : (
          <EmptyState {...EMPTY[query.view]}>
            {canEdit && query.view !== "done" ? (
              <Button variant="secondary" onClick={() => setCreating(true)}>
                New task
              </Button>
            ) : null}
          </EmptyState>
        )
      ) : (
        <section aria-labelledby="task-list-heading" className="flex flex-col gap-3">
          <h2
            id="task-list-heading"
            ref={listHeading}
            tabIndex={-1}
            className="sr-only"
          >{`${VIEW_LABEL[query.view]} tasks`}</h2>
          <ul className="flex flex-col gap-3">
            {visible.map((task) => (
              <TaskRow
                key={task.id}
                task={task}
                now={now}
                canEdit={canEdit}
                busy={pending.has(task.id)}
                failure={failures[task.id]}
                doneView={query.view === "done"}
                onComplete={() => void act(task, task.status === "open" ? "complete" : "reopen")}
                onReschedule={() => setRescheduling(task)}
                onEdit={() => setEditing(task)}
                onDismiss={() => setDismissing(task)}
              />
            ))}
          </ul>
        </section>
      )}

      {tasks.length > 0 || total > 0 ? (
        <nav aria-label="Pagination" className="flex items-center justify-between gap-4 text-sm">
          <p className="text-muted">
            Page {query.page} of {pageCount} · {total} {total === 1 ? "task" : "tasks"}
          </p>
          <div className="flex gap-2">
            {query.page > 1 ? (
              <Link rel="prev" href={pageHref(query, query.page - 1)} className={linkButton}>
                Previous
              </Link>
            ) : null}
            {query.page < pageCount ? (
              <Link rel="next" href={pageHref(query, query.page + 1)} className={linkButton}>
                Next
              </Link>
            ) : null}
          </div>
        </nav>
      ) : null}

      {creating ? (
        <TaskDrawer
          workspaceId={workspaceId}
          defaultTimezone={zone}
          onClose={() => setCreating(false)}
        />
      ) : null}
      {editing ? (
        <TaskDrawer
          workspaceId={workspaceId}
          task={editing}
          defaultTimezone={zone}
          onClose={() => setEditing(null)}
        />
      ) : null}
      {rescheduling ? (
        <TaskRescheduleDialog
          workspaceId={workspaceId}
          task={rescheduling}
          now={now}
          defaultTimezone={zone}
          onClose={() => setRescheduling(null)}
        />
      ) : null}
      <ConfirmDialog
        open={dismissing !== null}
        onOpenChange={(open) => !open && setDismissing(null)}
        title="Dismiss this task?"
        description="It stays in your history but leaves your lists."
        confirmLabel="Dismiss task"
        destructive
        onConfirm={() => {
          if (dismissing) void act(dismissing, "dismiss");
        }}
      />
    </div>
  );
}

function priorityTone(priority: string): "danger" | "neutral" | "info" {
  return priority === "high" ? "danger" : priority === "low" ? "info" : "neutral";
}

function TaskRow({
  task,
  now,
  canEdit,
  busy,
  failure,
  doneView,
  onComplete,
  onReschedule,
  onEdit,
  onDismiss,
}: {
  task: TaskOut;
  now: string;
  canEdit: boolean;
  busy: boolean;
  failure: { title: string; text: string } | undefined;
  doneView: boolean;
  onComplete: () => void;
  onReschedule: () => void;
  onEdit: () => void;
  onDismiss: () => void;
}) {
  const open = task.status === "open";
  const overdue = open && task.is_overdue && task.due_at;
  const zone = task.due_timezone ?? "UTC";
  const snippet = task.description
    ? task.description.length > 160
      ? `${task.description.slice(0, 160)}…`
      : task.description
    : "";
  return (
    <li
      aria-busy={busy}
      className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold break-words text-fg">{task.title}</h3>
            <Badge
              tone={priorityTone(task.priority)}
            >{`${priorityLabel(task.priority)} priority`}</Badge>
            {task.status === "done" ? <Badge tone="success">Done</Badge> : null}
            {task.status === "dismissed" ? <Badge>Dismissed</Badge> : null}
            {task.is_sample ? <SampleBadge /> : null}
          </div>
          {snippet ? <p className="mt-1 text-sm break-words text-muted">{snippet}</p> : null}
          <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-muted">
            {task.status === "done" && task.completed_at ? (
              <span>
                Completed{" "}
                <time dateTime={task.completed_at}>{formatDue(task.completed_at, zone)}</time>
              </span>
            ) : null}
            {task.due_at ? (
              <span>
                Due <time dateTime={task.due_at}>{formatDue(task.due_at, zone)}</time>
              </span>
            ) : (
              <span>No due date</span>
            )}
            {overdue && task.due_at ? (
              <span className="font-medium text-danger">{overdueText(task.due_at, now)}</span>
            ) : null}
            {open && task.remind_at ? (
              <span>
                Reminder <time dateTime={task.remind_at}>{formatDue(task.remind_at, zone)}</time>
              </span>
            ) : null}
          </p>
          {task.lead || task.opportunity ? (
            <p className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[13px]">
              {task.lead ? (
                <span>
                  Lead:{" "}
                  <Link
                    href={`/leads/${encodeURIComponent(task.lead.id)}`}
                    className="break-words underline underline-offset-4"
                  >
                    {task.lead.title}
                  </Link>
                </span>
              ) : null}
              {task.opportunity ? (
                <span>
                  Deal:{" "}
                  <Link
                    href={`/pipeline/${encodeURIComponent(task.opportunity.id)}`}
                    className="break-words underline underline-offset-4"
                  >
                    {task.opportunity.title}
                  </Link>
                </span>
              ) : null}
            </p>
          ) : null}
        </div>
        {canEdit ? (
          <div className="flex flex-wrap items-center gap-2">
            {open || doneView ? (
              <Button
                size="sm"
                variant={open ? "primary" : "secondary"}
                disabled={busy}
                aria-label={`${open ? "Complete" : "Reopen"}: ${task.title}`}
                onClick={onComplete}
              >
                {open ? "Complete" : "Reopen"}
              </Button>
            ) : null}
            {open ? (
              <Button
                size="sm"
                variant="secondary"
                disabled={busy}
                aria-label={`Reschedule: ${task.title}`}
                onClick={onReschedule}
              >
                Reschedule
              </Button>
            ) : null}
            <Button
              size="sm"
              variant="secondary"
              disabled={busy}
              aria-label={`Edit: ${task.title}`}
              onClick={onEdit}
            >
              Edit
            </Button>
            {open ? (
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                aria-label={`Dismiss: ${task.title}`}
                onClick={onDismiss}
              >
                Dismiss
              </Button>
            ) : null}
          </div>
        ) : null}
      </div>
      {failure ? (
        <Notice tone="danger" title={failure.title}>
          {failure.text}
        </Notice>
      ) : null}
    </li>
  );
}
