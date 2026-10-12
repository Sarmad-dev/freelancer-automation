"use client";

import { Eye, EyeOff } from "lucide-react";
import { useState } from "react";
import { Button, Input, type FieldControlProps } from "@freelancer-os/ui";

/** Password field with a show/hide toggle (helps people type long passphrases correctly). */
export function PasswordInput({
  controlProps,
  autoComplete,
  name = "password",
}: {
  controlProps: FieldControlProps;
  autoComplete: "current-password" | "new-password";
  name?: string;
}) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="relative">
      <Input
        {...controlProps}
        name={name}
        type={visible ? "text" : "password"}
        autoComplete={autoComplete}
        required
        maxLength={128}
        className="pr-11"
      />
      <Button
        variant="ghost"
        size="icon"
        className="absolute top-0 right-0 text-muted"
        aria-label={visible ? "Hide password" : "Show password"}
        aria-pressed={visible}
        onClick={() => setVisible((v) => !v)}
      >
        {visible ? (
          <EyeOff className="size-4" aria-hidden />
        ) : (
          <Eye className="size-4" aria-hidden />
        )}
      </Button>
    </div>
  );
}
