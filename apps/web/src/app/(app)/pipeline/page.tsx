import type { Metadata } from "next";
import Link from "next/link";
import { ErrorState, PageHeader } from "@freelancer-os/ui";
import { PipelineBoard } from "@/components/pipeline/pipeline-board";
import { NewDealButton } from "@/components/pipeline/opportunity-create-drawer";
import {
  apiQuery,
  parsePipelineQuery,
  parseView,
  type PipelineView,
} from "@/components/pipeline/pipeline-list-model";
import { PipelineTable } from "@/components/pipeline/pipeline-table";
import { requireWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Pipeline" };
export const dynamic = "force-dynamic";

const segment =
  "inline-flex h-8 items-center rounded-[5px] px-3 text-[13px] font-medium aria-[current=page]:bg-elevated aria-[current=page]:text-fg aria-[current=page]:shadow-sm text-muted hover:text-fg";

function ViewSwitch({ view }: { view: PipelineView }) {
  return (
    <nav aria-label="Pipeline view" className="w-fit">
      <div className="inline-flex gap-0.5 rounded-md border border-line bg-surface p-0.5">
        <Link
          href="/pipeline?view=board"
          className={segment}
          {...(view === "board" ? { "aria-current": "page" as const } : {})}
        >
          Board
        </Link>
        <Link
          href="/pipeline?view=table"
          className={segment}
          {...(view === "table" ? { "aria-current": "page" as const } : {})}
        >
          Table
        </Link>
      </div>
    </nav>
  );
}

export default async function PipelinePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const view = parseView(params);
  const query = parsePipelineQuery(params);
  const { api, workspaceId, workspace } = await requireWorkspace();
  const canEdit = workspace.role === "owner";
  const path = { workspace_id: workspaceId };
  // Worked out here, once, so the server render and the browser agree on what "overdue" means.
  const today = new Date().toISOString().slice(0, 10);

  const header = (stages: Parameters<typeof NewDealButton>[0]["stages"] | null) => (
    <PageHeader
      title="Pipeline"
      description="Deals are your opportunities. Add one from a lead."
      actions={
        canEdit && stages ? <NewDealButton workspaceId={workspaceId} stages={stages} /> : undefined
      }
    />
  );

  if (view === "table") {
    const [list, stages] = await Promise.all([
      api.GET("/api/v1/workspaces/{workspace_id}/opportunities", {
        params: { path, query: apiQuery(query) },
      }),
      api.GET("/api/v1/workspaces/{workspace_id}/pipeline/stages", { params: { path } }),
    ]).catch(() => [null, null] as const);

    return (
      <div className="flex flex-col gap-6">
        {header(stages?.data?.items ?? null)}
        <ViewSwitch view={view} />
        {list?.data && stages?.data ? (
          <PipelineTable
            workspaceId={workspaceId}
            deals={list.data.items}
            total={list.data.total}
            query={query}
            stages={stages.data.items}
            today={today}
            canEdit={canEdit}
          />
        ) : (
          <ErrorState
            title="Couldn't load your deals"
            description="Your data is safe. Try again in a moment."
          />
        )}
      </div>
    );
  }

  const board = await api
    .GET("/api/v1/workspaces/{workspace_id}/pipeline/board", { params: { path } })
    .catch(() => null);

  return (
    <div className="flex flex-col gap-6">
      {header(board?.data ? board.data.columns.map((c) => c.stage) : null)}
      <ViewSwitch view={view} />
      {board?.data ? (
        <PipelineBoard
          workspaceId={workspaceId}
          board={board.data}
          today={today}
          canEdit={canEdit}
        />
      ) : (
        <ErrorState
          title="Couldn't load your pipeline"
          description="Your data is safe. Try again in a moment."
        />
      )}
    </div>
  );
}
