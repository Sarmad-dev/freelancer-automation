import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import type * as ApiClient from "@/lib/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@freelancer-os/ui";
import { ImportWizard } from "./import-wizard";
import type { ImportJobOut, ImportPreview } from "./lead-model";

type ApiClientModule = typeof ApiClient;
const refresh = vi.fn();
const redirectToSignIn = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/lib/api-client", async (orig) => {
  const mod = await orig<ApiClientModule>();
  return { ...mod, redirectToSignIn: (...a: unknown[]) => redirectToSignIn(...a) };
});

const WS = "22222222-2222-4222-8222-222222222222";
const JOB_ID = "33333333-3333-4333-8333-333333333333";
const CSV =
  "Full name,E-mail,Org,Notes\nAda Example,ada@acme.example,Acme Example,Hello\nSam Sample,sam@x.example,X Example,Hi\n";

function previewOut(over: Partial<ImportPreview> = {}): ImportPreview {
  const suggested = { name: "Full name", email: "E-mail", company: "Org", notes: "Notes" };
  return {
    delimiter: ",",
    headers: ["Full name", "E-mail", "Org", "Notes"],
    suggested_mapping: suggested,
    mapping: suggested,
    mapping_problem: null,
    total_rows: 2,
    counts: { create: 2, update: 0, skip_duplicate: 0, error: 0 },
    suppressed: 0,
    rows: [
      {
        row: 2,
        action: "create",
        values: { name: "Ada Example", email: "ada@acme.example", company: "Acme Example" },
        issues: [],
        warnings: [],
        note: null,
      },
      {
        row: 3,
        action: "create",
        values: { name: "Sam Sample", email: "sam@x.example", company: "X Example" },
        issues: [],
        warnings: [],
        note: null,
      },
    ],
    errors: [],
    errors_truncated: false,
    ...over,
  };
}

function jobOut(over: Partial<ImportJobOut> = {}): ImportJobOut {
  return {
    id: JOB_ID,
    filename: "leads.csv",
    status: "completed",
    duplicate_strategy: "skip",
    total_rows: 2,
    created_count: 2,
    updated_count: 0,
    skipped_count: 0,
    error_count: 0,
    errors_truncated: false,
    suppressed: 0,
    created_at: "2026-10-12T09:00:00Z",
    ...over,
  };
}

function errorJson(
  status: number,
  code: string,
  message: string,
  fields: Record<string, string> = {},
) {
  return Response.json({ error: { code, message, fields } }, { status });
}

type Call = { method: string; path: string; body: Record<string, unknown> | undefined };
function stubApi(handlers: Record<string, (call: Call) => Response | Promise<Response>> = {}) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (req: Request) => {
      const path = new URL(req.url).pathname.replace(/^\/api\/v1\/workspaces\/[^/]+/, "");
      const text = await req.clone().text();
      const call: Call = { method: req.method, path, body: text ? JSON.parse(text) : undefined };
      calls.push(call);
      const handler = handlers[`${req.method} ${path}`];
      if (handler) return handler(call);
      if (req.method === "POST" && path === "/imports/preview") return Response.json(previewOut());
      if (req.method === "POST" && path === "/imports")
        return Response.json(jobOut(), { status: 201 });
      return errorJson(404, "not_found", "Not found.");
    }),
  );
  return calls;
}

function renderWizard() {
  return render(
    <ToastProvider>
      <ImportWizard workspaceId={WS} />
    </ToastProvider>,
  );
}

function csvFile(text = CSV, name = "leads.csv") {
  return new File([text], name, { type: "text/csv" });
}

async function upload(user: ReturnType<typeof userEvent.setup>, file = csvFile()) {
  await user.upload(screen.getByLabelText("CSV file"), file);
}

async function reachMap(user: ReturnType<typeof userEvent.setup>) {
  await upload(user);
  return screen.findByRole("heading", { name: "Match your columns" });
}

async function reachReview(user: ReturnType<typeof userEvent.setup>) {
  await reachMap(user);
  await user.click(screen.getByRole("button", { name: "Continue" }));
  return screen.findByRole("heading", { name: "Review before importing" });
}

async function noViolations(container: Element) {
  const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  expect(results.violations).toEqual([]);
}

