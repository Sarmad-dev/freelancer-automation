import type { Metadata } from "next";
import Link from "next/link";
import { AuthCard, CredentialFields } from "@/components/auth-preview";

export const metadata: Metadata = { title: "Sign in" };

export default function SignInPage() {
  return (
    <AuthCard
      title="Sign in"
      description="Welcome back. Pick up your leads and follow-ups where you left off."
      footer={
        <>
          New here?{" "}
          <Link href="/sign-up" className="text-fg underline underline-offset-4">
            Create an account
          </Link>
        </>
      }
    >
      <CredentialFields />
    </AuthCard>
  );
}
