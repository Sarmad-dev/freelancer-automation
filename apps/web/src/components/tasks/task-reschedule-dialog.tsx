"use client";

import { useMemo, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Button, Field, Input, Modal, Notice, Select, useToast } from "@freelancer-os/ui";
import { browserApi, toFailure } from "@/lib/api-client";
import { describeFailure, type MutationFailure } from "@/lib/mutation-error";
import {
  DATE_PRESETS,
  SNOOZE_CHOICES,
  buildSnooze,
  presetDue,
  type SnoozeChoice,
} from "./task-list-model";
import { timeZoneOptions, toLocalInput, type TaskOut } from "./task-model";

type Busy = "reschedule" | "snooze" | null;

/**
 * Move a task's due time, or push its reminder back. Mount it to open it; it asks to be closed through `onClose`.
 * Times are entered as wall-clock time in the chosen zone and sent as such: the server resolves daylight saving
 * and tells us when a local time does not exist.
 */
export function TaskRescheduleDialog({
  workspaceId,
  task,
  now,
  defaultTimezone,
  onClose,
}: {
  workspaceId: string;
  task: TaskOut;
  /** Server time (ISO). The presets are worked out from this, never from the browser clock. */
  now: string;
  defaultTimezone: string;
  onClose: () => void;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const initialZone = task.due_timezone ?? defaultTimezone;
  const [zone, setZone] = useState(initialZone);
  const [due, setDue] = useState(toLocalInput(task.due_at, initialZone));
  const [choice, setChoice] = useState<SnoozeChoice>("hour");
  const [custom, setCustom] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [banner, setBanner] = useState<MutationFailure | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const sending = useRef(false);
  const zones = useMemo(() => timeZoneOptions(zone), [zone]);
  const canSnooze = task.status === "open" && Boolean(task.due_at);

  async function send(
    kind: Exclude<Busy, null>,
    run: () => Promise<{ error?: unknown; response: Response }>,
  ) {
    if (sending.current) return; // one request at a time, however fast the clicks come
    sending.current = true;
    setBusy(kind);
    setBanner(null);
    setErrors({});
    try {
      const { error, response } = await run();
      if (response.ok) {
        toast({
          title: kind === "snooze" ? "Reminder moved" : "Task rescheduled",
          description: task.title,
          tone: "success",
        });
        router.refresh();
        onClose();
        return;
      }
      const out = describeFailure(error, response, "task");
      if (out) {
        setBanner(out.failure);
        setErrors(out.fields);
      }
    } catch {
      setBanner({ title: "That didn't work", text: toFailure(undefined).message });
    }
    sending.current = false;
    setBusy(null);
  }

  const path = { workspace_id: workspaceId, task_id: task.id };

  function reschedule(e: FormEvent) {
    e.preventDefault();
    if (!due) {
      setErrors({ due_at: "Choose a new date and time." });
      return;
    }
    void send("reschedule", () =>
      browserApi().POST("/api/v1/workspaces/{workspace_id}/tasks/{task_id}/reschedule", {
        params: { path },
        body: { due_at: due, due_timezone: zone },
      }),
    );
  }

  function snooze(e: FormEvent) {
    e.preventDefault();
    const built = buildSnooze(choice, custom, now, zone);
    if ("error" in built) {
      setErrors({ remind_at: built.error });
      return;
    }
    void send("snooze", () =>
      browserApi().POST("/api/v1/workspaces/{workspace_id}/tasks/{task_id}/snooze", {
        params: { path },
        body: built.body,
      }),
    );
  }

  const err = (name: string) => (errors[name] ? { error: errors[name] } : {});
  const disabled = busy !== null;

  return (
    <Modal
      open
      onOpenChange={(open) => !open && onClose()}
      title="Reschedule task"
      description={task.title}
      className="max-h-[90vh] max-w-lg overflow-y-auto"
    >
      <div className="flex flex-col gap-6">
        {banner ? (
          <Notice tone={banner.reload ? "warning" : "danger"} title={banner.title}>
            {banner.text}
          </Notice>
        ) : null}

        <form
          onSubmit={reschedule}
          noValidate
          aria-label="Reschedule"
          className="flex flex-col gap-4"
        >
          <h3 className="text-sm font-semibold text-fg">New due time</h3>
          {task.status !== "open" ? (
            <p className="text-[13px] text-muted">Rescheduling a finished task reopens it.</p>
          ) : null}
          <div role="group" aria-label="Quick dates" className="flex flex-wrap gap-2">
            {DATE_PRESETS.map((p) => (
              <Button
                key={p.value}
                variant="secondary"
                size="sm"
                disabled={disabled}
                onClick={() => {
                  setDue(presetDue(p.value, now, zone));
                  setErrors((prev) => ({ ...prev, due_at: "" }));
                }}
              >
                {p.label}
              </Button>
            ))}
          </div>
          <Field label="New due date and time" {...err("due_at")}>
            {(p) => (
              <Input
                {...p}
                type="datetime-local"
                value={due}
                disabled={disabled}
                onChange={(e) => setDue(e.target.value)}
              />
            )}
          </Field>
          <Field
            label="Time zone"
            hint="The time above means this zone's clock, even across daylight-saving changes."
            {...err("due_timezone")}
          >
            {(p) => (
              <Select
                {...p}
                value={zone}
                disabled={disabled}
                onChange={(e) => setZone(e.target.value)}
              >
                {zones.map((z) => (
                  <option key={z} value={z}>
                    {z}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <div className="flex justify-end">
            <Button type="submit" disabled={disabled} aria-busy={busy === "reschedule"}>
              {busy === "reschedule" ? "Saving…" : "Reschedule"}
            </Button>
          </div>
        </form>

        {canSnooze ? (
          <form
            onSubmit={snooze}
            noValidate
            aria-label="Snooze"
            className="flex flex-col gap-4 border-t border-line pt-5"
          >
            <h3 className="text-sm font-semibold text-fg">Snooze reminder</h3>
            <p className="text-[13px] text-muted">
              Keeps the due time and moves only the reminder. Clock times use {zone}.
            </p>
            <Field label="Remind me" {...(choice !== "custom" ? err("remind_at") : {})}>
              {(p) => (
                <Select
                  {...p}
                  value={choice}
                  disabled={disabled}
                  onChange={(e) => {
                    setChoice(e.target.value as SnoozeChoice);
                    setErrors({});
                  }}
                >
                  {SNOOZE_CHOICES.map((c) => (
                    <option key={c.value} value={c.value}>
                      {c.label}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            {choice === "custom" ? (
              <Field label="Reminder time" {...err("remind_at")}>
                {(p) => (
                  <Input
                    {...p}
                    type="datetime-local"
                    value={custom}
                    disabled={disabled}
                    onChange={(e) => setCustom(e.target.value)}
                  />
                )}
              </Field>
            ) : null}
            <div className="flex justify-end">
              <Button
                type="submit"
                variant="secondary"
                disabled={disabled}
                aria-busy={busy === "snooze"}
              >
                {busy === "snooze" ? "Saving…" : "Snooze reminder"}
              </Button>
            </div>
          </form>
        ) : null}
      </div>
    </Modal>
  );
}