beforeEach(() => {
  vi.unstubAllGlobals();
  refresh.mockClear();
  redirectToSignIn.mockClear();
});

describe("ImportWizard: upload", () => {
  it("rejects a file over 2 MB before any request", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderWizard();
    await upload(user, csvFile("a".repeat(3_400_000)));
    expect(await screen.findByText("That file is 3.4 MB; the limit is 2 MB.")).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it("rejects an empty file before any request", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderWizard();
    await upload(user, csvFile("   \n"));
    expect(await screen.findByText(/That file is empty/)).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it("explains nothing is fetched and offers a sample file", () => {
    renderWizard();
    expect(screen.getByText(/Nothing is fetched from the web/)).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Download a sample CSV" });
    expect(link).toHaveAttribute("download", "sample-leads.csv");
    expect(link.getAttribute("href")).toMatch(/^data:text\/csv/);
    expect(screen.getByLabelText("CSV file")).toHaveAttribute("accept", ".csv,text/csv,text/plain");
  });

  it("previews with the file text and no mapping, then shows the map step", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderWizard();
    await reachMap(user);
    expect(calls).toHaveLength(1);
    expect(calls[0]!.path).toBe("/imports/preview");
    expect(calls[0]!.body).toEqual({ content: CSV, duplicate_strategy: "skip" });
    expect(screen.getByRole("heading", { name: "Match your columns" })).toHaveFocus();
    expect(screen.getByRole("listitem", { current: "step" })).toHaveTextContent("Map columns");
  });

  it("shows the API's message for an unusable file", async () => {
    const user = userEvent.setup();
    stubApi({
      "POST /imports/preview": () =>
        errorJson(422, "invalid_csv", "The file has a header but no data rows.", {
          content: "The file has a header but no data rows.",
        }),
    });
    renderWizard();
    await upload(user);
    expect(await screen.findByText("The file has a header but no data rows.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Choose a CSV file" })).toBeInTheDocument();
  });

  it("shows a message when the owner-only API refuses (403)", async () => {
    const user = userEvent.setup();
    stubApi({
      "POST /imports/preview": () =>
        errorJson(403, "forbidden", "Only the workspace owner can do this."),
    });
    renderWizard();
    await upload(user);
    expect(await screen.findByText("Only the workspace owner can do this.")).toBeInTheDocument();
  });

  it("sends the user to sign-in when the session expired", async () => {
    const user = userEvent.setup();
    stubApi({
      "POST /imports/preview": () => errorJson(401, "session_expired", "Please sign in again."),
    });
    renderWizard();
    await upload(user);
    await waitFor(() => expect(redirectToSignIn).toHaveBeenCalledWith("expired"));
  });
});

