import type { Metadata } from "next";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { createApiClient } from "@freelancer-os/contracts";
import { ErrorState } from "@freelancer-os/ui";
import { OnboardingWizard } from "@/components/onboarding/wizard";
import { getEnv } from "@/env";
import { SESSION_COOKIE_NAMES } from "@/lib/auth-constants";
import { getSession } from "@/lib/session";

export const metadata: Metadata = { title: "Onboarding" };
export const dynamic = "force-dynamic";

export default async function OnboardingPage() {
  const session = await getSession();
  if (session.status !== "authenticated") redirect("/sign-in");
  const workspace = session.me.workspaces[0];
  if (!workspace) redirect("/sign-in");

  const jar = await cookies();
  const cookie = SESSION_COOKIE_NAMES.map((n) =>
    jar.get(n)?.value ? `${n}=${jar.get(n)?.value}` : null,
  ).find(Boolean);
  const client = createApiClient(getEnv().API_URL, {
    headers: cookie ? { cookie } : {},
    fetch: ((req: Request) =>
      fetch(req, { cache: "no-store", signal: AbortSignal.timeout(5000) })) as typeof fetch,
  });
  const { data } = await client
    .GET("/api/v1/workspaces/{workspace_id}/onboarding", {
      params: { path: { workspace_id: workspace.id } },
    })
    .catch(() => ({ data: undefined }));

  if (!data) {
    return (
      <ErrorState
        title="Couldn't load your setup"
        description="Please refresh the page. Your answers are saved."
      />
    );
  }
  return <OnboardingWizard workspaceId={workspace.id} initial={data} />;
}
