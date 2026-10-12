import type { Metadata } from "next";
import Link from "next/link";
import { AuthCard, CredentialFields } from "@/components/auth-preview";

export const metadata: Metadata = { title: "Create account" };

export default function SignUpPage() {
  return (
    <AuthCard
      title="Create your account"
      description="Set up a personal workspace for your leads, outreach and automations."
      footer={
        <>
          Already have an account?{" "}
          <Link href="/sign-in" className="text-fg underline underline-offset-4">
            Sign in
          </Link>
        </>
      }
    >
      <CredentialFields withName />
    </AuthCard>
  );
}
