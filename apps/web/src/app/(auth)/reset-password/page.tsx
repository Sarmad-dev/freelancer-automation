import type { Metadata } from "next";
import Link from "next/link";
import { Notice } from "@freelancer-os/ui";
import { AuthHeading } from "@/components/auth/auth-frame";
import { ResetPasswordForm } from "@/components/auth/password-reset-forms";

export const metadata: Metadata = { title: "Choose a new password", referrer: "no-referrer" };

export default async function ResetPasswordPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token } = await searchParams;
  return (
    <div className="flex flex-col gap-6">
      <AuthHeading title="Choose a new password" description="Pick something long and unique." />
      {token ? (
        <ResetPasswordForm token={token} />
      ) : (
        <Notice tone="warning" title="This reset link is incomplete">
          Open the link from your email again, or request a new one.
        </Notice>
      )}
      <p className="text-center text-sm">
        <Link href="/forgot-password" className="text-fg underline underline-offset-4">
          Request a new link
        </Link>
      </p>
    </div>
  );
}
