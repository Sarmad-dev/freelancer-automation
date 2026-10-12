import type { HTMLAttributes } from "react";
import { cn } from "./cn";

/** Loading placeholder. Wrap groups in an element with `aria-busy` and a visible/sr-only label. */
export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden
      className={cn(
        "animate-[fos-pulse_1.6s_ease-in-out_infinite] rounded-md bg-elevated",
        className,
      )}
      {...props}
    />
  );
}

export function TableSkeleton({ rows = 6, columns = 4 }: { rows?: number; columns?: number }) {
  return (
    <div role="status" aria-busy="true" aria-label="Loading" className="flex flex-col gap-2">
      {Array.from({ length: rows }, (_, r) => (
        <div
          key={r}
          className="grid gap-4"
          style={{ gridTemplateColumns: `repeat(${columns}, 1fr)` }}
        >
          {Array.from({ length: columns }, (_, c) => (
            <Skeleton key={c} className="h-8" />
          ))}
        </div>
      ))}
      <span className="sr-only">Loading…</span>
    </div>
  );
}
