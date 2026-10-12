"use client";

import { useState, type FormEvent } from "react";
import { Button, Field, Input, Notice } from "@freelancer-os/ui";
import { browserApi, describeRateLimit, toFailure } from "@/lib/api-client";
import { hardNavigate } from "@/lib/navigation";
import { PasswordInput } from "./password-input";

export function ForgotPasswordForm() {
  const [pending, setPending] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setPending(true);
    setError(null);
    try {
      const { response, error: apiError } = await browserApi().POST(
        "/api/v1/auth/password-reset/request",
        {
          body: { email: String(form.get("email") ?? "") },
        },
      );
      if (response.ok) setDone(true);
      else {
        const f = toFailure(apiError, response);
        setError(f.status === 429 ? describeRateLimit(f) : f.message);
      }
    } catch {
      setError(toFailure(undefined).message);
    }
    setPending(false);
  }

  if (done) {
    return (
      <Notice tone="success" title="Check your email">
        If an account exists for that address, we&apos;ve sent a link to reset the password. It
        expires in an hour.
      </Notice>
    );
  }
  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      {error ? (
        <Notice tone="danger" title="Couldn't send the link">
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
      <Button type="submit" disabled={pending} aria-busy={pending}>
        {pending ? "Sending…" : "Send reset link"}
      </Button>
    </form>
  );
}

export function ResetPasswordForm({ token }: { token: string }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | undefined>();

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setPending(true);
    setError(null);
    setPasswordError(undefined);
    try {
      const { response, error: apiError } = await browserApi().POST(
        "/api/v1/auth/password-reset/confirm",
        {
          body: { token, password: String(form.get("password") ?? "") },
        },
      );
      if (response.ok) {
        hardNavigate("/sign-in?reset=1");
        return;
      }
      const f = toFailure(apiError, response);
      if (f.fields.password) setPasswordError(f.fields.password);
      else setError(f.status === 429 ? describeRateLimit(f) : f.message);
    } catch {
      setError(toFailure(undefined).message);
    }
    setPending(false);
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      {error ? (
        <Notice tone="danger" title="Couldn't reset your password">
          {error}
        </Notice>
      ) : null}
      <Field
        label="New password"
        hint="At least 12 characters. You'll be signed out everywhere."
        {...(passwordError ? { error: passwordError } : {})}
      >
        {(p) => <PasswordInput controlProps={p} autoComplete="new-password" />}
      </Field>
      <Button type="submit" disabled={pending} aria-busy={pending}>
        {pending ? "Saving…" : "Set new password"}
      </Button>
    </form>
  );
}
