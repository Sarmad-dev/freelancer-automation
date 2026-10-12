import type { components } from "@freelancer-os/contracts";
import type { BadgeTone } from "@freelancer-os/ui";
import { formatDateTime } from "@/components/leads/lead-model";

type Schemas = components["schemas"];
export type EmailAccountOut = Schemas["EmailAccountOut"];
export type ProviderOut = Schemas["ProviderOut"];
export type SyncOut = Schemas["SyncOut"];

export type AccountStatus = EmailAccountOut["status"];

export const STATUS_TONE: Record<AccountStatus, BadgeTone> = {
  connected: "success",
  demo: "info",
  needs_reauth: "warning",
  error: "danger",
  disconnected: "neutral",
};

/** Short badge text. The longer, plain-language explanation comes from the API (`status_label`, `last_error`). */
export const STATUS_BADGE: Record<AccountStatus, string> = {
  connected: "Connected",
  demo: "Demo",
  needs_reauth: "Reconnect needed",
  error: "Problem",
  disconnected: "Disconnected",
};

export interface Flash {
  tone: "success" | "danger" | "warning";
  title: string;
  text: string;
}

const CONNECT_ERRORS: Record<string, string> = {
  denied: "You declined access at the provider, so nothing was connected.",
  insufficient_scopes:
    "The provider connected, but not every permission was allowed. Connect again and keep all the boxes ticked: Freelancer OS needs to read replies and to send the messages you approve.",
  no_refresh_token:
    "The provider did not allow ongoing access, so the mailbox was not connected. Connect again and approve the request.",
  expired: "That sign-in took too long and expired. Start again.",
  invalid_state: "That sign-in link was not valid or was already used. Start again from this page.",
  wrong_user: "That sign-in was started by a different account. Start again from this page.",
  not_allowed: "Only the workspace owner can connect a mailbox.",
  signed_out: "Sign in to Freelancer OS and start the connection again.",
  exchange_failed:
    "The provider refused the sign-in. Start again, and check the server's client credentials if it keeps happening.",
  profile_failed:
    "The provider signed you in, but a test of the connection failed, so the mailbox was not connected.",
  provider_unavailable: "The provider is not responding right now. Try again shortly.",
  provider_error: "The provider reported a problem. Try again.",
};

function first(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value) ?? "";
}

/** The banner for `?email=connected` / `?email=error&reason=…` after returning from the provider. */
export function flashFrom(params: Record<string, string | string[] | undefined>): Flash | null {
  const result = first(params.email);
  if (result === "connected") {
    return {
      tone: "success",
      title: "Mailbox connected",
      text: "The connection test succeeded. Use Sync now to bring in your conversations.",
    };
  }
  if (result === "error") {
    const reason = first(params.reason);
    return {
      tone: reason === "denied" ? "warning" : "danger",
      title: "The mailbox was not connected",
      text: CONNECT_ERRORS[reason] ?? "Something went wrong while connecting. Start again.",
    };
  }
  return null;
}

/** `2026-10-12 14:05 UTC`, or a plain statement when it never happened. */
export function when(iso: string | null | undefined, never: string): string {
  return iso ? formatDateTime(iso) || never : never;
}

export function actionsFor(account: Pick<EmailAccountOut, "status" | "is_demo">): {
  sync: boolean;
  test: boolean;
  reconnect: boolean;
  disconnect: boolean;
} {
  switch (account.status) {
    case "connected":
      return { sync: true, test: true, reconnect: false, disconnect: true };
    case "demo":
      return { sync: true, test: false, reconnect: false, disconnect: false };
    case "needs_reauth":
      return { sync: false, test: false, reconnect: true, disconnect: true };
    case "error":
      return { sync: true, test: true, reconnect: false, disconnect: true };
    case "disconnected":
      return { sync: false, test: false, reconnect: true, disconnect: false };
  }
}

export function syncSummary(result: SyncOut): {
  title: string;
  text: string;
  tone: "success" | "warning";
} {
  const found = `${result.messages_created} new message${result.messages_created === 1 ? "" : "s"} in ${result.conversations_created} new conversation${result.conversations_created === 1 ? "" : "s"}`;
  if (result.error_code === "rate_limited") {
    return {
      tone: "warning",
      title: "Paused by the provider",
      text: `${found} so far. The provider asked us to slow down; syncing continues later.`,
    };
  }
  if (result.error_code) {
    return {
      tone: "warning",
      title: "Sync stopped early",
      text: `${found} so far. The provider stopped responding; try again shortly.`,
    };
  }
  if (!result.complete) {
    return {
      tone: "success",
      title: "Sync in progress",
      text: `${found}. Run it again to continue.`,
    };
  }
  if (result.messages_created === 0 && result.messages_updated === 0) {
    return { tone: "success", title: "Up to date", text: "No new messages." };
  }
  return { tone: "success", title: "Sync complete", text: `${found}.` };
}
