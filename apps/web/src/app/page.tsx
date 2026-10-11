import { Button } from "@freelancer-os/ui";
import { fetchApiStatus, type ApiStatus } from "@/lib/api-status";
import { getEnv } from "@/env";

export const dynamic = "force-dynamic";

const LABELS: Record<ApiStatus["state"], { text: string; tone: string }> = {
  ready: { text: "Connected", tone: "text-success" },
  degraded: { text: "Degraded", tone: "text-warning" },
  unreachable: { text: "Unreachable", tone: "text-danger" },
};

export default async function Home() {
  const env = getEnv();
  const status = await fetchApiStatus(env.API_URL);
  const label = LABELS[status.state];

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-8 px-6 py-16">
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold tracking-tight">{env.NEXT_PUBLIC_APP_NAME}</h1>
        <p className="text-muted">
          Development scaffold. Product features arrive in later phases; this page only verifies
          that the web app can reach the API.
        </p>
      </header>

      <section
        aria-labelledby="api-status"
        className="rounded-[var(--fos-radius-lg)] border border-line bg-surface p-6"
      >
        <h2 id="api-status" className="text-sm font-medium text-muted">
          API connectivity
        </h2>
        <p className={`mt-2 text-lg font-medium ${label.tone}`} role="status">
          {label.text}
        </p>
        {status.state === "unreachable" ? (
          <p className="mt-2 text-sm text-muted">
            {status.reason}. Start the API with <code>pnpm dev:api</code> and check{" "}
            <code>API_URL</code>.
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
        <form action="/" className="mt-4">
          <Button type="submit" variant="secondary">
            Re-check
          </Button>
        </form>
      </section>
    </main>
  );
}
