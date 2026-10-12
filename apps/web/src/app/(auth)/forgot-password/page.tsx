import type { Metadata } from "next";
import Link from "next/link";
import { Notice } from "@freelancer-os/ui";
import { AuthHeading } from "@/components/auth/auth-frame";
import { ForgotPasswordForm } from "@/components/auth/password-reset-forms";
import { getAuthConfig } from "@/lib/session";

export const metadata: Metadata = { title: "Reset password" };

export default async function ForgotPasswordPage() {
  const { passwordResetEnabled } = await getAuthConfig();
  return (
    <div className="flex flex-col gap-6">
      <AuthHeading
        title="Reset your password"
        description="Enter your email and we'll send you a reset link."
      />
      {passwordResetEnabled ? (
        <ForgotPasswordForm />
      ) : (
        <Notice tone="info" title="Password reset isn't available yet">
          Outgoing email isn&apos;t configured on this server. Ask the administrator to reset your
          password.
        </Notice>
      )}
      <p className="text-center text-sm">
        <Link href="/sign-in" className="text-fg underline underline-offset-4">
          Back to sign in
        </Link>
      </p>
    </div>
  );
}
