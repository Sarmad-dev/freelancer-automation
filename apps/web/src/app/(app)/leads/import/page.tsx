import type { Metadata } from "next";
import Link from "next/link";
import {
  Notice,
  PageHeader,
  PermissionDeniedState,
  Table,
  TableContainer,
  Td,
  Th,
} from "@freelancer-os/ui";
import { ImportWizard } from "@/components/leads/import-wizard";
import { errorReportHref, hasErrorReport } from "@/components/leads/import-model";
import { formatDateTime } from "@/components/leads/lead-model";
import { requireWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Import leads" };
export const dynamic = "force-dynamic";

const linkClass =
  "inline-flex h-9 items-center rounded-md border border-line bg-elevated px-3 text-sm font-medium text-fg";

export default async function ImportLeadsPage() {
  const { api, workspaceId, workspace } = await requireWorkspace();
  const header = (
    <PageHeader
      title="Import leads"
      description="Bring in people and companies from a CSV file. You check everything before anything is saved."
      actions={
        <Link href="/leads" className={linkClass}>
          ← Back to leads
        </Link>
      }
    />
  );

  if (workspace.role !== "owner") {
    return (
      <div className="flex flex-col gap-6">
        {header}
        <PermissionDeniedState
          title="Only the workspace owner can import leads"
          description="Ask the owner of this workspace to import the file, or add the leads one by one."
        />
      </div>
    );
  }

  const history = await api
    .GET("/api/v1/workspaces/{workspace_id}/imports", {
      params: { path: { workspace_id: workspaceId }, query: { limit: 10 } },
    })
    .catch(() => null);
  const jobs = history?.data?.items ?? null;

  return (
    <div className="flex flex-col gap-6">
      {header}
      <ImportWizard workspaceId={workspaceId} />
      <section aria-labelledby="import-history-heading" className="flex flex-col gap-3">
        <h2 id="import-history-heading" className="text-lg font-semibold text-fg">
          Recent imports
        </h2>
        {jobs === null ? (
          <Notice tone="warning" title="Couldn't load your import history">
            Your data is safe. Reload the page to try again.
          </Notice>
        ) : jobs.length === 0 ? (
          <p className="text-sm text-muted">
            No imports yet. Your finished imports will show here.
          </p>
        ) : (
          <TableContainer>
            <Table>
              <caption className="sr-only">Your {jobs.length} most recent imports</caption>
              <thead>
                <tr>
                  <Th>File</Th>
                  <Th>Date</Th>
                  <Th>Created</Th>
                  <Th>Updated</Th>
                  <Th>Skipped duplicates</Th>
                  <Th>Rows with problems</Th>
                  <Th>
                    <span className="sr-only">Error report</span>
                  </Th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <tr key={job.id}>
                    <Td className="max-w-xs font-medium break-words">{job.filename}</Td>
                    <Td className="whitespace-nowrap text-muted">
                      <time dateTime={job.created_at}>{formatDateTime(job.created_at)}</time>
                    </Td>
                    <Td>{job.created_count}</Td>
                    <Td>{job.updated_count}</Td>
                    <Td>{job.skipped_count}</Td>
                    <Td>{job.error_count}</Td>
                    <Td className="whitespace-nowrap">
                      {hasErrorReport(job) ? (
                        <a
                          href={errorReportHref(workspaceId, job.id)}
                          download
                          aria-label={`Download error report for ${job.filename}`}
                          className="underline underline-offset-4"
                        >
                          Download error report
                        </a>
                      ) : null}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </TableContainer>
        )}
      </section>
    </div>
  );
}
