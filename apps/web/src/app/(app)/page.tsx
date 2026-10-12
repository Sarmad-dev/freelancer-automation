import type { Metadata } from "next";
import Link from "next/link";
import { Badge, EmptyState, PageHeader } from "@freelancer-os/ui";
import { getEnv } from "@/env";
import { fetchApiStatus, type ApiStatus } from "@/lib/api-status";

export const metadata: Metadata = { title: "Home" };
export const dynamic = "force-dynamic";

const STATUS: Record<ApiStatus["state"], { text: string; tone: "success" | "warning" | "danger" }> =
  {
    ready: { text: "Connected", tone: "success" },
    degraded: { text: "Degraded", tone: "warning" },
    unreachable: { text: "Unreachable", tone: "danger" },
  };

export default async function HomePage() {
  const env = getEnv();
  const status = await fetchApiStatus(env.API_URL);
  const label = STATUS[status.state];

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        title={`Welcome to ${env.NEXT_PUBLIC_APP_NAME}`}
        description="Your overview of next actions, follow-ups and activity will live here."
      />

      <div className="grid gap-6 lg:grid-cols-3">
        <section
          aria-labelledby="next-actions"
          className="rounded-lg border border-line bg-surface p-6 lg:col-span-2"
        >
          <h2 id="next-actions" className="text-sm font-medium text-muted">
            Recommended next actions
          </h2>
          <EmptyState
            className="mt-4"
            title="Nothing to do yet"
            description="Once you add leads and tasks, overdue follow-ups, pending approvals and promising leads show up here."
          >
            <Link
              href="/leads"
              className="inline-flex h-9 items-center rounded-md border border-line bg-elevated px-4 text-sm font-medium text-fg hover:brightness-110"
            >
              Preview Leads
            </Link>
          </EmptyState>
        </section>

        <section
          aria-labelledby="api-status"
          className="rounded-lg border border-line bg-surface p-6"
        >
          <div className="flex items-center justify-between gap-3">
            <h2 id="api-status" className="text-sm font-medium text-muted">
              System status
            </h2>
            <Badge tone={label.tone}>{label.text}</Badge>
          </div>
          {status.state === "unreachable" ? (
            <p role="status" className="mt-3 text-sm text-muted">
              API: {status.reason}. Start it with <code className="text-fg">pnpm dev:api</code> and
              check <code className="text-fg">API_URL</code>.
            </p>
          ) : (
            <ul className="mt-3 divide-y divide-line text-sm">
              {Object.entries(status.checks).map(([name, check]) => (
                <li key={name} className="flex justify-between py-2">
                  <span className="capitalize">{name}</span>
                  <span className={check.status === "ok" ? "text-success" : "text-danger"}>
                    {check.status === "ok"
                      ? "OK"
                      : `Error${check.detail ? ` (${check.detail})` : ""}`}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
