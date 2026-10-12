import type { ButtonHTMLAttributes } from "react";
import { cn } from "./cn";

export interface SwitchProps extends Omit<
  ButtonHTMLAttributes<HTMLButtonElement>,
  "onChange" | "role" | "aria-checked"
> {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  /** Accessible name. Required: a switch has no visible text of its own. */
  label: string;
}

/** On/off switch (`role="switch"`). State is conveyed by `aria-checked`, a position change and the knob, not by colour alone. */
export function Switch({
  checked,
  onCheckedChange,
  label,
  className,
  disabled,
  ...props
}: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors",
        checked ? "border-accent bg-accent" : "border-muted bg-elevated",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    >
      <span
        aria-hidden
        className={cn(
          "block size-3.5 rounded-full transition-transform",
          checked ? "translate-x-[18px] bg-on-accent" : "translate-x-[3px] bg-muted",
        )}
      />
    </button>
  );
}
