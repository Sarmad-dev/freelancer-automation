"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState, type FormEvent } from "react";
import { Button, Drawer, Field, Notice, Textarea, useToast } from "@freelancer-os/ui";
import { browserApi, toFailure } from "@/lib/api-client";
import { describeFailure, type MutationFailure } from "@/lib/mutation-error";
import {
  OpportunityFields,
  diffOpportunity,
  formFromOpportunity,
  validateOpportunityForm,
  type OpportunityForm,
} from "./opportunity-fields";
import type { OpportunityOut, OpportunityPatch } from "./pipeline-model";

export const LOSS_REASON_MAX = 300;

/**
 * Edit a deal's own fields. Stage and status are not here: they change through Move / Reopen.
 * Mount it to open it; key it on `deal.updated_at` so it starts from fresh data after a refresh.
 */
export function DealEditDrawer({
  workspaceId,
  deal,
  onClose,
}: {
  workspaceId: string;
  deal: OpportunityOut;
  onClose: () => void;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const baseline = useMemo(() => formFromOpportunity(deal), [deal]);
  const [form, setForm] = useState<OpportunityForm>(baseline);
  const [reason, setReason] = useState(deal.loss_reason ?? "");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [banner, setBanner] = useState<MutationFailure | null>(null);
  const [pending, setPending] = useState(false);

  const lost = deal.status === "lost";
  const patch: OpportunityPatch = { ...diffOpportunity(baseline, form) };
  if (lost && reason.trim() !== (deal.loss_reason ?? "").trim()) {
    patch.loss_reason = reason.trim() || null;
  }
  const dirty = Object.keys(patch).length > 0;

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!dirty || pending) return;
    const problems = validateOpportunityForm(form);
    if (!form.title.trim()) problems.title = "Give the deal a name.";
    if (Object.keys(problems).length > 0) {
      setErrors(problems);
      setBanner({
        title: "Some fields need attention",
        text: "Fix the highlighted fields and try again.",
      });
      return;
    }
    setPending(true);
    setBanner(null);
    setErrors({});
    try {
      const { error, response } = await browserApi().PATCH(
        "/api/v1/workspaces/{workspace_id}/opportunities/{opportunity_id}",
        {
          params: { path: { workspace_id: workspaceId, opportunity_id: deal.id } },
          body: patch,
        },
      );
      if (response.ok) {
        toast({ title: "Saved", description: "The deal was updated.", tone: "success" });
        router.refresh();
        onClose();
        return;
      }
      const out = describeFailure(error, response, "deal");
      if (out) {
        setBanner(out.failure);
        setErrors(out.fields);
      }
    } catch {
      setBanner({ title: "That didn't work", text: toFailure(undefined).message });
    }
    setPending(false);
  }

  return (
    <Drawer
      open
      onOpenChange={(open) => !open && onClose()}
      title="Edit deal"
      description="Change the details. The stage is changed with Move on the deal page."
      className="w-[min(34rem,100vw-2rem)]"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
          <Button type="submit" form="deal-edit" disabled={pending || !dirty} aria-busy={pending}>
            {pending ? "Saving…" : "Save changes"}
          </Button>
        </>
      }
    >
      <form
        id="deal-edit"
        onSubmit={(e) => void save(e)}
        aria-label="Deal details"
        className="flex flex-col gap-4"
      >
        {banner ? (
          <Notice tone={banner.reload ? "warning" : "danger"} title={banner.title}>
            {banner.text}
          </Notice>
        ) : null}
        <OpportunityFields form={form} setForm={setForm} errors={errors} idPrefix="deal-edit" />
        {lost ? (
          <Field
            label="Reason lost"
            hint="Optional. Up to 300 characters."
            {...(errors.loss_reason ? { error: errors.loss_reason } : {})}
          >
            {(p) => (
              <Textarea
                {...p}
                rows={3}
                value={reason}
                maxLength={LOSS_REASON_MAX}
                onChange={(e) => setReason(e.target.value)}
              />
            )}
          </Field>
        ) : null}
      </form>
    </Drawer>
  );
}
