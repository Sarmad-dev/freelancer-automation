"use client";

import * as CheckboxPrimitive from "@radix-ui/react-checkbox";
import { Check } from "lucide-react";
import { useId } from "react";
import { cn } from "./cn";

export interface CheckboxProps {
  label: string;
  description?: string;
  checked?: boolean | "indeterminate";
  defaultChecked?: boolean;
  onCheckedChange?: (checked: boolean | "indeterminate") => void;
  disabled?: boolean;
  name?: string;
  className?: string;
}

export function Checkbox({ label, description, className, ...props }: CheckboxProps) {
  const id = useId();
  return (
    <div className={cn("flex items-start gap-3", className)}>
      <CheckboxPrimitive.Root
        id={id}
        aria-describedby={description ? `${id}-desc` : undefined}
        className="mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-sm border border-muted bg-canvas data-[state=checked]:border-accent data-[state=checked]:bg-accent data-[state=indeterminate]:border-accent data-[state=indeterminate]:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
        {...props}
      >
        <CheckboxPrimitive.Indicator className="text-on-accent">
          <Check className="size-3" strokeWidth={3} aria-hidden />
        </CheckboxPrimitive.Indicator>
      </CheckboxPrimitive.Root>
      <div className="flex flex-col">
        <label htmlFor={id} className="text-sm text-fg">
          {label}
        </label>
        {description ? (
          <span id={`${id}-desc`} className="text-[13px] text-muted">
            {description}
          </span>
        ) : null}
      </div>
    </div>
  );
}
