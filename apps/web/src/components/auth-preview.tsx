import Link from "next/link";
import type { ReactNode } from "react";
import { Button, Field, Input, Notice } from "@freelancer-os/ui";

export function AuthCard({
  title,
  description,
  children,
  footer,
}: {
  title: string;
  description: string;
  children: ReactNode;
  footer: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-fg">{title}</h1>
        <p className="mt-1 text-sm text-muted">{description}</p>
      </div>
      <Notice tone="info" title="Preview only">
        Accounts and sign-in are built in the authentication phase. These fields are disabled so
        nothing here is mistaken for a working form.
      </Notice>
      {children}
      <p className="text-center text-sm text-muted">{footer}</p>
      <p className="text-center text-sm">
        <Link href="/" className="text-fg underline underline-offset-4">
          Explore the app shell without an account
        </Link>
      </p>
    </div>
  );
}

export function CredentialFields({ withName = false }: { withName?: boolean }) {
  return (
    <form
      className="flex flex-col gap-4"
      aria-label={withName ? "Sign up (preview)" : "Sign in (preview)"}
    >
      <fieldset disabled className="flex flex-col gap-4">
        <legend className="sr-only">Account details</legend>
        {withName ? (
          <Field label="Full name">{(p) => <Input {...p} autoComplete="name" />}</Field>
        ) : null}
        <Field label="Email">
          {(p) => <Input {...p} type="email" autoComplete="email" placeholder="you@example.com" />}
        </Field>
        <Field label="Password" hint={withName ? "At least 12 characters." : undefined}>
          {(p) => (
            <Input
              {...p}
              type="password"
              autoComplete={withName ? "new-password" : "current-password"}
            />
          )}
        </Field>
        <Button type="submit">{withName ? "Create account" : "Sign in"}</Button>
      </fieldset>
    </form>
  );
}
