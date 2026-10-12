import {
  forwardRef,
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { cn } from "./cn";

const control =
  "w-full rounded-md border border-line bg-canvas px-3 text-sm text-fg placeholder:text-muted " +
  "transition-colors hover:border-muted disabled:cursor-not-allowed disabled:opacity-50 " +
  "aria-[invalid=true]:border-danger";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...props }, ref) {
    return <input ref={ref} className={cn(control, "h-9", className)} {...props} />;
  },
);

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea({ className, ...props }, ref) {
  return <textarea ref={ref} className={cn(control, "min-h-24 py-2", className)} {...props} />;
});

/** Native `<select>`: best keyboard and screen-reader support, styled to match. */
export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className, children, ...props }, ref) {
    return (
      <select ref={ref} className={cn(control, "h-9 appearance-none pr-8", className)} {...props}>
        {children}
      </select>
    );
  },
);

export interface FieldControlProps {
  id: string;
  "aria-describedby"?: string;
  "aria-invalid"?: true;
}

/** Label + hint + error wiring. Pass the control via render prop to get the right ids/aria. */
export function Field({
  label,
  hint,
  error,
  required,
  children,
  className,
}: {
  label: string;
  hint?: string;
  error?: string;
  required?: boolean;
  className?: string;
  children: (props: FieldControlProps) => ReactNode;
}) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ");
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={id} className="text-sm font-medium text-fg">
        {label}
        {required ? <span className="text-muted"> (required)</span> : null}
      </label>
      {children({
        id,
        ...(describedBy ? { "aria-describedby": describedBy } : {}),
        ...(error ? { "aria-invalid": true as const } : {}),
      })}
      {hint ? (
        <p id={hintId} className="text-[13px] text-muted">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className="text-[13px] text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}
