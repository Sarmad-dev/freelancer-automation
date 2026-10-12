import { redirect } from "next/navigation";
import { ErrorState } from "@freelancer-os/ui";
import { SessionProvider } from "@/components/session-provider";
import { AppShell } from "@/components/shell/app-shell";
import { getSession } from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const session = await getSession();
  if (session.status === "expired") redirect("/sign-in?reason=expired");
  if (session.status === "anonymous") redirect("/sign-in");
  if (session.status === "unavailable") {
    // Don't bounce to sign-in (that would look like being logged out); say what's wrong.
    return (
      <main className="mx-auto flex min-h-screen max-w-lg items-center p-6">
        <ErrorState
          title="Can't reach the service"
          description="We couldn't verify your session because the API isn't responding. Your data is safe. Try again in a moment."
        />
      </main>
    );
  }
  return (
    <SessionProvider me={session.me}>
      <AppShell>{children}</AppShell>
    </SessionProvider>
  );
}
