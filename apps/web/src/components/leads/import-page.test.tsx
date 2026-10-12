import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@freelancer-os/ui";

const GET = vi.fn();
let role: "owner" | "member" = "owner";
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("@/lib/workspace", () => ({
  requireWorkspace: async () => ({
    api: { GET },
    workspaceId: "ws-1",
    workspace: { id: "ws-1", role },
  }),
}));

import ImportLeadsPage from "../../app/(app)/leads/import/page";

const job = {
  id: "j-1",
  filename: "<b>old.csv</b>",
  status: "completed",
  duplicate_strategy: "skip",
  total_rows: 5,
  created_count: 3,
  updated_count: 1,
  skipped_count: 1,
  error_count: 0,
  errors_truncated: false,
  created_at: "2026-10-01T08:30:00Z",
};

async function renderPage() {
  render(<ToastProvider>{await ImportLeadsPage()}</ToastProvider>);
}

beforeEach(() => {
  GET.mockReset();
  role = "owner";
});

describe("Import page", () => {
  it("shows a permission message instead of the wizard for members", async () => {
    role = "member";
    await renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "Import leads" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Only the workspace owner can import leads",
    );
    expect(screen.queryByLabelText("CSV file")).toBeNull();
    expect(GET).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "← Back to leads" })).toHaveAttribute("href", "/leads");
  });

  it("shows the wizard and the recent imports, with an error report link when rows were skipped", async () => {
    GET.mockResolvedValue({ data: { items: [job], total: 1, limit: 10, offset: 0 } });
    await renderPage();
    expect(screen.getByLabelText("CSV file")).toBeInTheDocument();
    expect(GET).toHaveBeenCalledWith(
      "/api/v1/workspaces/{workspace_id}/imports",
      expect.objectContaining({ params: { path: { workspace_id: "ws-1" }, query: { limit: 10 } } }),
    );
    expect(screen.getByText("<b>old.csv</b>")).toBeInTheDocument();
    expect(document.querySelector("b")).toBeNull();
    expect(screen.getByText("2026-10-01 08:30 UTC")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Download error report for/ })).toHaveAttribute(
      "href",
      "/api/v1/workspaces/ws-1/imports/j-1/errors.csv",
    );
  });

  it("hides the report link when nothing was skipped, and copes with no history", async () => {
    GET.mockResolvedValue({
      data: { items: [{ ...job, skipped_count: 0 }], total: 1, limit: 10, offset: 0 },
    });
    await renderPage();
    expect(screen.queryByRole("link", { name: /error report/i })).toBeNull();
  });

  it("says so when there are no imports yet or the history can't load", async () => {
    GET.mockResolvedValue({ data: { items: [], total: 0, limit: 10, offset: 0 } });
    await renderPage();
    expect(screen.getByText(/No imports yet/)).toBeInTheDocument();
  });

  it("still shows the wizard when the history request fails", async () => {
    GET.mockRejectedValue(new Error("down"));
    await renderPage();
    expect(screen.getByLabelText("CSV file")).toBeInTheDocument();
    expect(screen.getByText("Couldn't load your import history")).toBeInTheDocument();
  });
});
