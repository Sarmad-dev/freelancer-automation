"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import {
  Badge,
  Button,
  ConfirmDialog,
  Field,
  Input,
  Notice,
  Textarea,
  useToast,
} from "@freelancer-os/ui";
import { formatDateTime } from "@/components/leads/lead-model";
import { browserApi, toFailure, type ApiFailure } from "@/lib/api-client";
import { describeFailure } from "@/lib/mutation-error";
import type { ConversationDetail, DraftOut } from "./inbox-model";
import {
  BODY_MAX,
  KNOWLEDGE_HREF,
  authorBadge,
  canSend,
  hasInbound,
  isDirty,
  isLocked,
  newIdempotencyKey,
  openDraft,
  replySubject,
  sendProblem,
  sendResult,
  statusBadge,
  suggestProblem,
  warningTexts,
  type SendProblem,
} from "./reply-model";
import { SendDialog } from "./send-dialog";

type Busy = "suggest" | "create" | "save" | "approve" | "discard" | "send" | "resolve";

interface Problem {
  title: string;
  text: string;
  addFacts?: boolean;
}

interface Suggestion {
  label: string;
  warnings: string[];
}

const BASE = "/api/v1/workspaces/{workspace_id}";
const DRAFTS = `${BASE}/drafts` as const;
const DRAFT = `${BASE}/drafts/{draft_id}` as const;
const APPROVE = `${BASE}/drafts/{draft_id}/approve` as const;
const DISCARD = `${BASE}/drafts/{draft_id}/discard` as const;
const SEND = `${BASE}/drafts/{draft_id}/send` as const;
const RESOLVE = `${BASE}/drafts/{draft_id}/resolve-send` as const;
const SUGGEST = `${BASE}/inbox/conversations/{conversation_id}/suggest-reply` as const;

const linkClass = "text-accent underline underline-offset-2";

