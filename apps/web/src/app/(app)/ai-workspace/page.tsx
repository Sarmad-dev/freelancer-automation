import type { Metadata } from "next";
import Link from "next/link";
import { Badge, ErrorState, Notice } from "@freelancer-os/ui";
import { requireWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "AI Workspace" };
export const dynamic = "force-dynamic";

const card = "rounded-lg border border-line bg-surface p-5";
const linkButton =
  "inline-flex h-8 items-center rounded-md border border-line bg-elevated px-3 text-[13px] font-medium text-fg hover:brightness-110";

export default async function AiWorkspaceOverview() {
  const { api, workspaceId } = await requireWorkspace();
  const path = { workspace_id: workspaceId };
  const [profile, stats, context] = await Promise.all([
    api.GET("/api/v1/workspaces/{workspace_id}/profile", { params: { path } }),
    api.GET("/api/v1/workspaces/{workspace_id}/knowledge/stats", { params: { path } }),
    api.GET("/api/v1/workspaces/{workspace_id}/ai-context", { params: { path } }),
  ]).catch(() => [null, null, null] as const);

  if (!profile?.data || !stats?.data || !context?.data) {
    return (
      <ErrorState
        title="Couldn't load the AI Workspace"
        description="Your data is safe. Try again in a moment."
      />
    );
  }
  const { completeness } = profile.data;
  const needed = completeness.missing.filter((m) => m.importance === "needed");
  const counts = stats.data;
  const review = (counts.pending_review ?? 0) + (counts.draft ?? 0);

  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-4 md:grid-cols-2">
        <section aria-labelledby="ov-profile" className={card}>
          <div className="flex items-center justify-between gap-3">
            <h2 id="ov-profile" className="text-sm font-medium text-muted">
              Profile
            </h2>
            <Badge tone={needed.length === 0 ? "success" : "warning"}>
              {completeness.filled} of {completeness.total} filled
            </Badge>
          </div>
          {needed.length === 0 ? (
            <p className="mt-3 text-sm text-fg">
              The essentials are filled in. Add the optional details to make drafts sharper.
            </p>
          ) : (
            <p className="mt-3 text-sm text-fg">
              Still needed for good drafts: {needed.map((m) => m.label).join(", ")}.
            </p>
          )}
          <Link href="/ai-workspace/profile" className={`${linkButton} mt-4`}>
            {completeness.filled === 0 ? "Fill in your profile" : "Edit profile"}
          </Link>
        </section>

        <section aria-labelledby="ov-knowledge" className={card}>
          <div className="flex items-center justify-between gap-3">
            <h2 id="ov-knowledge" className="text-sm font-medium text-muted">
              Knowledge
            </h2>
            <Badge tone={review > 0 ? "warning" : "neutral"}>{review} to review</Badge>
          </div>
          <dl className="mt-3 grid grid-cols-3 gap-2 text-sm">
            <div>
              <dt className="text-muted">In use</dt>
              <dd className="text-lg font-semibold text-fg">{counts.in_use ?? 0}</dd>
            </div>
            <div>
              <dt className="text-muted">Switched off</dt>
              <dd className="text-lg font-semibold text-fg">{counts.disabled ?? 0}</dd>
            </div>
            <div>
              <dt className="text-muted">Rejected</dt>
              <dd className="text-lg font-semibold text-fg">{counts.rejected ?? 0}</dd>
            </div>
          </dl>
          <div className="mt-4 flex flex-wrap gap-2">
            <Link href="/ai-workspace/knowledge" className={linkButton}>
              Manage knowledge
            </Link>
            {(counts.pending_review ?? 0) > 0 ? (
              <Link href="/ai-workspace/knowledge?status=pending_review" className={linkButton}>
                Review {counts.pending_review} extracted
              </Link>
            ) : null}
          </div>
        </section>
      </div>

      <section aria-labelledby="ov-ai" className={card}>
        <h2 id="ov-ai" className="text-sm font-medium text-muted">
          What the AI may use
        </h2>
        <p className="mt-2 text-sm text-fg">
          {context.data.facts.length} approved fact{context.data.facts.length === 1 ? "" : "s"} plus
          the profile fields you filled in. Drafts, unreviewed extractions, rejected and
          switched-off items are never used.
        </p>
        <ul className="mt-3 list-disc pl-5 text-sm text-muted">
          {context.data.policy.map((rule) => (
            <li key={rule}>{rule}</li>
          ))}
        </ul>
      </section>

      <Notice tone="info" title="No AI provider is connected yet">
        Nothing here calls a model. Importing reference material just splits your own text into
        statements for you to review. When AI features arrive they will read only what is shown
        above.
      </Notice>
    </div>
  );
}
