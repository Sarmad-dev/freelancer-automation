import type { Metadata } from "next";
import Link from "next/link";
import { AuthHeading } from "@/components/auth/auth-frame";
import { SignUpForm } from "@/components/auth/sign-up-form";

export const metadata: Metadata = { title: "Create account" };

export default function SignUpPage() {
  return (
    <div className="flex flex-col gap-6">
      <AuthHeading
        title="Create your account"
        description="Set up a personal workspace for your leads, outreach and automations."
      />
      <SignUpForm />
      <p className="text-center text-sm text-muted">
        Already have an account?{" "}
        <Link href="/sign-in" className="text-fg underline underline-offset-4">
          Sign in
        </Link>
      </p>
    </div>
  );
}
