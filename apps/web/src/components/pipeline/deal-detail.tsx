"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import {
  Badge,
  Button,
  ConfirmDialog,
  Field,
  Modal,
  Notice,
  PageHeader,
  Select,
  Textarea,
  useToast,
} from "@freelancer-os/ui";
import { SampleBadge } from "@/components/leads/lead-badges";
import { formatDateTime, type ActivityOut } from "@/components/leads/lead-model";
import { browserApi, toFailure } from "@/lib/api-client";
import { describeFailure, type MutationFailure } from "@/lib/mutation-error";
import { formatDate } from "@/lib/safe-url";
import { DealEditDrawer, LOSS_REASON_MAX } from "./deal-edit-drawer";
import { DealTasks, type TaskPage } from "./deal-tasks";
import { DealTimeline } from "./deal-timeline";
import {
  DEAL_STATUS_LABEL,
  dealStatusTone,
  formatMoney,
  isCloseOverdue,
  stageTone,
  type OpportunityOut,
  type PipelineStage,
} from "./pipeline-model";

const card = "rounded-lg border border-line bg-surface p-5";

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 break-words text-fg">{children}</dd>
    </>
  );
}

function NotSet({ children = "Not set" }: { children?: string }) {
  return <span className="text-muted">{children}</span>;
}

type Failure = MutationFailure;

