import type { ButtonHTMLAttributes } from "react";
import { cn } from "./cn";

export type ButtonVariant = "primary" | "secondary" | "ghost";

const variants: Record<ButtonVariant, string> = {
  primary: "bg-[var(--fos-accent)] text-[var(--fos-accent-contrast)] hover:brightness-110",
  secondary:
    "bg-[var(--fos-elevated)] text-[var(--fos-text)] border border-[var(--fos-border)] hover:brightness-110",
  ghost: "bg-transparent text-[var(--fos-text)] hover:bg-[var(--fos-elevated)]",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
}

export function Button({ variant = "primary", className, type = "button", ...props }: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex h-9 items-center justify-center gap-2 rounded-[var(--fos-radius-md)] px-4 text-sm font-medium",
        "transition-[filter,background-color] duration-150",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--fos-focus)]",
        "disabled:cursor-not-allowed disabled:opacity-50",
        variants[variant],
        className,
      )}
      {...props}
    />
  );
}