describe("ImportWizard: map columns", () => {
  it("pre-fills from the suggested mapping and shows sample values", async () => {
    const user = userEvent.setup();
    stubApi();
    renderWizard();
    await reachMap(user);
    expect(screen.getByLabelText("Contact name")).toHaveValue("Full name");
    expect(screen.getByLabelText("Email")).toHaveValue("E-mail");
    expect(screen.getByLabelText("Phone")).toHaveValue("");
    expect(screen.getByText(/First rows: “Ada Example” · “Sam Sample”/)).toBeInTheDocument();
    expect(screen.getByText(/Map at least one of name, email or company/)).toBeInTheDocument();
  });

  it("re-previews with the new mapping on Continue", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderWizard();
    await reachMap(user);
    await user.selectOptions(screen.getByLabelText("Phone"), "Notes");
    await user.selectOptions(screen.getByLabelText("Notes"), "");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Review before importing" });
    const body = calls[1]!.body as { mapping: Record<string, string | null> };
    expect(body.mapping.phone).toBe("Notes");
    expect(body.mapping.notes).toBeNull();
    expect(body.mapping.name).toBe("Full name");
  });

  it("blocks a column used for two fields", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderWizard();
    await reachMap(user);
    await user.selectOptions(screen.getByLabelText("Phone"), "E-mail");
    expect(screen.getByText(/already used for “Email”/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    expect(calls).toHaveLength(1);
  });

  it("requires one of name, email or company", async () => {
    const user = userEvent.setup();
    stubApi();
    renderWizard();
    await reachMap(user);
    for (const label of ["Contact name", "Email", "Company"]) {
      await user.selectOptions(screen.getByLabelText(label), "");
    }
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    expect(screen.getByText("Map at least one of name, email or company")).toBeInTheDocument();
  });

  it("shows mapping_problem as an alert and stays on the step", async () => {
    const user = userEvent.setup();
    stubApi({
      "POST /imports/preview": (call) =>
        Response.json(
          call.body?.mapping
            ? previewOut({ mapping_problem: "Map at least one of name, email or company." })
            : previewOut(),
        ),
    });
    renderWizard();
    await reachMap(user);
    await user.click(screen.getByRole("button", { name: "Continue" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Map at least one of name, email or company.");
    expect(screen.getByRole("heading", { name: "Match your columns" })).toBeInTheDocument();
  });

  it("goes back to the upload step and can continue with the same file", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderWizard();
    await reachMap(user);
    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByRole("heading", { name: "Choose a CSV file" })).toHaveFocus();
    expect(screen.getByText("leads.csv")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Continue with this file" }));
    expect(screen.getByRole("heading", { name: "Match your columns" })).toBeInTheDocument();
    expect(calls).toHaveLength(1);
  });
});

describe("ImportWizard: review", () => {
  it("shows counts as words, the rows and the problems", async () => {
    const user = userEvent.setup();
    stubApi({
      "POST /imports/preview": (call) =>
        Response.json(
          call.body?.mapping
            ? previewOut({
                total_rows: 30,
                counts: { create: 12, update: 3, skip_duplicate: 2, error: 1 },
                rows: [
                  {
                    row: 2,
                    action: "update",
                    values: { name: "Ada Example" },
                    issues: [],
                    warnings: ["Phone looks short"],
                    note: "Matches an existing contact",
                  },
                  {
                    row: 3,
                    action: "error",
                    values: { email: "nope" },
                    issues: ["Email is not valid"],
                    warnings: [],
                    note: null,
                  },
                  {
                    row: 4,
                    action: "skip_duplicate",
                    values: { email: "dup@x.example" },
                    issues: [],
                    warnings: [],
                    note: null,
                  },
                ],
                errors: [
                  {
                    row: 3,
                    column: "E-mail",
                    message: "Not a valid email",
                    value: "nope",
                    kind: "error",
                  },
                  {
                    row: 4,
                    column: "E-mail",
                    message: "Already exists",
                    value: "dup@x.example",
                    kind: "skipped",
                  },
                ],
                errors_truncated: true,
              })
            : previewOut(),
        ),
    });
    renderWizard();
    await reachReview(user);
    const summary = screen.getByTestId("import-summary");
    expect(summary).toHaveTextContent("12 will be created");
    expect(summary).toHaveTextContent("3 will update");
    expect(summary).toHaveTextContent("2 duplicates skipped");
    expect(summary).toHaveTextContent("1 row has a problem");
    const rows = screen.getAllByRole("row");
    expect(within(rows[1]!).getByText("Will update")).toBeInTheDocument();
    expect(within(rows[1]!).getByText(/Heads up:/)).toBeInTheDocument();
    expect(within(rows[1]!).getByText("Matches an existing contact")).toBeInTheDocument();
    expect(within(rows[2]!).getByText("Has a problem")).toBeInTheDocument();
    expect(within(rows[2]!).getByText("Email is not valid")).toBeInTheDocument();
    expect(within(rows[3]!).getByText("Duplicate, skipped")).toBeInTheDocument();
    expect(screen.getByText("Not a valid email")).toBeInTheDocument();
    expect(screen.getByText("Skipped duplicate")).toBeInTheDocument();
    expect(screen.getByText(/Showing the first 2 problems/)).toBeInTheDocument();
    expect(screen.getByText("Showing the first 3 of 30 rows.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import 15 leads" })).toBeEnabled();
  });

  it("warns about rows on the do-not-contact list", async () => {
    const user = userEvent.setup();
    stubApi({
      "POST /imports/preview": (call) =>
        Response.json(call.body?.mapping ? previewOut({ suppressed: 3 }) : previewOut()),
    });
    renderWizard();
    await reachReview(user);
    expect(
      screen.getByText(
        "3 rows are on your do-not-contact list: they will be imported but never emailed.",
      ),
    ).toBeInTheDocument();
  });

  it("re-previews when the duplicate strategy changes", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderWizard();
    await reachReview(user);
    expect(screen.getByRole("radio", { name: /Skip duplicates/ })).toBeChecked();
    expect(screen.getByText(/never erase anything/)).toBeInTheDocument();
    expect(screen.getByText(/A row is a duplicate when its email matches/)).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: /Update existing records/ }));
    await waitFor(() => expect(calls).toHaveLength(3));
    expect(calls[2]!.body).toMatchObject({ duplicate_strategy: "update" });
    expect((calls[2]!.body as { mapping: { email: string } }).mapping.email).toBe("E-mail");
    await waitFor(() =>
      expect(screen.getByRole("radio", { name: /Update existing records/ })).toBeChecked(),
    );
  });

  it("disables the import button and says why when nothing would change", async () => {
    const user = userEvent.setup();
    stubApi({
      "POST /imports/preview": (call) =>
        Response.json(
          call.body?.mapping
            ? previewOut({
                counts: { create: 0, update: 0, skip_duplicate: 2, error: 0 },
                rows: [],
              })
            : previewOut(),
        ),
    });
    renderWizard();
    await reachReview(user);
    expect(screen.getByRole("button", { name: "Import 0 leads" })).toBeDisabled();
    expect(screen.getByText("Nothing to import")).toBeInTheDocument();
    expect(screen.getByText(/Choose “Update existing records”/)).toBeInTheDocument();
  });

  it("keeps the file and choices when the import fails", async () => {
    const user = userEvent.setup();
    stubApi({
      "POST /imports": () => errorJson(500, "internal", "The service is temporarily unavailable."),
    });
    renderWizard();
    await reachReview(user);
    await user.click(screen.getByRole("button", { name: "Import 2 leads" }));
    expect(await screen.findByText("The import didn't run")).toBeInTheDocument();
    expect(screen.getByText(/The service is temporarily unavailable/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import 2 leads" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByLabelText("Contact name")).toHaveValue("Full name");
  });
});

