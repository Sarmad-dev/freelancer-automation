"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Button, Field, Input, Notice } from "@freelancer-os/ui";
import { browserApi, describeRateLimit, toFailure } from "@/lib/api-client";
import { hardNavigate } from "@/lib/navigation";
import { PasswordInput } from "./password-input";

export function SignInForm({
  next,
  notice,
  passwordResetEnabled,
}: {
  /** Already-sanitised destination (see safeNextPath). */
  next: string;
  notice?: "expired" | "reset" | undefined;
  passwordResetEnabled: boolean;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setPending(true);
    setError(null);
    try {
      const {
        data,
        error: apiError,
        response,
      } = await browserApi().POST("/api/v1/auth/sign-in", {
        body: {
          email: String(form.get("email") ?? ""),
          password: String(form.get("password") ?? ""),
        },
      });
      if (data) {
        hardNavigate(next);
        return;
      }
      const failure = toFailure(apiError, response);
      setError(failure.status === 429 ? describeRateLimit(failure) : failure.message);
    } catch {
      setError(toFailure(undefined).message);
    }
    setPending(false);
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate={false}>
      {notice === "expired" ? (
        <Notice tone="warning" title="Your session has ended">
          For your security you&apos;ve been signed out. Sign in again to continue.
        </Notice>
      ) : null}
      {notice === "reset" ? (
        <Notice tone="success" title="Password updated">
          Sign in with your new password.
        </Notice>
      ) : null}
      {error ? (
        <Notice tone="danger" title="Couldn't sign you in">
          {error}
        </Notice>
      ) : null}

      <Field label="Email">
        {(p) => (
          <Input
            {...p}
            name="email"
            type="email"
            autoComplete="username"
            required
            maxLength={254}
          />
        )}
      </Field>
      <Field label="Password">
        {(p) => <PasswordInput controlProps={p} autoComplete="current-password" />}
      </Field>

      <Button type="submit" disabled={pending} aria-busy={pending}>
        {pending ? "Signing in…" : "Sign in"}
      </Button>

      {passwordResetEnabled ? (
        <p className="text-center text-sm">
          <Link
            href="/forgot-password"
            className="text-muted underline underline-offset-4 hover:text-fg"
          >
            Forgot your password?
          </Link>
        </p>
      ) : null}
    </form>
  );
}
