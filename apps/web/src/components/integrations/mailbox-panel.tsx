"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Badge, Button, ConfirmDialog, EmptyState, Notice, useToast } from "@freelancer-os/ui";
import { SampleBadge } from "@/components/leads/lead-badges";
import { browserApi, toFailure } from "@/lib/api-client";
import { describeFailure } from "@/lib/mutation-error";
import {
  STATUS_BADGE,
  STATUS_TONE,
  actionsFor,
  syncSummary,
  when,
  type EmailAccountOut,
  type Flash,
  type ProviderOut,
} from "./mailbox-model";

type Verb = "sync" | "test" | "disconnect" | "connect" | "demo";

const goTo = (url: string) => window.location.assign(url);

export function MailboxPanel({
  workspaceId,
  accounts,
  providers,
  canEdit,
  flash,
  navigate = goTo,
}: {
  workspaceId: string;
  accounts: readonly EmailAccountOut[];
  providers: readonly ProviderOut[];
  canEdit: boolean;
  flash: Flash | null;
  /** Leaves the site for the provider's consent screen. Injected so tests can observe it. */
  navigate?: (url: string) => void;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<EmailAccountOut | null>(null);
  const label = (key: string) => providers.find((p) => p.key === key)?.label ?? key;
  const path = { workspace_id: workspaceId };

  async function run(key: string, verb: Verb, call: () => Promise<void>) {
    if (busy) return;
    setBusy(key + ":" + verb);
    try {
      await call();
    } catch {
      toast({
        title: "That didn't work",
        description: toFailure(undefined).message,
        tone: "danger",
      });
    } finally {
      setBusy(null);
    }
  }

  function failed(error: unknown, response: Response, title: string) {
    const out = describeFailure(error, response, "mailbox");
    if (out) toast({ title, description: out.failure.text, tone: "danger" });
  }

  const sync = (a: EmailAccountOut) =>
    run(a.id, "sync", async () => {
      const { data, error, response } = await browserApi().POST(
        "/api/v1/workspaces/{workspace_id}/email/accounts/{account_id}/sync",
        { params: { path: { ...path, account_id: a.id } } },
      );
      if (data) {
        const s = syncSummary(data);
        toast({ title: s.title, description: s.text, tone: s.tone });
        router.refresh();
      } else {
        failed(error, response, "Couldn't sync");
        router.refresh();
      }
    });

  const test = (a: EmailAccountOut) =>
    run(a.id, "test", async () => {
      const { data, error, response } = await browserApi().POST(
        "/api/v1/workspaces/{workspace_id}/email/accounts/{account_id}/test",
        { params: { path: { ...path, account_id: a.id } } },
      );
      if (data) {
        toast(
          data.ok
            ? {
                title: "Connection works",
                description: "The provider answered a real request.",
                tone: "success",
              }
            : {
                title: "The connection test failed",
                description: data.account.last_error ?? "The provider did not answer.",
                tone: "danger",
              },
        );
      } else {
        failed(error, response, "Couldn't test the connection");
      }
      router.refresh();
    });

  const disconnect = (a: EmailAccountOut) =>
    run(a.id, "disconnect", async () => {
      const { data, error, response } = await browserApi().POST(
        "/api/v1/workspaces/{workspace_id}/email/accounts/{account_id}/disconnect",
        { params: { path: { ...path, account_id: a.id } } },
      );
      if (data) {
        toast(
          data.revoked
            ? {
                title: "Disconnected",
                description: "Access was revoked and the stored credentials were deleted.",
                tone: "success",
              }
            : {
                title: "Disconnected here",
                description:
                  "We deleted our copy of the credentials but couldn't confirm the provider revoked access. Remove Freelancer OS in your provider's account permissions too.",
                tone: "warning",
              },
        );
      } else {
        failed(error, response, "Couldn't disconnect");
      }
      router.refresh();
    });

  const connect = (provider: string, id: string) =>
    run(id, "connect", async () => {
      const { data, error, response } = await browserApi().POST(
        "/api/v1/workspaces/{workspace_id}/email/accounts/connect",
        { params: { path }, body: { provider: provider as "gmail" } },
      );
      if (data) navigate(data.authorization_url);
      else failed(error, response, "Couldn't start the connection");
    });

  const addDemo = () =>
    run("demo", "demo", async () => {
      const { data, error, response } = await browserApi().POST(
        "/api/v1/workspaces/{workspace_id}/email/accounts/demo",
        { params: { path } },
      );
      if (data) {
        toast({
          title: "Demo mailbox added",
          description: "It holds fictional data and never sends real email.",
          tone: "success",
        });
        router.refresh();
      } else {
        failed(error, response, "Couldn't add the demo mailbox");
      }
    });

  const isBusy = (id: string, verb: Verb) => busy === id + ":" + verb;
  const hasDemo = accounts.some((a) => a.provider === "demo");

  return (
    <div className="flex flex-col gap-8">
      {flash ? (
        <Notice tone={flash.tone === "success" ? "success" : flash.tone} title={flash.title}>
          {flash.text}
        </Notice>
      ) : null}
      {!canEdit ? (
        <Notice title="View only">
          Only the workspace owner can add, sync, test or disconnect mailboxes.
        </Notice>
      ) : null}

      <section aria-labelledby="mailboxes-heading" className="flex flex-col gap-3">
        <div>
          <h2 id="mailboxes-heading" className="text-base font-semibold text-fg">
            Mailboxes
          </h2>
          <p className="text-sm text-muted">
            A mailbox shows as connected only after a real request to the provider has succeeded.
          </p>
        </div>
        {accounts.length === 0 ? (
          <EmptyState
            title="No mailbox yet"
            description="Add the demo mailbox to explore with fictional data, or connect a real one below."
          />
        ) : (
          <ul className="flex flex-col gap-3">
            {accounts.map((a) => {
              const actions = actionsFor(a);
              return (
                <li key={a.id} className="rounded-lg border border-line bg-surface p-4">
                  <article aria-label={a.email_address} className="flex flex-col gap-3">
                    <header className="flex flex-wrap items-center gap-2">
                      <h3 className="text-sm font-semibold text-fg">{a.email_address}</h3>
                      <Badge tone={STATUS_TONE[a.status]}>{STATUS_BADGE[a.status]}</Badge>
                      {a.is_demo ? <SampleBadge /> : null}
                      <span className="text-[13px] text-muted">{label(a.provider)}</span>
                    </header>
                    <p className="text-sm text-muted">{a.status_label}</p>
                    <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-[13px] sm:grid-cols-2">
                      <div className="flex gap-2">
                        <dt className="text-muted">Last synced</dt>
                        <dd className="text-fg">{when(a.last_synced_at, "Never")}</dd>
                      </div>
                      <div className="flex gap-2">
                        <dt className="text-muted">Last tested</dt>
                        <dd className="text-fg">{when(a.last_health_check_at, "Never")}</dd>
                      </div>
                      {a.granted_scopes.length > 0 ? (
                        <div className="flex gap-2 sm:col-span-2">
                          <dt className="text-muted">Permissions</dt>
                          <dd className="min-w-0 break-words text-fg">
                            {a.granted_scopes.map((s) => s.split("/").pop()).join(", ")}
                          </dd>
                        </div>
                      ) : null}
                    </dl>
                    {a.last_error ? (
                      <Notice
                        tone={
                          a.status === "connected" || a.status === "demo" ? "warning" : "danger"
                        }
                        title="Last problem"
                      >
                        {a.last_error}
                      </Notice>
                    ) : null}
                    {a.rate_limited_until ? (
                      <Notice tone="warning" title="Paused by the provider">
                        {`Syncing and sending resume after ${when(a.rate_limited_until, "a short wait")}.`}
                      </Notice>
                    ) : null}
                    {canEdit ? (
                      <div className="flex flex-wrap gap-2">
                        {actions.reconnect ? (
                          <Button
                            onClick={() => connect(a.provider, a.id)}
                            disabled={busy !== null}
                            aria-label={`${a.status === "disconnected" ? "Connect" : "Reconnect"} ${a.email_address}`}
                          >
                            {isBusy(a.id, "connect")
                              ? "Opening…"
                              : a.status === "disconnected"
                                ? "Connect again"
                                : "Reconnect"}
                          </Button>
                        ) : null}
                        {actions.sync ? (
                          <Button
                            variant="secondary"
                            onClick={() => sync(a)}
                            disabled={busy !== null}
                            aria-label={`Sync ${a.email_address} now`}
                          >
                            {isBusy(a.id, "sync") ? "Syncing…" : "Sync now"}
                          </Button>
                        ) : null}
                        {actions.test ? (
                          <Button
                            variant="secondary"
                            onClick={() => test(a)}
                            disabled={busy !== null}
                            aria-label={`Test the connection for ${a.email_address}`}
                          >
                            {isBusy(a.id, "test") ? "Testing…" : "Test connection"}
                          </Button>
                        ) : null}
                        {actions.disconnect ? (
                          <Button
                            variant="secondary"
                            onClick={() => setConfirming(a)}
                            disabled={busy !== null}
                            aria-label={`Disconnect ${a.email_address}`}
                          >
                            Disconnect
                          </Button>
                        ) : null}
                      </div>
                    ) : null}
                  </article>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section aria-labelledby="available-heading" className="flex flex-col gap-3">
        <div>
          <h2 id="available-heading" className="text-base font-semibold text-fg">
            Available connectors
          </h2>
          <p className="text-sm text-muted">
            Only connectors that exist in this version are listed.
          </p>
        </div>
        <ul className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {providers.map((p) => {
            const already = p.is_demo && hasDemo;
            return (
              <li key={p.key} className="rounded-lg border border-line bg-surface p-4">
                <article aria-label={p.label} className="flex h-full flex-col gap-3">
                  <header className="flex flex-wrap items-center gap-2">
                    <h3 className="text-sm font-semibold text-fg">{p.label}</h3>
                    {p.is_demo ? <Badge tone="info">Demo</Badge> : null}
                    {!p.is_demo && !p.configured ? <Badge tone="warning">Not set up</Badge> : null}
                    {!p.verified_live && !p.is_demo ? (
                      <Badge tone="neutral">Not verified live</Badge>
                    ) : null}
                  </header>
                  {p.notes.length > 0 ? (
                    <ul className="list-disc space-y-0.5 pl-5 text-[13px] text-muted">
                      {p.notes.map((n) => (
                        <li key={n}>{n}</li>
                      ))}
                    </ul>
                  ) : null}
                  {p.scopes.length > 0 ? (
                    <div>
                      <h4 className="text-[13px] font-medium text-fg">What it asks for, and why</h4>
                      <ul className="mt-1 space-y-1 text-[13px] text-muted">
                        {p.scopes.map((s) => (
                          <li key={s.scope}>
                            <span className="font-mono text-xs text-fg break-all">
                              {s.scope.split("/").pop()}
                            </span>
                            {": "}
                            {s.why}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {!p.is_demo && !p.configured ? (
                    <p className="text-[13px] text-muted">
                      This server has no {p.label} credentials yet. An administrator can add them by
                      following the setup steps in docs/EMAIL.md.
                    </p>
                  ) : null}
                  {canEdit ? (
                    <div className="mt-auto">
                      {p.is_demo ? (
                        <Button
                          variant="secondary"
                          onClick={addDemo}
                          disabled={busy !== null || already}
                        >
                          {already
                            ? "Demo mailbox added"
                            : isBusy("demo", "demo")
                              ? "Adding…"
                              : "Add demo mailbox"}
                        </Button>
                      ) : (
                        <Button
                          onClick={() => connect(p.key, p.key)}
                          disabled={busy !== null || !p.configured}
                        >
                          {isBusy(p.key, "connect") ? "Opening…" : `Connect ${p.label}`}
                        </Button>
                      )}
                    </div>
                  ) : null}
                </article>
              </li>
            );
          })}
        </ul>
      </section>

      <ConfirmDialog
        open={confirming !== null}
        onOpenChange={(open) => !open && setConfirming(null)}
        title={`Disconnect ${confirming?.email_address ?? "this mailbox"}?`}
        description="We will ask the provider to revoke access and delete our stored credentials. Conversations already synced stay. Nothing is deleted from the mailbox itself."
        confirmLabel="Disconnect"
        destructive
        onConfirm={() => {
          if (confirming) void disconnect(confirming);
        }}
      />
    </div>
  );
}