export function DealDetail({
  workspaceId,
  deal: initialDeal,
  stages: allStages,
  activities,
  openTasks,
  doneTasks,
  canEdit,
  today,
}: {
  workspaceId: string;
  deal: OpportunityOut;
  stages: PipelineStage[];
  activities: { items: ActivityOut[]; total: number };
  openTasks: TaskPage;
  doneTasks: TaskPage;
  canEdit: boolean;
  /** `YYYY-MM-DD` from the server, so "overdue" is computed the same on server and client. */
  today: string;
}) {
  const router = useRouter();
  const { toast } = useToast();

  // Render from what the last mutation returned; take the server's data again once it refreshes.
  const [deal, setDeal] = useState(initialDeal);
  const [target, setTarget] = useState(initialDeal.stage.id);
  const [seen, setSeen] = useState(initialDeal);
  if (initialDeal !== seen) {
    setSeen(initialDeal);
    setDeal(initialDeal);
    setTarget(initialDeal.stage.id);
  }

  const stages = [...allStages].sort((a, b) => a.position - b.position);
  const openStages = stages.filter((s) => !s.is_won && !s.is_lost);

  const [busy, setBusy] = useState<"move" | "reopen" | null>(null);
  const [banner, setBanner] = useState<(Failure & { tone?: "warning" }) | null>(null);
  const [editing, setEditing] = useState(false);
  const [confirmWon, setConfirmWon] = useState<PipelineStage | null>(null);
  const [lostStage, setLostStage] = useState<PipelineStage | null>(null);
  const [lostReason, setLostReason] = useState("");
  const [reopening, setReopening] = useState(false);
  const [reopenStage, setReopenStage] = useState("");

  const closed = deal.status !== "open";
  const overdue = isCloseOverdue(deal, today);
  const path = { workspace_id: workspaceId, opportunity_id: deal.id };

  /** Never optimistic: wait for the server, then show exactly what it answered. */
  async function run(
    key: "move" | "reopen",
    call: () => Promise<{ data?: OpportunityOut; error?: unknown; response: Response }>,
    done: { title: string; description?: string },
  ): Promise<boolean> {
    if (busy) return false;
    setBusy(key);
    setBanner(null);
    let ok = false;
    try {
      const { data, error, response } = await call();
      if (response.ok && data) {
        setDeal(data);
        setTarget(data.stage.id);
        toast({ ...done, tone: "success" });
        router.refresh();
        ok = true;
      } else {
        const out = describeFailure(error, response, "deal");
        if (out) {
          const code = toFailure(error, response).code;
          if (code === "stale_stage") {
            setBanner({
              title: "This deal was moved elsewhere",
              text: "Its stage changed since you opened this page. We've reloaded it. Check the stage and try again.",
              tone: "warning",
            });
            router.refresh();
          } else if (code === "opportunity_closed") {
            setBanner({
              title: "This deal is already closed",
              text: out.failure.text,
              tone: "warning",
            });
            router.refresh();
          } else {
            setBanner(out.failure);
          }
        }
      }
    } catch {
      setBanner({ title: "That didn't work", text: toFailure(undefined).message });
    }
    if (!ok) setTarget(deal.stage.id);
    setBusy(null);
    return ok;
  }

  function move(stage: PipelineStage, lossReason?: string) {
    return run(
      "move",
      () =>
        browserApi().POST("/api/v1/workspaces/{workspace_id}/opportunities/{opportunity_id}/move", {
          params: { path },
          body: {
            stage_id: stage.id,
            expected_stage_id: deal.stage.id,
            ...(lossReason ? { loss_reason: lossReason } : {}),
          },
        }),
      {
        title: stage.is_won ? "Deal won" : stage.is_lost ? "Deal marked as lost" : "Deal moved",
        description: `Now in ${stage.name}.`,
      },
    );
  }

  function reopen(stageId: string) {
    const name = stages.find((s) => s.id === stageId)?.name ?? "an open stage";
    return run(
      "reopen",
      () =>
        browserApi().POST(
          "/api/v1/workspaces/{workspace_id}/opportunities/{opportunity_id}/reopen",
          { params: { path }, body: { stage_id: stageId } },
        ),
      { title: "Deal reopened", description: `Back in ${name}.` },
    );
  }

  function startMove() {
    const stage = stages.find((s) => s.id === target);
    if (!stage || stage.id === deal.stage.id) return;
    if (stage.is_won) setConfirmWon(stage);
    else if (stage.is_lost) {
      setLostReason("");
      setLostStage(stage);
    } else void move(stage);
  }

  async function submitLost() {
    const stage = lostStage;
    if (!stage) return;
    setLostStage(null);
    await move(stage, lostReason.trim());
  }

  const weighted =
    deal.weighted_value !== null ? formatMoney(deal.weighted_value, deal.currency) : null;
  const closedOn = deal.closed_at ? formatDate(deal.closed_at) : null;

  return (
    <div className="flex flex-col gap-6">
      <Link
        href="/pipeline"
        className="inline-flex w-fit items-center gap-1.5 text-sm text-muted underline-offset-4 hover:text-fg hover:underline"
      >
        <ArrowLeft className="size-4" aria-hidden />
        Back to pipeline
      </Link>

      <PageHeader
        title={deal.title}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone={stageTone(deal.stage)}>Stage: {deal.stage.name}</Badge>
            <Badge tone={dealStatusTone(deal.status)}>
              {DEAL_STATUS_LABEL[deal.status] ?? deal.status}
            </Badge>
            {deal.is_sample ? <SampleBadge /> : null}
          </span>
        }
        actions={
          canEdit ? (
            <Button variant="secondary" onClick={() => setEditing(true)} disabled={busy !== null}>
              Edit
            </Button>
          ) : undefined
        }
      />

      {closed ? (
        <Notice
          tone={deal.status === "won" ? "success" : "warning"}
          title={`This deal is ${deal.status}${closedOn ? ` on ${closedOn}` : ""}`}
        >
          {deal.status === "lost"
            ? deal.loss_reason
              ? `Reason: ${deal.loss_reason}`
              : "No reason was recorded."
            : "It no longer counts in your weighted pipeline."}
        </Notice>
      ) : null}
      {!canEdit ? (
        <Notice tone="info" title="View only">
          Only the workspace owner can change deals.
        </Notice>
      ) : null}
      {banner ? (
        <Notice tone={banner.tone ?? "danger"} title={banner.title}>
          {banner.text}
        </Notice>
      ) : null}

      <div className={canEdit ? "grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]" : ""}>
        <div className="flex min-w-0 flex-col gap-6">
          <section aria-labelledby="deal-summary-h" className={card}>
            <h2 id="deal-summary-h" className="text-base font-semibold text-fg">
              Summary
            </h2>
            <dl className="mt-4 grid grid-cols-[auto_minmax(0,1fr)] gap-x-6 gap-y-2 text-sm">
              <Row label="Value">
                {deal.value_amount !== null ? (
                  formatMoney(deal.value_amount, deal.currency)
                ) : (
                  <NotSet>No value yet</NotSet>
                )}
              </Row>
              <Row label="Chance of winning">
                {deal.probability !== null ? (
                  `${deal.probability}%`
                ) : (
                  <NotSet>Not estimated</NotSet>
                )}
              </Row>
              <Row label="Weighted value">
                {weighted ? (
                  weighted
                ) : (
                  <NotSet>
                    {closed
                      ? "Only open deals have a weighted value"
                      : "Add a value and a chance of winning to see a weighted value"}
                  </NotSet>
                )}
              </Row>
              <Row label="Expected close">
                {deal.expected_close_date ? (
                  <span className="flex flex-wrap items-center gap-2">
                    <time dateTime={deal.expected_close_date}>{deal.expected_close_date}</time>
                    {overdue ? <Badge tone="danger">Overdue</Badge> : null}
                  </span>
                ) : (
                  <NotSet />
                )}
              </Row>
              <Row label="Next action">{deal.next_action ?? <NotSet />}</Row>
              <Row label="Source lead">
                <Link href={`/leads/${deal.lead.id}`} className="underline underline-offset-4">
                  {deal.lead.title}
                </Link>
                {deal.lead.company_name ? (
                  <span className="text-muted"> · {deal.lead.company_name}</span>
                ) : null}
              </Row>
              <Row label="Created">
                <time dateTime={deal.created_at}>{formatDateTime(deal.created_at)}</time>
              </Row>
              <Row label="Updated">
                <time dateTime={deal.updated_at}>{formatDateTime(deal.updated_at)}</time>
              </Row>
            </dl>
          </section>

          <DealTasks
            workspaceId={workspaceId}
            deal={{ id: deal.id, title: deal.title }}
            open={openTasks}
            done={doneTasks}
            canEdit={canEdit}
          />

          <DealTimeline
            workspaceId={workspaceId}
            dealId={deal.id}
            activities={activities.items}
            total={activities.total}
            stages={stages}
            canLog={canEdit}
            isOwner={canEdit}
          />
        </div>

        {canEdit ? (
          <div className="flex min-w-0 flex-col gap-6">
            <section aria-labelledby="deal-move-h" className={card}>
              <h2 id="deal-move-h" className="text-base font-semibold text-fg">
                {closed ? "Reopen this deal" : "Move this deal"}
              </h2>
              {closed ? (
                <div className="mt-4 flex flex-col gap-3">
                  <p className="text-sm text-muted">
                    This deal is closed. Reopen it into an open stage to work on it again.
                  </p>
                  <div>
                    <Button
                      variant="secondary"
                      disabled={busy !== null || openStages.length === 0}
                      aria-busy={busy === "reopen"}
                      onClick={() => {
                        setReopenStage(openStages[0]?.id ?? "");
                        setReopening(true);
                      }}
                    >
                      {busy === "reopen" ? "Reopening…" : "Reopen"}
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="mt-4 flex flex-col gap-3" aria-busy={busy === "move"}>
                  <Field label="Stage">
                    {(p) => (
                      <Select
                        {...p}
                        value={target}
                        disabled={busy !== null}
                        onChange={(e) => setTarget(e.target.value)}
                      >
                        {stages.map((s) => (
                          <option key={s.id} value={s.id}>
                            {s.name}
                          </option>
                        ))}
                      </Select>
                    )}
                  </Field>
                  <div>
                    <Button
                      onClick={startMove}
                      disabled={busy !== null || target === deal.stage.id}
                      aria-busy={busy === "move"}
                    >
                      {busy === "move" ? "Moving…" : "Move"}
                    </Button>
                  </div>
                  <p className="text-[13px] text-muted">
                    Every move is logged in the activity. Won and lost close the deal.
                  </p>
                </div>
              )}
            </section>
          </div>
        ) : null}
      </div>

      {editing && canEdit ? (
        <DealEditDrawer
          key={deal.updated_at}
          workspaceId={workspaceId}
          deal={deal}
          onClose={() => setEditing(false)}
        />
      ) : null}

      <ConfirmDialog
        open={confirmWon !== null}
        onOpenChange={(o) => !o && setConfirmWon(null)}
        title="Mark as won?"
        description="The deal closes as won and leaves your weighted pipeline. You can reopen it later."
        confirmLabel="Mark as won"
        onConfirm={() => {
          if (confirmWon) void move(confirmWon);
        }}
      />

      <Modal
        open={lostStage !== null}
        onOpenChange={(o) => !o && setLostStage(null)}
        title="Mark as lost?"
        description="The deal closes as lost and leaves your weighted pipeline. You can reopen it later."
        footer={
          <>
            <Button variant="secondary" onClick={() => setLostStage(null)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={() => void submitLost()}>
              Mark as lost
            </Button>
          </>
        }
      >
        <Field label="Why was it lost?" hint="Optional. Up to 300 characters.">
          {(p) => (
            <Textarea
              {...p}
              rows={3}
              value={lostReason}
              maxLength={LOSS_REASON_MAX}
              onChange={(e) => setLostReason(e.target.value)}
            />
          )}
        </Field>
      </Modal>

      <Modal
        open={reopening}
        onOpenChange={setReopening}
        title="Reopen this deal?"
        description="Choose the open stage it goes back into."
        footer={
          <>
            <Button variant="secondary" onClick={() => setReopening(false)}>
              Cancel
            </Button>
            <Button
              disabled={!reopenStage}
              onClick={() => {
                setReopening(false);
                void reopen(reopenStage);
              }}
            >
              Reopen deal
            </Button>
          </>
        }
      >
        <Field label="Open stage">
          {(p) => (
            <Select {...p} value={reopenStage} onChange={(e) => setReopenStage(e.target.value)}>
              {openStages.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </Modal>
    </div>
  );
}
