import { redirect } from "next/navigation";
import { AuthFrame } from "@/components/auth/auth-frame";
import { getSession } from "@/lib/session";

export const dynamic = "force-dynamic";

/** Public auth pages. Visitors who are already signed in go straight to the app. */
export default async function AuthLayout({ children }: { children: React.ReactNode }) {
  const session = await getSession();
  if (session.status === "authenticated") redirect("/");
  return <AuthFrame>{children}</AuthFrame>;
}
