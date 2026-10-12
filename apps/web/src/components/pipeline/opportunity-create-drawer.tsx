"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { Button, Drawer, Field, Notice, Select, useToast } from "@freelancer-os/ui";
import { browserApi, toFailure } from "@/lib/api-client";
import { describeFailure, type MutationFailure } from "@/lib/mutation-error";
import {
  OpportunityFields,
  emptyOpportunityForm,
  opportunityCreateFields,
  validateOpportunityForm,
  type OpportunityForm,
} from "./opportunity-fields";
import type { PipelineStage } from "./pipeline-model";

interface LeadChoice {
  id: string;
  title: string;
  company: string | null;
}

const LEAD_LIMIT = 100;

/** A "New deal" button that opens the drawer. The drawer is mounted only while open, so it starts fresh each time. */
export function NewDealButton({
  workspaceId,
  stages,
  leadId,
  variant = "primary",
}: {
  workspaceId: string;
  stages: readonly PipelineStage[];
  leadId?: string;
  variant?: "primary" | "secondary";
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant={variant} onClick={() => setOpen(true)}>
        New deal
      </Button>
      {open ? (
        <OpportunityCreateDrawer
          workspaceId={workspaceId}
          {...(leadId ? { leadId } : {})}
          stages={stages}
          onClose={() => setOpen(false)}
        />
      ) : null}
    </>
  );
}

/**
 * Create a deal from a lead. Mount it to open it; call `onClose` to unmount. With `leadId` the lead is
 * chosen for the person and cannot be changed. The leads list is fetched when the drawer opens.
 */
export function OpportunityCreateDrawer({
  workspaceId,
  leadId,
  stages,
  onClose,
}: {
  workspaceId: string;
  leadId?: string;
  stages: readonly PipelineStage[];
  onClose: () => void;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const [leads, setLeads] = useState<LeadChoice[] | null>(null);
  const [leadTotal, setLeadTotal] = useState(0);
  const [leadsFailed, setLeadsFailed] = useState(false);
  const [lead, setLead] = useState(leadId ?? "");
  const [stage, setStage] = useState("");
  const [form, setForm] = useState<OpportunityForm>(emptyOpportunityForm());
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [banner, setBanner] = useState<MutationFailure | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let live = true;
    browserApi()
      .GET("/api/v1/workspaces/{workspace_id}/leads", {
        params: {
          path: { workspace_id: workspaceId },
          query: { limit: LEAD_LIMIT, sort: "title" },
        },
      })
      .then((r) => {
        if (!live) return;
        if (r.data) {
          setLeads(
            r.data.items.map((l) => ({
              id: l.id,
              title: l.title,
              company: l.company?.name ?? null,
            })),
          );
          setLeadTotal(r.data.total);
        } else {
          setLeadsFailed(true);
        }
      })
      .catch(() => live && setLeadsFailed(true));
    return () => {
      live = false;
    };
  }, [workspaceId]);

  const openStages = stages.filter((s) => !s.is_won && !s.is_lost);
  const err = (k: string) => (errors[k] ? { error: errors[k] } : {});
  const known = leads?.some((l) => l.id === lead) ?? false;

  async function submit(e: FormEvent) {
    e.preventDefault();
    const problems = validateOpportunityForm(form);
    if (!lead) problems.lead_id = "Choose the lead this deal is for.";
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
      const { data, error, response } = await browserApi().POST(
        "/api/v1/workspaces/{workspace_id}/opportunities",
        {
          params: { path: { workspace_id: workspaceId } },
          body: {
            lead_id: lead,
            ...(stage ? { stage_id: stage } : {}),
            ...opportunityCreateFields(form),
          },
        },
      );
      if (response.ok) {
        toast({
          title: "Deal created",
          ...(data ? { description: data.title } : {}),
          tone: "success",
        });
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
      title="New deal"
      description="A deal tracks a possible sale to one lead. Only the lead is required."
      className="w-[min(32rem,100vw-2rem)]"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
          <Button type="submit" form="deal-create" disabled={pending}>
            Create deal
          </Button>
        </>
      }
    >
      <form
        id="deal-create"
        onSubmit={submit}
        noValidate
        className="flex flex-col gap-4"
        aria-label="New deal"
      >
        {banner ? (
          <Notice tone="danger" title={banner.title}>
            {banner.text}
          </Notice>
        ) : null}
        {leadsFailed ? (
          <Notice tone="warning" title="Couldn't load your leads">
            Close this and try again in a moment.
          </Notice>
        ) : null}

        <Field
          label="Lead"
          required
          {...(leadId
            ? { hint: "This deal is created for this lead." }
            : leads && leadTotal > leads.length
              ? { hint: `Showing the first ${leads.length} of ${leadTotal} leads, A to Z.` }
              : leads && leads.length === 0
                ? { hint: "You have no leads yet. Add a lead first, then create a deal from it." }
                : {})}
          {...err("lead_id")}
        >
          {(p) => (
            <Select
              {...p}
              value={lead}
              disabled={Boolean(leadId) || leads === null}
              onChange={(ev) => setLead(ev.target.value)}
            >
              <option value="">
                {leads === null && !leadsFailed ? "Loading leads…" : "Choose a lead…"}
              </option>
              {leadId && !known ? <option value={leadId}>Selected lead</option> : null}
              {(leads ?? []).map((l) => (
                <option key={l.id} value={l.id}>
                  {l.company ? `${l.title} · ${l.company}` : l.title}
                </option>
              ))}
            </Select>
          )}
        </Field>

        <Field
          label="Stage"
          hint="Only open stages. You can mark a deal won or lost later from the board."
          {...err("stage_id")}
        >
          {(p) => (
            <Select {...p} value={stage} onChange={(ev) => setStage(ev.target.value)}>
              <option value="">Same as the lead&apos;s stage</option>
              {openStages.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
          )}
        </Field>

        <OpportunityFields
          form={form}
          setForm={setForm}
          errors={errors}
          idPrefix="deal-create"
          titleHint="Leave blank to use the lead's name."
        />
      </form>
    </Drawer>
  );
}
