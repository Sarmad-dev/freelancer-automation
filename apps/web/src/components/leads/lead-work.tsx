"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Badge, Button, useToast } from "@freelancer-os/ui";
import { browserApi, toFailure } from "@/lib/api-client";
import { describeFailure } from "@/lib/mutation-error";
import {
  dealStatusTone,
  formatMoney,
  DEAL_STATUS_LABEL,
  type OpportunityOut,
  type PipelineStage,
} from "@/components/pipeline/pipeline-model";
import { OpportunityCreateDrawer } from "@/components/pipeline/opportunity-create-drawer";
import { TaskDrawer } from "@/components/tasks/task-drawer";
import { formatDue, priorityLabel, type TaskOut } from "@/components/tasks/task-model";

const card = "rounded-lg border border-line bg-surface p-5";

/**
 * What the freelancer is working on with this lead: the deals it has become and the follow-ups still to do.
 * Both lists come from the server page; mutations refresh it.
 */
export function LeadWork({
  workspaceId,
  leadId,
  leadTitle,
  deals,
  tasks,
  stages,
  timezone,
  canEdit,
}: {
  workspaceId: string;
  leadId: string;
  leadTitle: string;
  deals: OpportunityOut[];
  tasks: TaskOut[];
  stages: PipelineStage[];
  timezone: string;
  canEdit: boolean;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const [newDeal, setNewDeal] = useState(false);
  const [newTask, setNewTask] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  async function complete(task: TaskOut) {
    if (busy) return;
    setBusy(task.id);
    setFailed(null);
    try {
      const { error, response } = await browserApi().POST(
        "/api/v1/workspaces/{workspace_id}/tasks/{task_id}/complete",
        { params: { path: { workspace_id: workspaceId, task_id: task.id } } },
      );
      if (response.ok) {
        toast({ title: "Task done", description: task.title, tone: "success" });
        router.refresh();
      } else {
        setFailed(describeFailure(error, response, "task")?.failure.text ?? null);
      }
    } catch {
      setFailed(toFailure(undefined).message);
    }
    setBusy(null);
  }

  return (
    <>
      <section aria-labelledby="lead-deals-h" className={card}>
        <div className="flex items-center justify-between gap-2">
          <h2 id="lead-deals-h" className="text-base font-semibold text-fg">
            Deals
          </h2>
          {canEdit ? (
            <Button variant="secondary" size="sm" onClick={() => setNewDeal(true)}>
              New deal
            </Button>
          ) : null}
        </div>
        {deals.length === 0 ? (
          <p className="mt-3 text-sm text-muted">
            No deals yet. Create one when this lead turns into work you could win.
          </p>
        ) : (
          <ul className="mt-3 flex flex-col divide-y divide-line">
            {deals.map((deal) => (
              <li key={deal.id} className="flex flex-col gap-1 py-2.5 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Link
                    href={`/pipeline/${deal.id}`}
                    className="text-sm font-medium text-fg underline-offset-4 hover:underline"
                  >
                    {deal.title}
                  </Link>
                  <Badge tone={dealStatusTone(deal.status)}>
                    {DEAL_STATUS_LABEL[deal.status] ?? deal.status}
                  </Badge>
                </div>
                <p className="text-[13px] text-muted">
                  {deal.stage.name}
                  {deal.value_amount
                    ? ` · ${formatMoney(deal.value_amount, deal.currency)}`
                    : " · No value yet"}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="lead-tasks-h" className={card}>
        <div className="flex items-center justify-between gap-2">
          <h2 id="lead-tasks-h" className="text-base font-semibold text-fg">
            Follow-ups
          </h2>
          {canEdit ? (
            <Button variant="secondary" size="sm" onClick={() => setNewTask(true)}>
              New task
            </Button>
          ) : null}
        </div>
        {failed ? (
          <p role="alert" className="mt-3 text-sm text-danger">
            {failed}
          </p>
        ) : null}
        {tasks.length === 0 ? (
          <p className="mt-3 text-sm text-muted">Nothing to do for this lead right now.</p>
        ) : (
          <ul className="mt-3 flex flex-col divide-y divide-line">
            {tasks.map((task) => (
              <li
                key={task.id}
                className="flex items-start justify-between gap-3 py-2.5 first:pt-0 last:pb-0"
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium break-words text-fg">{task.title}</p>
                  <p className="text-[13px] text-muted">
                    {task.due_at ? formatDue(task.due_at, task.due_timezone) : "No due date"}
                    {task.priority !== "normal"
                      ? ` · ${priorityLabel(task.priority)} priority`
                      : ""}
                  </p>
                  {task.is_overdue ? <Badge tone="danger">Overdue</Badge> : null}
                </div>
                {canEdit ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy !== null}
                    aria-label={`Complete: ${task.title}`}
                    onClick={() => void complete(task)}
                  >
                    Done
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
        <p className="mt-3 text-[13px]">
          <Link href="/tasks" className="text-muted underline underline-offset-4 hover:text-fg">
            All tasks
          </Link>
        </p>
      </section>

      {newDeal ? (
        <OpportunityCreateDrawer
          workspaceId={workspaceId}
          leadId={leadId}
          stages={stages}
          onClose={() => setNewDeal(false)}
        />
      ) : null}
      {newTask ? (
        <TaskDrawer
          workspaceId={workspaceId}
          links={{ lead_id: leadId }}
          linkLabel={leadTitle}
          defaultTimezone={timezone}
          onClose={() => setNewTask(false)}
        />
      ) : null}
    </>
  );
}
