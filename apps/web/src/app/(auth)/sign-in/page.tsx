import type { Metadata } from "next";
import Link from "next/link";
import { AuthHeading } from "@/components/auth/auth-frame";
import { SignInForm } from "@/components/auth/sign-in-form";
import { safeNextPath } from "@/lib/safe-redirect";
import { getAuthConfig } from "@/lib/session";

export const metadata: Metadata = { title: "Sign in" };

export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; reason?: string; reset?: string }>;
}) {
  const sp = await searchParams;
  const { passwordResetEnabled } = await getAuthConfig();
  const notice = sp.reset === "1" ? "reset" : sp.reason === "expired" ? "expired" : undefined;
  return (
    <div className="flex flex-col gap-6">
      <AuthHeading
        title="Sign in"
        description="Welcome back. Pick up your leads and follow-ups where you left off."
      />
      <SignInForm
        next={safeNextPath(sp.next)}
        notice={notice}
        passwordResetEnabled={passwordResetEnabled}
      />
      <p className="text-center text-sm text-muted">
        New here?{" "}
        <Link href="/sign-up" className="text-fg underline underline-offset-4">
          Create an account
        </Link>
      </p>
    </div>
  );
}
