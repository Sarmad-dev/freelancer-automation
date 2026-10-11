export const dynamic = "force-dynamic";

/** Liveness probe for the web app (does not call the API). */
export function GET() {
  return Response.json({ status: "ok", service: "freelancer-os-web" });
}
