"use client";

/**
 * Full-page navigation for authentication boundaries (sign-in, sign-up, sign-out, finishing
 * onboarding). A hard navigation guarantees fresh server state and drops the client router cache,
 * so no authenticated page can be shown from cache after sign-out. It also avoids racing
 * `router.replace()` against `router.refresh()`, which could leave a blank page.
 *
 * `path` must be a same-origin path; callers pass values already validated by `safeNextPath`.
 */
export function hardNavigate(path: string): void {
  window.location.assign(path);
}