export function ReplyEditor({
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
  const ids = useId();
  const headingId = `${ids}-heading`;
  const factsId = `${ids}-facts`;
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const busyRef = useRef(false);
  const returnFocusTo = useRef<HTMLElement | null>(null);

  const [draft, setDraft] = useState<DraftOut | null>(() => openDraft(thread.draft));
  const [seen, setSeen] = useState(thread.draft);
  const [subject, setSubject] = useState(() => openDraft(thread.draft)?.subject ?? "");
  const [body, setBody] = useState(() => openDraft(thread.draft)?.body_text ?? "");
  const [suggestion, setSuggestion] = useState<Suggestion | null>(null);
  const [busy, setBusy] = useState<Busy | null>(null);
  const [status, setStatus] = useState("");
  const [problem, setProblem] = useState<Problem | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [confirming, setConfirming] = useState<"regenerate" | "discard" | null>(null);
  const [sendOpen, setSendOpen] = useState(false);
  const [sendKey, setSendKey] = useState("");
  const [sendIssue, setSendIssue] = useState<SendProblem | null>(null);
  const [focusBody, setFocusBody] = useState(false);

  // The page's copy is the source of truth: when it changes, follow it. Text the person is typing is
  // only replaced when the draft itself is a different one or a newer version.
  if (thread.draft !== seen) {
    setSeen(thread.draft);
    const next = openDraft(thread.draft);
    if (next?.id !== draft?.id) setSuggestion(null);
    if (next?.id !== draft?.id || next?.version !== draft?.version) {
      setSubject(next?.subject ?? "");
      setBody(next?.body_text ?? "");
    }
    setDraft(next);
  }

  useEffect(() => {
    if (focusBody) {
      bodyRef.current?.focus();
      setFocusBody(false);
    }
  }, [focusBody]);

  // The shared dialog hands focus back to whatever had it when it opened, but its own autofocused Cancel
  // button has already taken it by then. So the editor puts focus back on the Send button itself.
  useEffect(() => {
    if (sendOpen) return;
    const el = returnFocusTo.current;
    returnFocusTo.current = null;
    if (!el) return;
    const t = setTimeout(() => {
      if (el.isConnected) el.focus();
    }, 0);
    return () => clearTimeout(t);
  }, [sendOpen]);

  const path = { workspace_id: workspaceId };

  function adopt(next: DraftOut) {
    setDraft(next);
    setSubject(next.subject);
    setBody(next.body_text);
  }

  /** One request at a time; every outcome is announced. */
  async function run(kind: Busy, work: () => Promise<void>) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(kind);
    setProblem(null);
    setFieldErrors({});
    try {
      await work();
    } finally {
      busyRef.current = false;
      setBusy(null);
    }
  }

  /** A failed call as the person should hear it, or null when they are already being sent to sign in. */
  function explain(result: { error?: unknown; response: Response } | null) {
    const out = describeFailure(result?.error, result?.response, "draft");
    if (!out) return null;
    return { f: toFailure(result?.error, result?.response), fields: out.fields };
  }

  function fail(
    result: { error?: unknown; response: Response } | null,
    title: string,
    statusText: string,
    extra: (f: ApiFailure) => { addFacts?: boolean; refresh?: boolean } = () => ({}),
  ) {
    const e = explain(result);
    if (!e) return;
    const { f, fields } = e;
    const more = extra(f);
    const known = {
      subject: fields.subject,
      body_text: fields.body_text ?? fields.body,
      to_address: fields.to_address,
    };
    const listed = Object.values(known).some(Boolean);
    setFieldErrors(known as Record<string, string>);
    const text = listed
      ? "Fix the highlighted fields and try again."
      : Object.keys(fields).length > 0
        ? Object.values(fields).join(" ")
        : f.message;
    setProblem({ title, text, ...(more.addFacts ? { addFacts: true } : {}) });
    setStatus(statusText);
    if (more.refresh || f.status === 404 || f.status === 409) router.refresh();
  }

  const done = (title: string, description: string, statusText: string) => {
    toast({ title, description, tone: "success" });
    setStatus(statusText);
    router.refresh();
  };

  /* ---------------------------------------------------------------- requests */

  const suggest = () =>
    run("suggest", async () => {
      setStatus("Writing a draft…");
      const r = await browserApi()
        .POST(SUGGEST, { params: { path: { ...path, conversation_id: thread.id } } })
        .catch(() => null);
      if (r?.data) {
        adopt(r.data.draft);
        setSuggestion({ label: r.data.ai_label, warnings: r.data.warnings });
        done(
          r.data.regenerated ? "Draft replaced" : "Draft ready",
          "Read every line before you approve it. Nothing has been sent.",
          r.data.regenerated
            ? "A new draft replaced the earlier one. Read it before you approve it."
            : "A draft is ready below. Read it before you approve it.",
        );
        return;
      }
      fail(r, "No draft was written", "Couldn't write a draft.", suggestProblem);
    });

  const create = () =>
    run("create", async () => {
      setStatus("Starting your draft…");
      const r = await browserApi()
        .POST(DRAFTS, {
          params: { path },
          body: {
            conversation_id: thread.id,
            lead_id: thread.lead?.id ?? null,
            email_account_id: thread.account_id,
            to_address: thread.counterpart.address,
            subject: replySubject(thread.subject),
            body_text: "",
          },
        })
        .catch(() => null);
      if (r?.data) {
        adopt(r.data);
        setSuggestion(null);
        setFocusBody(true);
        done(
          "Draft started",
          "Write your message, then approve it.",
          "Your draft is ready to write.",
        );
        return;
      }
      fail(r, "The draft wasn't started", "Couldn't start a draft.");
    });

  /** Save the text as it is on screen. Returns the saved draft, or null (the problem is already shown). */
  async function patch(current: DraftOut): Promise<DraftOut | null> {
    const r = await browserApi()
      .PATCH(DRAFT, {
        params: { path: { ...path, draft_id: current.id } },
        body: { subject, body_text: body },
      })
      .catch(() => null);
    if (r?.data) {
      adopt(r.data);
      return r.data;
    }
    fail(r, "The draft wasn't saved", "Couldn't save the draft.");
    return null;
  }

  const save = (current: DraftOut) =>
    run("save", async () => {
      setStatus("Saving the draft…");
      if (await patch(current)) {
        done("Draft saved", "Your changes are saved.", "Draft saved.");
      }
    });

  const approve = (current: DraftOut, saveFirst: boolean) =>
    run("approve", async () => {
      let target = current;
      if (saveFirst) {
        setStatus("Saving the draft…");
        const saved = await patch(current);
        if (!saved) return;
        target = saved;
      }
      setStatus("Approving the draft…");
      const r = await browserApi()
        .POST(APPROVE, { params: { path: { ...path, draft_id: target.id } } })
        .catch(() => null);
      if (r?.data) {
        adopt(r.data);
        done(
          "Draft approved",
          "You can send it when you're ready.",
          "Draft approved. You can send it now.",
        );
        return;
      }
      fail(
        r,
        "The draft wasn't approved",
        saveFirst ? "Saved, but couldn't approve the draft." : "Couldn't approve the draft.",
      );
    });

  const discard = (current: DraftOut) =>
    run("discard", async () => {
      setStatus("Discarding the draft…");
      const r = await browserApi()
        .POST(DISCARD, { params: { path: { ...path, draft_id: current.id } } })
        .catch(() => null);
      if (r?.response.ok) {
        setDraft(null);
        setSuggestion(null);
        setSubject("");
        setBody("");
        done("Draft discarded", "Nothing was sent.", "Draft discarded.");
        return;
      }
      fail(r, "The draft wasn't discarded", "Couldn't discard the draft.");
    });

  const resolve = (current: DraftOut, outcome: "sent" | "not_sent") =>
    run("resolve", async () => {
      setStatus("Recording what happened…");
      const r = await browserApi()
        .POST(RESOLVE, {
          params: { path: { ...path, draft_id: current.id } },
          body: { outcome },
        })
        .catch(() => null);
      if (r?.data) {
        adopt(r.data);
        done(
          outcome === "sent" ? "Marked as sent" : "Marked as not sent",
          outcome === "sent"
            ? "We recorded that this message went out."
            : "You can send it again when you're ready.",
          outcome === "sent" ? "Recorded as sent." : "Recorded as not sent. You can send it again.",
        );
        return;
      }
      fail(r, "We couldn't record that", "Couldn't record what happened.");
    });

  function openSend() {
    // One key per time the dialog opens: every retry inside it repeats the same request.
    returnFocusTo.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setSendKey(newIdempotencyKey());
    setSendIssue(null);
    setSendOpen(true);
  }

  const send = (current: DraftOut) =>
    run("send", async () => {
      setStatus("Sending the message…");
      const r = await browserApi()
        .POST(SEND, {
          params: { path: { ...path, draft_id: current.id } },
          body: { idempotency_key: sendKey },
        })
        .catch(() => null);
      if (r?.data) {
        const out = r.data;
        const result = sendResult(out, r.response.status);
        adopt(out.draft);
        setSendOpen(false);
        switch (result.kind) {
          case "unknown":
            setStatus("We couldn't confirm the message was sent. See the note below.");
            break;
          case "failed":
            toast({ title: "The message wasn't sent", description: result.label, tone: "danger" });
            setStatus("The message was not sent.");
            break;
          case "replayed":
            toast({ title: "This message was already sent", tone: "info" });
            setStatus("That message had already been sent.");
            break;
          case "demo":
            toast({
              title: "Demo only: nothing was delivered",
              description: "The demo mailbox never sends real email.",
              tone: "warning",
            });
            setStatus("Demo send recorded. Nothing was delivered.");
            break;
          case "queued":
            toast({ title: "Message queued", description: "It is being sent.", tone: "info" });
            setStatus("The message is being sent.");
            break;
          default:
            toast({
              title: "Message sent",
              description: out.draft.to_address ? `Sent to ${out.draft.to_address}.` : "",
              tone: "success",
            });
            setStatus("The message was sent.");
        }
        router.refresh();
        return;
      }
      const e = explain(r);
      if (!e) return;
      const p = sendProblem(e.f);
      setSendIssue(p);
      setStatus("The message wasn't sent.");
      if (p.refresh) router.refresh();
    });

  /* ---------------------------------------------------------------- pieces */

  const stopped = thread.stop !== null;
  const queued = draft?.message?.delivery_state === "queued";
  const statusLine = draft && queued ? "Sending…" : status;
  const locked = draft ? isLocked(draft) : false;
  const dirty = draft ? isDirty(draft, subject, body) : false;
  const readOnly = !canEdit || stopped || draft?.status === "sent";

  const liveStatus = (
    <p
      role="status"
      aria-live="polite"
      data-testid="reply-status"
      className="min-h-5 text-sm text-muted"
    >
      {statusLine}
    </p>
  );

  const stopNotice = thread.stop ? (
    <Notice tone="danger" title="Replies are turned off for this contact">
      {thread.stop.text}
    </Notice>
  ) : null;

  const memberNote = !canEdit ? (
    <p className="text-sm text-muted">Only the workspace owner can write or send replies.</p>
  ) : null;

  const problemNotice = problem ? (
    <Notice tone="danger" title={problem.title}>
      <p>{problem.text}</p>
      {problem.addFacts ? (
        <p className="mt-1">
          <Link href={KNOWLEDGE_HREF} className={linkClass}>
            Add approved facts in the AI Workspace
          </Link>
        </p>
      ) : null}
    </Notice>
  ) : null;

  const message = draft?.message ?? null;
  const unknownNotice =
    draft && message?.delivery_state === "unknown" ? (
      <Notice tone="warning" title="Send outcome unknown">
        <p>
          We couldn&apos;t confirm this message was sent. Check your mailbox, then tell us what
          happened.
        </p>
        {canEdit ? (
          <div className="mt-2 flex flex-wrap gap-2">
            <Button
              variant="secondary"
              size="sm"
              disabled={busy !== null}
              onClick={() => void resolve(draft, "sent")}
            >
              It was sent
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={busy !== null}
              onClick={() => void resolve(draft, "not_sent")}
            >
              It was not sent
            </Button>
          </div>
        ) : null}
      </Notice>
    ) : null;

  const failedNotice =
    draft && message?.delivery_state === "failed" && draft.status !== "sent" ? (
      <Notice tone="danger" title="The last send failed">
        {message.delivery_label} You can try sending it again.
      </Notice>
    ) : null;

  const wrap = (children: ReactNode) => (
    <section aria-labelledby={headingId} className="flex flex-col gap-3 border-t border-line pt-4">
      <h2 id={headingId} className="text-base font-semibold text-fg">
        Reply
      </h2>
      {children}
    </section>
  );

  /* ---------------------------------------------------------------- read-only */

  if (draft && readOnly) {
    const sb = statusBadge(draft);
    const ab = authorBadge(draft);
    return wrap(
      <>
        {liveStatus}
        {stopNotice}
        {memberNote}
        {unknownNotice}
        {failedNotice}
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={sb.tone}>{sb.label}</Badge>
          <Badge tone={ab.tone}>{ab.label}</Badge>
        </div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
          <dt className="text-muted">To</dt>
          <dd className="min-w-0 break-words text-fg">{draft.to_address ?? "No recipient"}</dd>
          <dt className="text-muted">Subject</dt>
          <dd className="min-w-0 break-words text-fg">{draft.subject}</dd>
          <dt className="text-muted">Message</dt>
          <dd className="min-w-0 break-words whitespace-pre-wrap text-fg">{draft.body_text}</dd>
          {draft.status === "sent" && draft.sent_at ? (
            <>
              <dt className="text-muted">Sent</dt>
              <dd className="text-fg">{formatDateTime(draft.sent_at)}</dd>
            </>
          ) : null}
        </dl>
      </>,
    );
  }

  /* ---------------------------------------------------------------- no draft */

  if (!draft) {
    if (readOnly) {
      return wrap(
        <>
          {liveStatus}
          {stopNotice}
          {memberNote}
          {!stopped ? <p className="text-sm text-muted">No draft</p> : null}
        </>,
      );
    }
    if (!hasInbound(thread)) {
      return wrap(
        <>
          {liveStatus}
          <p className="text-sm text-muted">There&apos;s nothing to reply to yet.</p>
        </>,
      );
    }
    return wrap(
      <>
        <p className="text-sm text-muted">
          Suggestions use only facts you have approved. Nothing is sent without your approval.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => void suggest()} disabled={busy !== null}>
            {busy === "suggest" ? "Writing a draft…" : "Suggest a reply"}
          </Button>
          <Button variant="secondary" onClick={() => void create()} disabled={busy !== null}>
            {busy === "create" ? "Starting a draft…" : "Write my own"}
          </Button>
        </div>
        {liveStatus}
        {problemNotice}
      </>,
    );
  }

  /* ---------------------------------------------------------------- editor */

  const sb = statusBadge(draft);
  const ab = authorBadge(draft);
  const approvedNow = draft.status === "approved" && draft.approval_is_current;
  const sendable = canSend(draft, dirty);
  const reasons = warningTexts(suggestion?.warnings ?? []);
  const pending = busy !== null;
  const frozen = pending || locked;
  const empty = !subject.trim() || !body.trim();

  return wrap(
    <>
      {liveStatus}
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={sb.tone}>{sb.label}</Badge>
        <Badge tone={ab.tone}>{ab.label}</Badge>
        {dirty ? (
          <span className="text-[13px] font-medium text-warning">Unsaved changes</span>
        ) : null}
      </div>
      {suggestion ? <p className="text-[13px] text-muted">{suggestion.label}</p> : null}
      {thread.classification.needs_review ? (
        <Notice tone="warning" title="Check the classification first">
          {thread.classification.review_text}
        </Notice>
      ) : null}
      {reasons.length > 0 ? (
        <Notice tone="warning" title="Before you approve this draft">
          <ul className="list-disc space-y-0.5 pl-5">
            {reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </Notice>
      ) : null}
      {unknownNotice}
      {failedNotice}

      <div className="flex flex-col gap-3">
        <dl className="flex flex-col gap-1.5">
          <dt className="text-sm font-medium text-fg">To</dt>
          <dd className="min-w-0 break-words text-sm text-fg">
            {draft.to_address ?? "No recipient"}
            {fieldErrors.to_address ? (
              <span className="mt-1 block text-[13px] text-danger">{fieldErrors.to_address}</span>
            ) : null}
          </dd>
        </dl>
        <Field label="Subject" {...(fieldErrors.subject ? { error: fieldErrors.subject } : {})}>
          {(p) => (
            <Input
              {...p}
              value={subject}
              readOnly={frozen}
              onChange={(e) => setSubject(e.target.value)}
            />
          )}
        </Field>
        <Field
          label="Message"
          {...(approvedNow ? { hint: "Editing an approved draft withdraws your approval." } : {})}
          {...(fieldErrors.body_text ? { error: fieldErrors.body_text } : {})}
        >
          {(p) => (
            <Textarea
              {...p}
              ref={bodyRef}
              rows={12}
              maxLength={BODY_MAX}
              value={body}
              readOnly={frozen}
              onChange={(e) => setBody(e.target.value)}
            />
          )}
        </Field>
      </div>

      {draft.facts.length > 0 || draft.author === "ai" ? (
        <section aria-labelledby={factsId} className="flex flex-col gap-1.5">
          <h3 id={factsId} className="text-sm font-medium text-fg">
            Written using
          </h3>
          {draft.facts.length > 0 ? (
            <ul className="flex flex-col gap-1">
              {draft.facts.map((f) => (
                <li key={f.id} className="flex flex-wrap items-center gap-2 text-sm text-fg">
                  <span className="min-w-0 break-words">{f.title}</span>
                  <Badge tone="neutral">{f.kind}</Badge>
                  {!f.still_approved ? <Badge tone="warning">No longer approved</Badge> : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">
              No approved fact was cited; this was written from your profile only.
            </p>
          )}
          <p className="text-[13px]">
            <Link href={KNOWLEDGE_HREF} className={linkClass}>
              Review approved facts in the AI Workspace
            </Link>
          </p>
        </section>
      ) : null}

      {!locked ? (
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => void save(draft)} disabled={pending || !dirty}>
            {busy === "save" ? "Saving…" : "Save"}
          </Button>
          <Button
            variant="secondary"
            onClick={() => {
              if (dirty || draft.version > 1) setConfirming("regenerate");
              else void suggest();
            }}
            disabled={pending}
          >
            {busy === "suggest" ? "Writing a draft…" : "Regenerate"}
          </Button>
          <Button
            variant={sendable ? "secondary" : "primary"}
            onClick={() => void approve(draft, dirty)}
            disabled={pending || empty || (approvedNow && !dirty)}
          >
            {busy === "approve" ? "Approving…" : dirty ? "Save and approve" : "Approve"}
          </Button>
          <Button variant="secondary" onClick={() => setConfirming("discard")} disabled={pending}>
            {busy === "discard" ? "Discarding…" : "Discard"}
          </Button>
          {sendable ? (
            <Button onClick={openSend} disabled={pending}>
              Send
            </Button>
          ) : null}
        </div>
      ) : null}
      {problemNotice}

      <SendDialog
        open={sendOpen}
        onOpenChange={setSendOpen}
        to={draft.to_address ?? ""}
        mailbox={thread.account_email}
        isDemo={thread.is_demo}
        subject={draft.subject}
        pending={busy === "send"}
        problem={sendIssue}
        onSend={() => void send(draft)}
      />
      <ConfirmDialog
        open={confirming === "regenerate"}
        onOpenChange={(open) => !open && setConfirming(null)}
        title="Replace this draft?"
        description="This replaces the text you have written with a new suggestion. Nothing is sent."
        confirmLabel="Replace draft"
        onConfirm={() => void suggest()}
      />
      <ConfirmDialog
        open={confirming === "discard"}
        onOpenChange={(open) => !open && setConfirming(null)}
        title="Discard this draft?"
        description="The draft is deleted. Nothing has been sent, and you can start a new one."
        confirmLabel="Discard draft"
        destructive
        onConfirm={() => void discard(draft)}
      />
    </>,
  );
}
