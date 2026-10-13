"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, ConfirmDialog, Notice, useToast } from "@freelancer-os/ui";
import { formatDateTime } from "@/components/leads/lead-model";
import { browserApi, toFailure } from "@/lib/api-client";
import { describeFailure } from "@/lib/mutation-error";
import type { StopOut } from "./inbox-model";

/** Why messages to this contact are blocked, and (for the owner) how to lift it. */
export function StopBanner({
  workspaceId,
  stop,
  canEdit,
}: {
  workspaceId: string;
  stop: StopOut;
  canEdit: boolean;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);

  async function remove() {
    if (busy) return;
    setBusy(true);
    try {
      const { error, response } = await browserApi().DELETE(
        "/api/v1/workspaces/{workspace_id}/suppressions/{suppression_id}",
        { params: { path: { workspace_id: workspaceId, suppression_id: stop.id } } },
      );
      if (response.ok) {
        toast({
          title: "Removed from the do-not-contact list",
          description: `${stop.address} can be contacted again.`,
          tone: "success",
        });
        router.refresh();
      } else {
        const out = describeFailure(error, response, "contact");
        if (out) {
          toast({ title: "Couldn't remove it", description: out.failure.text, tone: "danger" });
        }
      }
    } catch {
      toast({
        title: "Couldn't remove it",
        description: toFailure(undefined).message,
        tone: "danger",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Notice tone="danger" title="Contact stopped">
        <p>{stop.text}</p>
        <p className="mt-1 break-words text-[13px]">
          <span className="text-fg">{stop.address}</span>
          {", added "}
          {formatDateTime(stop.since)}
        </p>
        {canEdit ? (
          <div className="mt-3">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setConfirming(true)}
              disabled={busy}
            >
              {busy ? "Removing…" : "Remove from do-not-contact list"}
            </Button>
          </div>
        ) : null}
      </Notice>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={`Remove ${stop.address} from your do-not-contact list?`}
        description="Future messages to this address become possible again. Nothing is sent until you approve a message."
        confirmLabel="Remove from list"
        destructive
        onConfirm={() => void remove()}
      />
    </>
  );
}
