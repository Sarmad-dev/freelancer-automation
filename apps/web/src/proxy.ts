import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE_NAMES, isPublicPath } from "@/lib/auth-constants";

/**
 * Optimistic gate: send visitors without a session cookie to sign-in before rendering anything.
 * This is a UX shortcut, not the security boundary: pages and the API validate the session for real.
 */
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  if (isPublicPath(pathname)) return NextResponse.next();

  const hasCookie = SESSION_COOKIE_NAMES.some((n) => request.cookies.has(n));
  if (hasCookie) return NextResponse.next();

  const url = request.nextUrl.clone();
  url.pathname = "/sign-in";
  url.search = "";
  if (pathname !== "/") url.searchParams.set("next", `${pathname}${search}`);
  return NextResponse.redirect(url);
}

export const config = {
  // Skip static assets and Next internals.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|icon.svg).*)"],
};
