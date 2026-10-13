"use client";

import { ChevronLeft, ChevronRight, Search, X } from "lucide-react";
import type { HTMLAttributes, ReactNode, TdHTMLAttributes, ThHTMLAttributes } from "react";
import { Button } from "./button";
import { cn } from "./cn";
import { Input } from "./field";

/* ---------- Table primitives ---------- */
export function TableContainer({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  // tabIndex makes the scroll region keyboard-scrollable (WCAG 2.1.1).
  return (
    <div
      tabIndex={0}
      className={cn("relative overflow-x-auto rounded-lg border border-line bg-surface", className)}
      {...props}
    />
  );
}
export function Table({ className, ...props }: HTMLAttributes<HTMLTableElement>) {
  return <table className={cn("w-full border-collapse text-sm", className)} {...props} />;
}
export function Th({
  className,
  sort,
  ...props
}: ThHTMLAttributes<HTMLTableCellElement> & { sort?: "ascending" | "descending" | "none" }) {
  return (
    <th
      scope="col"
      {...(sort ? { "aria-sort": sort } : {})}
      className={cn(
        "border-b border-line px-4 py-2.5 text-left text-xs font-medium whitespace-nowrap text-muted",
        className,
      )}
      {...props}
    />
  );
}
export function Td({ className, ...props }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("border-b border-line px-4 py-3 text-fg", className)} {...props} />;
}

/* ---------- Toolbar ---------- */
export function TableToolbar({
  searchLabel = "Search",
  searchPlaceholder = "Search…",
  searchValue,
  onSearchChange,
  filters,
  actions,
  selectedCount = 0,
  bulkActions,
}: {
  searchLabel?: string;
  searchPlaceholder?: string;
  searchValue?: string;
  onSearchChange?: (value: string) => void;
  filters?: ReactNode;
  actions?: ReactNode;
  selectedCount?: number;
  bulkActions?: ReactNode;
}) {
  return (
    <div role="toolbar" aria-label="Table controls" className="flex flex-wrap items-center gap-2">
      <div className="relative min-w-52 flex-1 sm:max-w-xs">
        <Search
          className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-muted"
          aria-hidden
        />
        <Input
          type="search"
          aria-label={searchLabel}
          placeholder={searchPlaceholder}
          className="pl-8"
          {...(searchValue !== undefined ? { value: searchValue } : {})}
          {...(onSearchChange ? { onChange: (e) => onSearchChange(e.target.value) } : {})}
        />
      </div>
      {filters}
      <div className="ml-auto flex items-center gap-2">
        {selectedCount > 0 ? (
          <>
            <span role="status" className="text-sm text-muted">
              {selectedCount} selected
            </span>
            {bulkActions}
          </>
        ) : null}
        {actions}
      </div>
    </div>
  );
}

/* ---------- Filter chips ---------- */
export interface FilterChip {
  id: string;
  label: string;
}

export function FilterChips({
  chips,
  onRemove,
  onClear,
}: {
  chips: FilterChip[];
  onRemove: (id: string) => void;
  onClear?: () => void;
}) {
  if (chips.length === 0) return null;
  return (
    <ul aria-label="Active filters" className="flex flex-wrap items-center gap-2">
      {chips.map((c) => (
        <li key={c.id}>
          <span className="inline-flex items-center gap-1 rounded-full border border-line bg-elevated py-0.5 pr-1 pl-3 text-[13px] text-fg">
            {c.label}
            <button
              type="button"
              aria-label={`Remove filter: ${c.label}`}
              onClick={() => onRemove(c.id)}
              className="flex size-5 items-center justify-center rounded-full text-muted hover:bg-line hover:text-fg"
            >
              <X className="size-3" aria-hidden />
            </button>
          </span>
        </li>
      ))}
      {onClear ? (
        <li>
          <Button variant="ghost" size="sm" onClick={onClear}>
            Clear all
          </Button>
        </li>
      ) : null}
    </ul>
  );
}

/* ---------- Pagination ---------- */
export function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
  noun = "results",
}: {
  /** 1-based current page. */
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  noun?: string;
}) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const current = Math.min(Math.max(1, page), pageCount);
  const from = total === 0 ? 0 : (current - 1) * pageSize + 1;
  const to = Math.min(total, current * pageSize);
  return (
    <nav aria-label="Pagination" className="flex items-center justify-between gap-4 text-sm">
      <p className="text-muted" aria-live="polite">
        {from}–{to} of {total} {noun}
      </p>
      <div className="flex items-center gap-2">
        <span className="text-muted">
          Page {current} of {pageCount}
        </span>
        <Button
          variant="secondary"
          size="icon"
          aria-label="Previous page"
          disabled={current <= 1}
          onClick={() => onPageChange(current - 1)}
        >
          <ChevronLeft className="size-4" aria-hidden />
        </Button>
        <Button
          variant="secondary"
          size="icon"
          aria-label="Next page"
          disabled={current >= pageCount}
          onClick={() => onPageChange(current + 1)}
        >
          <ChevronRight className="size-4" aria-hidden />
        </Button>
      </div>
    </nav>
  );
}
