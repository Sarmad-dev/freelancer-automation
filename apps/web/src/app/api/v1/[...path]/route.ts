import type { NextRequest } from "next/server";
import { getEnv } from "@/env";
import { buildUpstreamPath, pickRequestHeaders, pickResponseHeaders } from "@/lib/api-proxy";

export const dynamic = "force-dynamic";

const UPSTREAM_TIMEOUT_MS = 15_000;

async function forward(request: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const upstreamPath = buildUpstreamPath(path);
  if (!upstreamPath) {
    return Response.json({ error: { code: "not_found", message: "Not found." } }, { status: 404 });
  }

  const url = new URL(upstreamPath, getEnv().API_URL);
  url.search = request.nextUrl.search;

  const hasBody = !["GET", "HEAD"].includes(request.method);
  try {
    const upstream = await fetch(url, {
      method: request.method,
      headers: pickRequestHeaders(request.headers),
      body: hasBody ? await request.arrayBuffer() : undefined,
      redirect: "manual",
      cache: "no-store",
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
    return new Response(upstream.status === 204 ? null : upstream.body, {
      status: upstream.status,
      headers: pickResponseHeaders(upstream.headers),
    });
  } catch {
    // Never leak upstream addresses or error details to the browser.
    return Response.json(
      {
        error: { code: "service_unavailable", message: "The service is temporarily unavailable." },
      },
      { status: 503, headers: { "cache-control": "no-store" } },
    );
  }
}

export { forward as GET, forward as POST, forward as PUT, forward as PATCH, forward as DELETE };
