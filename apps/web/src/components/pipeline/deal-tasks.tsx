"use client";

import { Check, ChevronDown, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useId, useState } from "react";
import { Badge, Button, ConfirmDialog, Notice, useToast } from "@freelancer-os/ui";
import { browserApi, toFailure } from "@/lib/api-client";
import { describeFailure, type MutationFailure } from "@/lib/mutation-error";
import { TaskDrawer } from "@/components/tasks/task-drawer";
import { formatDue, priorityLabel, type TaskOut } from "@/components/tasks/task-model";

export interface TaskPage {
  items: TaskOut[];
  total: number;
}

type TaskAction = "complete" | "reopen" | "dismiss";
type DrawerState = { mode: "new" } | { mode: "edit"; task: TaskOut };

const DONE_LABEL: Record<TaskAction, string> = {
  complete: "Task completed",
  reopen: "Task reopened",
  dismiss: "Task dismissed",
};

/** The deal's own to-do list: open tasks first, recently finished ones tucked away, and a way to add more. */
export function DealTasks({
  workspaceId,
  deal,
  open,
  done,
  canEdit,
}: {
  workspaceId: string;
  deal: { id: string; title: string };
  open: TaskPage;
  done: TaskPage;
  canEdit: boolean;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const doneId = useId();

  // Render from what the last action returned; take the server's lists again once they refresh.
  const [openItems, setOpenItems] = useState(open.items);
  const [doneItems, setDoneItems] = useState(done.items);
  const [openTotal, setOpenTotal] = useState(open.total);
  const [doneTotal, setDoneTotal] = useState(done.total);
  const [seen, setSeen] = useState({ open, done });
  if (seen.open !== open || seen.done !== done) {
    setSeen({ open, done });
    setOpenItems(open.items);
    setDoneItems(done.items);
    setOpenTotal(open.total);
    setDoneTotal(done.total);
  }

  const [busyId, setBusyId] = useState<string | null>(null);
  const [banner, setBanner] = useState<MutationFailure | null>(null);
  const [drawer, setDrawer] = useState<DrawerState | null>(null);
  const [confirmDismiss, setConfirmDismiss] = useState<TaskOut | null>(null);
  const [showDone, setShowDone] = useState(false);

  async function act(task: TaskOut, action: TaskAction) {
    if (busyId) return;
    setBusyId(task.id);
    setBanner(null);
    const options = { params: { path: { workspace_id: workspaceId, task_id: task.id } } };
    try {
      const api = browserApi();
      const { data, error, response } =
        action === "complete"
          ? await api.POST("/api/v1/workspaces/{workspace_id}/tasks/{task_id}/complete", options)
          : action === "reopen"
            ? await api.POST("/api/v1/workspaces/{workspace_id}/tasks/{task_id}/reopen", options)
            : await api.POST("/api/v1/workspaces/{workspace_id}/tasks/{task_id}/dismiss", options);
      if (response.ok && data) {
        if (action === "complete") {
          setOpenItems((l) => l.filter((t) => t.id !== task.id));
          setOpenTotal((n) => Math.max(0, n - 1));
          setDoneItems((l) => [data, ...l.filter((t) => t.id !== task.id)]);
          setDoneTotal((n) => n + 1);
        } else if (action === "reopen") {
          setDoneItems((l) => l.filter((t) => t.id !== task.id));
          setDoneTotal((n) => Math.max(0, n - 1));
          setOpenItems((l) => [data, ...l.filter((t) => t.id !== task.id)]);
          setOpenTotal((n) => n + 1);
        } else {
          setOpenItems((l) => l.filter((t) => t.id !== task.id));
          setOpenTotal((n) => Math.max(0, n - 1));
        }
        toast({ title: DONE_LABEL[action], description: task.title, tone: "success" });
        router.refresh();
      } else {
        const out = describeFailure(error, response, "task");
        if (out) setBanner(out.failure);
      }
    } catch {
      setBanner({ title: "That didn't work", text: toFailure(undefined).message });
    }
    setBusyId(null);
  }

  const empty = openItems.length === 0 && doneItems.length === 0;

  return (
    <section
      aria-labelledby="deal-tasks-h"
      className="rounded-lg border border-line bg-surface p-5"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="deal-tasks-h" className="text-base font-semibold text-fg">
          Tasks
        </h2>
        <div className="flex items-center gap-2">
          <Link
            href="/tasks"
            className="text-sm text-muted underline underline-offset-4 hover:text-fg"
          >
            All tasks
          </Link>
          {canEdit ? (
            <Button variant="secondary" size="sm" onClick={() => setDrawer({ mode: "new" })}>
              Add task
            </Button>
          ) : null}
        </div>
      </div>

      {banner ? (
        <div className="mt-3">
          <Notice tone="danger" title={banner.title}>
            {banner.text}
          </Notice>
        </div>
      ) : null}

      {empty ? (
        <p className="mt-3 text-sm text-muted">No tasks for this deal yet.</p>
      ) : openItems.length === 0 ? (
        <p className="mt-3 text-sm text-muted">Nothing left to do on this deal.</p>
      ) : (
        <ul className="mt-3 flex flex-col gap-2" aria-label="Open tasks">
          {openItems.map((t) => (
            <li
              key={t.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-line p-3"
            >
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium break-words text-fg">{t.title}</p>
                <p className="mt-1 flex flex-wrap items-center gap-2 text-[13px] text-muted">
                  <Badge tone={t.priority === "high" ? "warning" : "neutral"}>
                    {priorityLabel(t.priority)} priority
                  </Badge>
                  {t.due_at ? (
                    <time dateTime={t.due_at}>Due {formatDue(t.due_at, t.due_timezone)}</time>
                  ) : (
                    <span>No due date</span>
                  )}
                  {t.is_overdue ? <Badge tone="danger">Overdue</Badge> : null}
                </p>
              </div>
              {canEdit ? (
                <div className="flex items-center gap-1">
                  <Button
                    variant="secondary"
                    size="sm"
                    aria-label={`Complete task: ${t.title}`}
                    aria-busy={busyId === t.id}
                    disabled={busyId !== null}
                    onClick={() => void act(t, "complete")}
                  >
                    <Check className="size-4" aria-hidden />
                    {busyId === t.id ? "Saving…" : "Complete"}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={`Edit task: ${t.title}`}
                    disabled={busyId !== null}
                    onClick={() => setDrawer({ mode: "edit", task: t })}
                  >
                    Edit
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={`Dismiss task: ${t.title}`}
                    disabled={busyId !== null}
                    onClick={() => setConfirmDismiss(t)}
                  >
                    Dismiss
                  </Button>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {openTotal > openItems.length ? (
        <p className="mt-2 text-[13px] text-muted">
          Showing {openItems.length} of {openTotal} open tasks. See all of them under All tasks.
        </p>
      ) : null}

      {doneItems.length > 0 ? (
        <div className="mt-4 border-t border-line pt-3">
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-sm text-sm text-muted hover:text-fg"
            aria-expanded={showDone}
            aria-controls={doneId}
            onClick={() => setShowDone((v) => !v)}
          >
            {showDone ? (
              <ChevronDown className="size-4" aria-hidden />
            ) : (
              <ChevronRight className="size-4" aria-hidden />
            )}
            Recently done ({doneTotal})
          </button>
          <div id={doneId} hidden={!showDone}>
            {showDone ? (
              <>
                <ul className="mt-2 flex flex-col gap-1.5" aria-label="Recently done tasks">
                  {doneItems.map((t) => (
                    <li
                      key={t.id}
                      className="flex flex-wrap items-center justify-between gap-2 text-sm"
                    >
                      <span className="min-w-0 break-words text-muted line-through">{t.title}</span>
                      <span className="flex items-center gap-2 text-[13px] text-muted">
                        {t.completed_at ? (
                          <time dateTime={t.completed_at}>Done {t.completed_at.slice(0, 10)}</time>
                        ) : (
                          <span>Done</span>
                        )}
                        {canEdit ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            aria-label={`Reopen task: ${t.title}`}
                            disabled={busyId !== null}
                            aria-busy={busyId === t.id}
                            onClick={() => void act(t, "reopen")}
                          >
                            Reopen
                          </Button>
                        ) : null}
                      </span>
                    </li>
                  ))}
                </ul>
                {doneTotal > doneItems.length ? (
                  <p className="mt-2 text-[13px] text-muted">
                    Showing the {doneItems.length} most recent of {doneTotal}.
                  </p>
                ) : null}
              </>
            ) : null}
          </div>
        </div>
      ) : null}

      {drawer && canEdit ? (
        <TaskDrawer
          key={drawer.mode === "edit" ? drawer.task.id : "new"}
          workspaceId={workspaceId}
          {...(drawer.mode === "edit"
            ? { task: drawer.task }
            : { links: { opportunity_id: deal.id }, linkLabel: deal.title })}
          onClose={() => setDrawer(null)}
        />
      ) : null}
      <ConfirmDialog
        open={confirmDismiss !== null}
        onOpenChange={(o) => !o && setConfirmDismiss(null)}
        title="Dismiss this task?"
        description="It leaves the list without being marked as done."
        confirmLabel="Dismiss task"
        destructive
        onConfirm={() => {
          if (confirmDismiss) void act(confirmDismiss, "dismiss");
        }}
      />
    </section>
  );
}
