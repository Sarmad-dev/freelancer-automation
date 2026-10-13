"use client";

import { useRouter } from "next/navigation";
import { useId, useState } from "react";
import { Badge, Button, ConfirmDialog, Field, Notice, Select, useToast } from "@freelancer-os/ui";
import { browserApi, toFailure } from "@/lib/api-client";
import { describeFailure } from "@/lib/mutation-error";
import {
  CATEGORIES,
  CATEGORY_HELP,
  CATEGORY_LABEL,
  CATEGORY_TONE,
  confidenceText,
  sourceLabel,
  type ConversationDetail,
  type ReplyCategory,
} from "./inbox-model";

type Verb = "save" | "confirm" | "classify";
type Pick = ReplyCategory | "";

export function ClassificationCard({
  workspaceId,
  thread,
  canEdit,
}: {
  workspaceId: string;
  thread: ConversationDetail;
  canEdit: boolean;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const headingId = useId();
  const c = thread.classification;
  const server: Pick = c.category ?? "";

  // The picker follows the server until the person chooses something; a new server value resets it.
  const [picked, setPicked] = useState<Pick | null>(null);
  const [seen, setSeen] = useState<Pick>(server);
  if (seen !== server) {
    setSeen(server);
    setPicked(null);
  }
  const category: Pick = picked ?? server;

  const [busy, setBusy] = useState<Verb | null>(null);
  const [confirmingStop, setConfirmingStop] = useState<Verb | null>(null);

  const hasInbound = thread.messages.some((m) => m.direction === "inbound");
  const path = { workspace_id: workspaceId, conversation_id: thread.id };

  async function run(verb: Verb, failTitle: string, call: () => Promise<Response | null>) {
    if (busy) return;
    setBusy(verb);
    try {
      const response = await call();
      if (response?.ok) router.refresh();
    } catch {
      toast({ title: failTitle, description: toFailure(undefined).message, tone: "danger" });
    } finally {
      setBusy(null);
    }
  }

  const setCategory = (verb: "save" | "confirm", value: ReplyCategory) =>
    run(verb, "Couldn't save the category", async () => {
      const { error, response } = await browserApi().PUT(
        "/api/v1/workspaces/{workspace_id}/inbox/conversations/{conversation_id}/classification",
        { params: { path }, body: { category: value } },
      );
      if (response.ok) {
        toast({
          title: verb === "confirm" ? "Category confirmed" : "Category saved",
          description:
            value === "unsubscribe"
              ? `${CATEGORY_LABEL[value]}. ${thread.counterpart.address} is on your do-not-contact list.`
              : `Marked as ${CATEGORY_LABEL[value]}.`,
          tone: "success",
        });
      } else {
        const out = describeFailure(error, response, "classification");
        if (out) {
          toast({
            title: "Couldn't save the category",
            description: out.failure.text,
            tone: "danger",
          });
        }
      }
      return response;
    });

  const classifyAgain = () =>
    run("classify", "Couldn't start the classification", async () => {
      const { error, response } = await browserApi().POST(
        "/api/v1/workspaces/{workspace_id}/inbox/conversations/{conversation_id}/classify",
        { params: { path } },
      );
      if (response.ok) {
        toast({
          title: "Classification started",
          description: "It can take a moment. Check again shortly.",
          tone: "success",
        });
      } else {
        const out = describeFailure(error, response, "classification");
        if (out) {
          toast({
            title: "Couldn't start the classification",
            description: out.failure.text,
            tone: "danger",
          });
        }
      }
      return response;
    });

  /** Unsubscribe adds the sender to the do-not-contact list, so it always asks first. */
  function submit(verb: "save" | "confirm") {
    if (!category) return;
    if (category === "unsubscribe") setConfirmingStop(verb);
    else void setCategory(verb, category);
  }

  const needsReview = c.status === "classified" && c.needs_review;
  const showControls =
    c.status === "failed" || c.status === "classified" || (c.status === "none" && hasInbound);

  const controls = !showControls ? null : canEdit ? (
    <div className="flex flex-col gap-3">
      <Field
        label="Category"
        hint={category ? CATEGORY_HELP[category] : "Choose the category that fits this reply."}
        className="max-w-sm"
      >
        {(props) => (
          <Select
            {...props}
            value={category}
            onChange={(e) => setPicked(e.target.value as Pick)}
            disabled={busy !== null}
          >
            {category === "" ? (
              <option value="" disabled>
                Choose a category
              </option>
            ) : null}
            {CATEGORIES.map((value) => (
              <option key={value} value={value}>
                {CATEGORY_LABEL[value]}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <div className="flex flex-wrap gap-2">
        {needsReview && category ? (
          <Button onClick={() => submit("confirm")} disabled={busy !== null}>
            {busy === "confirm" ? "Confirming…" : `Confirm “${CATEGORY_LABEL[category]}”`}
          </Button>
        ) : null}
        <Button
          variant="secondary"
          onClick={() => submit("save")}
          disabled={
            busy !== null || category === "" || (c.status === "classified" && category === server)
          }
        >
          {busy === "save" ? "Saving…" : "Save category"}
        </Button>
        <Button variant="secondary" onClick={() => void classifyAgain()} disabled={busy !== null}>
          {busy === "classify" ? "Starting…" : "Classify again"}
        </Button>
      </div>
    </div>
  ) : (
    <p className="text-[13px] text-muted">Only the workspace owner can change this.</p>
  );

  return (
    <section
      aria-labelledby={headingId}
      className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4"
    >
      <h3 id={headingId} className="text-sm font-semibold text-fg">
        Classification
      </h3>

      {c.status === "none" && !hasInbound ? (
        <p className="text-sm text-muted">Nothing to classify yet.</p>
      ) : null}
      {c.status === "none" && hasInbound ? (
        <p className="text-sm text-muted">This reply hasn&apos;t been classified yet.</p>
      ) : null}

      {c.status === "pending" ? (
        <div role="status" className="flex flex-wrap items-center gap-3">
          <p className="text-sm text-muted">Classifying this reply…</p>
          <Button variant="secondary" size="sm" onClick={() => router.refresh()}>
            Check again
          </Button>
        </div>
      ) : null}

      {c.status === "failed" ? (
        <Notice tone="danger" title="Couldn't classify this automatically">
          {c.review_text ?? "Pick the category yourself, or try again."}
        </Notice>
      ) : null}

      {c.status === "classified" ? (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            {c.category ? (
              <Badge tone={CATEGORY_TONE[c.category]}>{CATEGORY_LABEL[c.category]}</Badge>
            ) : null}
            {confidenceText(c.confidence) ? (
              <span className="text-[13px] text-fg">{confidenceText(c.confidence)}</span>
            ) : null}
            {sourceLabel(c.source) ? (
              <span className="text-[13px] text-muted">{sourceLabel(c.source)}</span>
            ) : null}
          </div>
          {c.explanation ? <p className="text-sm text-fg">{c.explanation}</p> : null}
          {c.evidence.length > 0 ? (
            <div className="flex flex-col gap-1">
              <h4 className="text-[13px] font-medium text-fg">From the message</h4>
              <ul className="flex flex-col gap-2">
                {c.evidence.map((quote, i) => (
                  <li key={`${i}-${quote}`}>
                    <blockquote className="break-words border-l-2 border-line pl-3 text-[13px] text-muted">
                      {quote}
                    </blockquote>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {needsReview ? (
            <Notice tone="warning" title="Needs your review">
              {c.review_text ?? "Please check that this category is right."}
            </Notice>
          ) : null}
        </div>
      ) : null}

      {controls}

      <ConfirmDialog
        open={confirmingStop !== null}
        onOpenChange={(open) => !open && setConfirmingStop(null)}
        title={`Add ${thread.counterpart.address} to your do-not-contact list?`}
        description="Nothing will be sent to this address while it is on the list. You can remove it from the list later."
        confirmLabel="Add to do-not-contact list"
        destructive
        onConfirm={() => {
          if (confirmingStop)
            void setCategory(confirmingStop === "confirm" ? "confirm" : "save", "unsubscribe");
        }}
      />
    </section>
  );
}
