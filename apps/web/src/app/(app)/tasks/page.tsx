import type { Metadata } from "next";
import { ErrorState, Notice, PageHeader } from "@freelancer-os/ui";
import { TasksView } from "@/components/tasks/tasks-view";
import { apiQuery, parseTaskQuery } from "@/components/tasks/task-list-model";
import { requireWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Tasks" };
export const dynamic = "force-dynamic";

export default async function TasksPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = parseTaskQuery(await searchParams);
  const { api, workspaceId, workspace } = await requireWorkspace();
  const path = { workspace_id: workspaceId };

  const load = (tz: string) =>
    Promise.all([
      api.GET("/api/v1/workspaces/{workspace_id}/tasks/summary", {
        params: { path, query: tz ? { tz } : {} },
      }),
      api.GET("/api/v1/workspaces/{workspace_id}/tasks", {
        params: { path, query: apiQuery(query, tz) },
      }),
    ]);

  let usedQuery = query;
  let zoneNotice: string | null = null;
  let results: Awaited<ReturnType<typeof load>> | null = await load(query.tz).catch(() => null);

  // An unknown zone is a 422 from the API: fall back to the workspace's zone and say so.
  if (
    results &&
    query.tz &&
    (results[0].response.status === 422 || results[1].response.status === 422)
  ) {
    results = await load("").catch(() => null);
    usedQuery = { ...query, tz: "" };
    zoneNotice = `"${query.tz}" isn't a time zone we know, so the default is shown instead.`;
  }

  const summary = results?.[0].data;
  const list = results?.[1].data;
  const now = new Date().toISOString();

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Tasks & Calendar"
        description="Follow-ups and reminders for your leads and deals. Calendar events appear only after you connect a calendar; until then this page shows your tasks."
      />
      {!summary || !list ? (
        <ErrorState
          title="Couldn't load your tasks"
          description="Your data is safe. Try again in a moment."
        />
      ) : (
        <>
          {zoneNotice ? (
            <Notice tone="warning" title="Time zone not recognised">
              {`${zoneNotice} Showing today in ${summary.timezone}.`}
            </Notice>
          ) : null}
          <TasksView
            workspaceId={workspaceId}
            tasks={list.items}
            total={list.total}
            summary={summary}
            query={usedQuery}
            now={now}
            canEdit={workspace.role === "owner"}
          />
        </>
      )}
    </div>
  );
}
