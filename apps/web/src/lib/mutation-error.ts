import { isSessionLost, redirectToSignIn, toFailure } from "@/lib/api-client";

export interface MutationFailure {
  title: string;
  text: string;
  /** The record changed elsewhere (409 stale_version): offer a reload instead of a retry. */
  reload?: boolean;
}

/**
 * One way to turn a failed mutation into UI state, for every form.
 * Returns null when the session expired (the browser is already on its way to sign-in).
 */
export function describeFailure(
  error: unknown,
  response?: Response,
  subject = "item",
): { failure: MutationFailure; fields: Record<string, string> } | null {
  const f = toFailure(error, response);
  if (isSessionLost(f)) {
    redirectToSignIn("expired");
    return null;
  }
  if (f.code === "stale_version") {
    return {
      failure: { title: `This ${subject} changed`, text: f.message, reload: true },
      fields: {},
    };
  }
  const hasFields = Object.keys(f.fields).length > 0;
  return {
    failure: {
      title: hasFields ? "Some fields need attention" : "That didn't work",
      text: hasFields ? "Fix the highlighted fields and try again." : f.message,
    },
    fields: f.fields,
  };
}
