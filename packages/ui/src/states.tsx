import { AlertTriangle, Inbox, ShieldAlert } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "./button";
import { cn } from "./cn";

function StateShell({
  icon,
  title,
  description,
  children,
  role,
  className,
  titleAs: Title = "h2",
}: {
  icon: ReactNode;
  title: string;
  titleAs?: "h1" | "h2" | "h3";
  description?: ReactNode;
  children?: ReactNode;
  role?: "alert" | "status";
  className?: string;
}) {
  return (
    <div
      {...(role ? { role } : {})}
      className={cn(
        "flex flex-col items-center gap-3 rounded-lg border border-dashed border-line px-6 py-12 text-center",
        className,
      )}
    >
      <div
        className="flex size-10 items-center justify-center rounded-full bg-elevated text-muted"
        aria-hidden
      >
        {icon}
      </div>
      <Title className="text-base font-semibold text-fg">{title}</Title>
      {description ? <p className="max-w-md text-sm text-muted">{description}</p> : null}
      {children ? <div className="mt-1 flex flex-wrap justify-center gap-2">{children}</div> : null}
    </div>
  );
}

export function EmptyState(props: {
  title: string;
  /** Heading level; use "h1" when the state is the whole page (e.g. 404). */
  titleAs?: "h1" | "h2" | "h3";
  description?: ReactNode;
  icon?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  const { icon, ...rest } = props;
  return <StateShell icon={icon ?? <Inbox className="size-5" />} {...rest} />;
}

export function ErrorState({
  title = "Something went wrong",
  description = "We couldn't load this. Your data is safe. Try again, and if it keeps failing, check the system status on Home.",
  onRetry,
  detail,
}: {
  title?: string;
  description?: ReactNode;
  onRetry?: () => void;
  /** Non-sensitive reference (e.g. an error digest) to quote to support. */
  detail?: string;
}) {
  return (
    <StateShell
      role="alert"
      icon={<AlertTriangle className="size-5 text-danger" />}
      title={title}
      description={
        <>
          {description}
          {detail ? <span className="mt-2 block text-xs">Reference: {detail}</span> : null}
        </>
      }
    >
      {onRetry ? (
        <Button variant="secondary" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </StateShell>
  );
}

export function PermissionDeniedState({
  title = "You don't have access to this",
  description = "Ask the workspace owner to grant you access, or switch to a workspace where you have permission.",
  children,
}: {
  title?: string;
  description?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <StateShell
      role="alert"
      icon={<ShieldAlert className="size-5 text-warning" />}
      title={title}
      description={description}
    >
      {children}
    </StateShell>
  );
}

/** Honest placeholder for a destination whose feature ships in a later phase. */
export function PlannedFeature({
  title,
  description,
  phase,
}: {
  title: string;
  description: string;
  phase: string;
}) {
  return (
    <EmptyState title={title} description={description}>
      <span className="text-[13px] text-muted">
        Planned: {phase}. Nothing here is functional yet.
      </span>
    </EmptyState>
  );
}

const noticeTones = {
  info: "border-info/40 bg-info/10",
  warning: "border-warning/40 bg-warning/10",
  danger: "border-danger/40 bg-danger/10",
  success: "border-success/40 bg-success/10",
} as const;

/** Inline banner for page-level context ("preview only", partial outages, success summaries). */
export function Notice({
  tone = "info",
  title,
  children,
}: {
  tone?: keyof typeof noticeTones;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div
      role={tone === "danger" || tone === "warning" ? "alert" : "status"}
      className={cn("rounded-md border p-3 text-sm", noticeTones[tone])}
    >
      <p className="font-medium text-fg">{title}</p>
      {children ? <div className="mt-0.5 text-muted">{children}</div> : null}
    </div>
  );
}
