import { redirect } from "next/navigation";
import { AuthFrame } from "@/components/auth/auth-frame";
import { SessionProvider } from "@/components/session-provider";
import { getSession } from "@/lib/session";

export const dynamic = "force-dynamic";

/** Signed-in full-page flows (onboarding) that don't use the app shell. */
export default async function FlowLayout({ children }: { children: React.ReactNode }) {
  const session = await getSession();
  if (session.status === "expired") redirect("/sign-in?reason=expired");
  if (session.status !== "authenticated") redirect("/sign-in");
  return (
    <SessionProvider me={session.me}>
      <AuthFrame>{children}</AuthFrame>
    </SessionProvider>
  );
}
