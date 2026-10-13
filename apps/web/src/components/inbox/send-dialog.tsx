"use client";

import Link from "next/link";
import { Button, Modal, Notice } from "@freelancer-os/ui";
import { INTEGRATIONS_HREF, type SendProblem } from "./reply-model";

/**
 * The last look before a message leaves. Cancel is the default action. The dialog holds no state of its
 * own: the editor owns the idempotency key (made when the dialog opens) and the request.
 */
export function SendDialog({
  open,
  onOpenChange,
  to,
  mailbox,
  isDemo,
  subject,
  pending,
  problem,
  onSend,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  to: string;
  mailbox: string;
  isDemo: boolean;
  subject: string;
  pending: boolean;
  problem: SendProblem | null;
  onSend: () => void;
}) {
  return (
    <Modal
      open={open}
      onOpenChange={(next) => {
        if (!pending) onOpenChange(next);
      }}
      title="Send this message?"
      description="Check who it goes to. Once sent, it can't be taken back."
      footer={
        <>
          <Button
            variant="secondary"
            autoFocus
            disabled={pending}
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button onClick={onSend} disabled={pending || problem?.blocked === true}>
            {pending ? "Sending…" : problem && !problem.blocked ? "Try again" : "Send message"}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-muted">To</dt>
          <dd className="min-w-0 break-words text-fg">{to}</dd>
          <dt className="text-muted">From</dt>
          <dd className="min-w-0 break-words text-fg">{mailbox}</dd>
          <dt className="text-muted">Subject</dt>
          <dd className="min-w-0 break-words text-fg">{subject}</dd>
        </dl>
        {isDemo ? (
          <p className="text-sm font-medium text-fg">
            Demo mailbox: nothing will be delivered to anyone.
          </p>
        ) : null}
        <p className="text-sm text-muted">This sends exactly the text you approved.</p>
        {problem ? (
          <Notice tone="danger" title="The message wasn't sent">
            <p>{problem.text}</p>
            {problem.reconnect ? (
              <p className="mt-1">
                <Link href={INTEGRATIONS_HREF} className="text-accent underline underline-offset-2">
                  Reconnect your mailbox in Integrations
                </Link>
              </p>
            ) : null}
          </Notice>
        ) : null}
      </div>
    </Modal>
  );
}
