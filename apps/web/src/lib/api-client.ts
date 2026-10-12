"use client";

import { createApiClient } from "@freelancer-os/contracts";
import { CSRF_HEADER, CSRF_HEADER_VALUE } from "./auth-constants";

/** Typed same-origin API client for browser code (cookies are sent automatically). */
export function browserApi() {
  return createApiClient(window.location.origin, { headers: { [CSRF_HEADER]: CSRF_HEADER_VALUE } });
}

export interface ApiFailure {
  status: number;
  code: string;
  message: string;
  fields: Record<string, string>;
  retryAfter?: number;
}

const NETWORK_FAILURE: ApiFailure = {
  status: 0,
  code: "network_error",
  message: "Can't reach the server. Check your connection and try again.",
  fields: {},
};

/** Normalise an openapi-fetch error result (or a thrown network error) into one shape for forms. */
export function toFailure(error: unknown, response?: Response): ApiFailure {
  if (!response) return NETWORK_FAILURE;
  const body = (
    error as
      { error?: { code?: string; message?: string; fields?: Record<string, string> } } | undefined
  )?.error;
  const retry = Number(response.headers.get("retry-after"));
  return {
    status: response.status,
    code: body?.code ?? "unknown_error",
    message:
      body?.message ??
      (response.status >= 500
        ? "The service is temporarily unavailable. Try again shortly."
        : "Something went wrong."),
    fields: body?.fields ?? {},
    ...(Number.isFinite(retry) && retry > 0 ? { retryAfter: retry } : {}),
  };
}

/** True when the failure means the user must sign in again. */
export function isSessionLost(f: ApiFailure): boolean {
  return f.status === 401 && (f.code === "session_expired" || f.code === "not_authenticated");
}

/** Send the user to sign-in, remembering where they were. Never throws. */
export function redirectToSignIn(reason: "expired" | "required" = "expired") {
  const here = `${window.location.pathname}${window.location.search}`;
  const params = new URLSearchParams({ reason });
  if (here !== "/") params.set("next", here);
  // Hard navigation on purpose: it discards all client state tied to the dead session.
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  window.location.assign(`/sign-in?${params.toString()}`);
}

export function describeRateLimit(f: ApiFailure): string {
  return f.retryAfter
    ? `Too many attempts. Try again in ${f.retryAfter < 60 ? `${f.retryAfter} seconds` : `${Math.ceil(f.retryAfter / 60)} minutes`}.`
    : f.message;
}
