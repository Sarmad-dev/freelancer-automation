"use client";

import { useState, type FormEvent } from "react";
import { Button, Field, Input, Notice } from "@freelancer-os/ui";
import { browserApi, describeRateLimit, toFailure } from "@/lib/api-client";
import { hardNavigate } from "@/lib/navigation";
import { PasswordInput } from "./password-input";

export function SignUpForm() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setPending(true);
    setError(null);
    setFields({});
    try {
      const {
        data,
        error: apiError,
        response,
      } = await browserApi().POST("/api/v1/auth/sign-up", {
        body: {
          display_name: String(form.get("display_name") ?? ""),
          email: String(form.get("email") ?? ""),
          password: String(form.get("password") ?? ""),
        },
      });
      if (data) {
        hardNavigate("/onboarding");
        return;
      }
      const failure = toFailure(apiError, response);
      if (Object.keys(failure.fields).length > 0) {
        setFields(failure.fields);
        setError(failure.status === 422 ? null : failure.message);
      } else {
        setError(failure.status === 429 ? describeRateLimit(failure) : failure.message);
      }
    } catch {
      setError(toFailure(undefined).message);
    }
    setPending(false);
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      {error ? (
        <Notice tone="danger" title="Couldn't create your account">
          {error}
        </Notice>
      ) : null}
      <Field label="Your name" {...(fields.display_name ? { error: fields.display_name } : {})}>
        {(p) => <Input {...p} name="display_name" autoComplete="name" required maxLength={120} />}
      </Field>
      <Field label="Email" {...(fields.email ? { error: fields.email } : {})}>
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
      <Field
        label="Password"
        hint="At least 12 characters. A few random words make a strong, memorable passphrase."
        {...(fields.password ? { error: fields.password } : {})}
      >
        {(p) => <PasswordInput controlProps={p} autoComplete="new-password" />}
      </Field>
      <Button type="submit" disabled={pending} aria-busy={pending}>
        {pending ? "Creating account…" : "Create account"}
      </Button>
    </form>
  );
}