describe("ImportWizard: importing and result", () => {
  it("sends one import request however often the button is clicked", async () => {
    const user = userEvent.setup();
    let release: (r: Response) => void = () => {};
    const calls = stubApi({
      "POST /imports": () => new Promise<Response>((resolve) => (release = resolve)),
    });
    renderWizard();
    await reachReview(user);
    await user.dblClick(screen.getByRole("button", { name: "Import 2 leads" }));
    const status = await screen.findByText(/keep this tab open/);
    expect(status.closest("[role=status]")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("progressbar", { name: "Importing" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Importing your leads" })).toHaveFocus();
    expect(calls.filter((c) => c.method === "POST" && c.path === "/imports")).toHaveLength(1);
    release(Response.json(jobOut(), { status: 201 }));
    await screen.findByRole("heading", { name: "Import finished" });
    expect(calls.filter((c) => c.method === "POST" && c.path === "/imports")).toHaveLength(1);
  });

  it("posts the content, mapping, strategy and filename", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderWizard();
    await reachReview(user);
    await user.click(screen.getByRole("button", { name: "Import 2 leads" }));
    await screen.findByRole("heading", { name: "Import finished" });
    const post = calls.find((c) => c.method === "POST" && c.path === "/imports")!;
    expect(post.body).toMatchObject({
      content: CSV,
      duplicate_strategy: "skip",
      filename: "leads.csv",
      mapping: { name: "Full name", email: "E-mail", company: "Org", notes: "Notes", phone: null },
    });
    expect(refresh).toHaveBeenCalled();
  });

  it("shows the result with an error report link and lets you start over", async () => {
    const user = userEvent.setup();
    stubApi({
      "POST /imports": () =>
        Response.json(
          jobOut({
            created_count: 1,
            updated_count: 1,
            skipped_count: 1,
            error_count: 2,
            suppressed: 1,
          }),
          { status: 201 },
        ),
    });
    renderWizard();
    await reachReview(user);
    await user.click(screen.getByRole("button", { name: "Import 2 leads" }));
    await screen.findByRole("heading", { name: "Import finished" });
    const result = screen.getByRole("list", { name: "Result" });
    expect(result).toHaveTextContent("1 created");
    expect(result).toHaveTextContent("1 updated");
    expect(result).toHaveTextContent("1 duplicate skipped");
    expect(result).toHaveTextContent("2 rows with problems");
    const link = screen.getByRole("link", { name: "Download error report (CSV)" });
    expect(link).toHaveAttribute("href", `/api/v1/workspaces/${WS}/imports/${JOB_ID}/errors.csv`);
    expect(link).toHaveAttribute("download");
    expect(screen.getByRole("link", { name: "View leads" })).toHaveAttribute("href", "/leads");
    expect(screen.getByText(/never emailed/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Import another file" }));
    expect(screen.getByRole("heading", { name: "Choose a CSV file" })).toHaveFocus();
    expect(screen.queryByText("leads.csv")).toBeNull();
  });

  it("offers no error report when every row was imported", async () => {
    const user = userEvent.setup();
    stubApi();
    renderWizard();
    await reachReview(user);
    await user.click(screen.getByRole("button", { name: "Import 2 leads" }));
    await screen.findByRole("heading", { name: "Import finished" });
    expect(screen.queryByRole("link", { name: /error report/i })).toBeNull();
  });
});

describe("ImportWizard: untrusted values", () => {
  it("renders hostile cell values as inert text", async () => {
    const user = userEvent.setup();
    const hostile = '<script>alert(1)</script><img src=x onerror="alert(2)">';
    const formula = '=HYPERLINK("http://evil.example","click")';
    stubApi({
      "POST /imports/preview": (call) =>
        Response.json(
          call.body?.mapping
            ? previewOut({
                rows: [
                  {
                    row: 2,
                    action: "create",
                    values: { name: hostile, notes: formula },
                    issues: [hostile],
                    warnings: [],
                    note: null,
                  },
                ],
                errors: [
                  { row: 2, column: hostile, message: formula, value: hostile, kind: "error" },
                ],
              })
            : previewOut({
                headers: [hostile, "E-mail"],
                suggested_mapping: { name: hostile, email: "E-mail" },
                mapping: { name: hostile, email: "E-mail" },
              }),
        ),
    });
    renderWizard();
    await upload(user, csvFile(`${hostile},E-mail\n${formula},a@b.example\n`));
    await screen.findByRole("heading", { name: "Match your columns" });
    expect(document.querySelector("script, img")).toBeNull();
    expect(
      screen.getAllByText(new RegExp(formula.slice(0, 11).replace("(", "\\("))).length,
    ).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Review before importing" });
    expect(document.querySelector("script, img")).toBeNull();
    expect(screen.getAllByText(hostile).length).toBeGreaterThan(0);
    expect(screen.getAllByText(formula).length).toBeGreaterThan(0);
    expect(document.querySelector("a[href*='evil']")).toBeNull();
  });
});

describe("ImportWizard: accessibility", () => {
  it("has no axe violations on any step", async () => {
    const user = userEvent.setup();
    let release: (r: Response) => void = () => {};
    stubApi({
      "POST /imports": () => new Promise<Response>((resolve) => (release = resolve)),
      "POST /imports/preview": (call) =>
        Response.json(
          call.body?.mapping
            ? previewOut({
                suppressed: 1,
                counts: { create: 1, update: 0, skip_duplicate: 0, error: 1 },
                rows: [
                  {
                    row: 2,
                    action: "error",
                    values: { email: "x" },
                    issues: ["Not valid"],
                    warnings: [],
                    note: null,
                  },
                ],
                errors: [
                  { row: 2, column: "E-mail", message: "Not valid", value: "x", kind: "error" },
                ],
              })
            : previewOut(),
        ),
    });
    const { container } = renderWizard();
    await noViolations(container);
    await reachMap(user);
    await noViolations(container);
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Review before importing" });
    await noViolations(container);
    await user.click(screen.getByRole("button", { name: "Import 1 lead" }));
    await screen.findByRole("heading", { name: "Importing your leads" });
    await noViolations(container);
    release(Response.json(jobOut({ error_count: 1 }), { status: 201 }));
    await screen.findByRole("heading", { name: "Import finished" });
    await noViolations(container);
  });

  it("has no axe violations with an upload error showing", async () => {
    const user = userEvent.setup();
    stubApi();
    const { container } = renderWizard();
    await upload(user, csvFile("   "));
    await screen.findByText(/That file is empty/);
    await noViolations(container);
  });
});
