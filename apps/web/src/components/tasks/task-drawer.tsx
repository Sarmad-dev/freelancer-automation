"use client";

import { useMemo, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
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
  PRIORITIES,
  REMINDERS,
  browserTimeZone,
  buildTaskCreate,
  diffTask,
  emptyTaskForm,
  formFromTask,
  newIdempotencyKey,
  timeZoneOptions,
  validateTaskForm,
  type Priority,
  type TaskForm,
  type TaskOut,
} from "./task-model";

export interface TaskLinks {
  lead_id?: string;
  opportunity_id?: string;
  conversation_id?: string;
}

/**
 * Create or edit a task. Mount it to open it; it asks to be closed through `onClose`.
 *
 * - Create: pass `links` (the lead/deal/conversation the task belongs to) and `linkLabel` for the sentence shown to
 *   the person ("For: Fabrikam website rebuild"). A fresh idempotency key is made once per opening, so a double click or
 *   a retry after a flaky connection can never create two tasks.
 * - Edit: pass `task`; only changed fields are sent.
 * - Times are entered as wall-clock time in the chosen zone and sent as such; the server handles daylight saving.
 */
export function TaskDrawer({
  workspaceId,
  task,
  links = {},
  linkLabel,
  defaultTimezone,
  onClose,
  onSaved,
}: {
  workspaceId: string;
  task?: TaskOut;
  links?: TaskLinks;
  linkLabel?: string;
  defaultTimezone?: string;
  onClose: () => void;
  onSaved?: (task: TaskOut) => void;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const fallbackZone = defaultTimezone ?? browserTimeZone();
  const base = useMemo<TaskForm>(
    () => (task ? formFromTask(task, fallbackZone) : emptyTaskForm(fallbackZone)),
    [task, fallbackZone],
  );
  const [form, setForm] = useState<TaskForm>(base);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [banner, setBanner] = useState<MutationFailure | null>(null);
  const [pending, setPending] = useState(false);
  const submitting = useRef(false);
  const key = useRef<string>(newIdempotencyKey());
  const zones = useMemo(() => timeZoneOptions(form.timezone), [form.timezone]);
  const patch = task ? diffTask(base, form) : null;
  const dirty = patch ? Object.keys(patch).length > 0 : true;

  const set = <K extends keyof TaskForm>(name: K, value: TaskForm[K]) => {
    setForm((f) => ({ ...f, [name]: value }));
    setErrors((e) => {
      if (!e[name]) return e;
      const rest = { ...e };
      delete rest[name];
      return rest;
    });
  };
  const err = (name: string) => (errors[name] ? { error: errors[name] } : {});
  const apiField: Record<string, string> = {
    due_at: "due",
    remind_at: "reminder",
    due_timezone: "timezone",
  };

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (submitting.current) return; // one request at a time, however fast the clicks come
    const problems = validateTaskForm(form);
    if (Object.keys(problems).length > 0) {
      setErrors(problems);
      setBanner({
        title: "Some fields need attention",
        text: "Fix the highlighted fields and try again.",
      });
      return;
    }
    if (task && !dirty) return;
    submitting.current = true;
    setPending(true);
    setBanner(null);
    setErrors({});
    try {
      const api = browserApi();
      const path = { workspace_id: workspaceId };
      const result = task
        ? await api.PATCH("/api/v1/workspaces/{workspace_id}/tasks/{task_id}", {
            params: { path: { ...path, task_id: task.id } },
            body: patch ?? {},
          })
        : await api.POST("/api/v1/workspaces/{workspace_id}/tasks", {
            params: { path },
            body: buildTaskCreate(form, links, key.current),
          });
      if (result.data) {
        toast({
          title: task ? "Task saved" : "Task added",
          description: form.title.trim(),
          tone: "success",
        });
        onSaved?.(result.data);
        router.refresh();
        onClose();
        return;
      }
      const out = describeFailure(result.error, result.response, "task");
      if (out) {
        setBanner(out.failure);
        setErrors(
          Object.fromEntries(Object.entries(out.fields).map(([k, v]) => [apiField[k] ?? k, v])),
        );
      }
    } catch {
      setBanner({ title: "That didn't work", text: toFailure(undefined).message });
    }
    submitting.current = false;
    setPending(false);
  }

  return (
    <Drawer
      open
      onOpenChange={(open) => !open && onClose()}
      title={task ? "Edit task" : "New task"}
      description={linkLabel ? `For: ${linkLabel}` : "A follow-up or reminder."}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="task-form"
            disabled={pending || (!!task && !dirty)}
            aria-busy={pending}
          >
            {pending ? "Saving…" : task ? "Save changes" : "Add task"}
          </Button>
        </>
      }
    >
      <form id="task-form" onSubmit={submit} className="flex flex-col gap-4" aria-label="Task">
        {banner ? (
          <Notice tone={banner.reload ? "warning" : "danger"} title={banner.title}>
            {banner.text}
          </Notice>
        ) : null}
        <Field label="What needs doing?" required {...err("title")}>
          {(p) => (
            <Input
              {...p}
              value={form.title}
              maxLength={300}
              onChange={(e) => set("title", e.target.value)}
            />
          )}
        </Field>
        <Field label="Details" {...err("description")}>
          {(p) => (
            <Textarea
              {...p}
              rows={3}
              value={form.description}
              maxLength={4000}
              onChange={(e) => set("description", e.target.value)}
            />
          )}
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Due" hint="Date and time, in the time zone below." {...err("due")}>
            {(p) => (
              <Input
                {...p}
                type="datetime-local"
                value={form.due}
                onChange={(e) => set("due", e.target.value)}
              />
            )}
          </Field>
          <Field label="Priority" {...err("priority")}>
            {(p) => (
              <Select
                {...p}
                value={form.priority}
                onChange={(e) => set("priority", e.target.value as Priority)}
              >
                {PRIORITIES.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        </div>
        <Field
          label="Time zone"
          hint="The time above means this zone's clock, even across daylight-saving changes."
          {...err("timezone")}
        >
          {(p) => (
            <Select {...p} value={form.timezone} onChange={(e) => set("timezone", e.target.value)}>
              {zones.map((z) => (
                <option key={z} value={z}>
                  {z}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Reminder" {...err("reminder")}>
          {(p) => (
            <Select {...p} value={form.reminder} onChange={(e) => set("reminder", e.target.value)}>
              {REMINDERS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </form>
    </Drawer>
  );
}
