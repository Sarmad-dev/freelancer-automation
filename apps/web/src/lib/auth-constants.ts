/** Session cookie names set by the API (the __Host- form is used when cookies are Secure). */
export const SESSION_COOKIE_NAMES = ["__Host-fos_session", "fos_session"] as const;

/** Header the API requires on state-changing requests (CSRF defence in depth). */
export const CSRF_HEADER = "X-Requested-With";
export const CSRF_HEADER_VALUE = "freelancer-os";

/** Routes reachable without a session. Everything else requires one. */
export const PUBLIC_PATHS = [
  "/sign-in",
  "/sign-up",
  "/forgot-password",
  "/reset-password",
] as const;

export function isPublicPath(pathname: string): boolean {
  return (
    PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`)) ||
    pathname === "/api/health" ||
    pathname.startsWith("/api/v1/")
  );
}
