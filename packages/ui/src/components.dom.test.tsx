import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { axeViolations } from "./axe";
import { Button } from "./button";
import { Checkbox } from "./checkbox";
import { ConfirmDialog, Modal } from "./overlay";
import { Field, Input, Select } from "./field";
import { EmptyState, ErrorState, Notice, PermissionDeniedState } from "./states";
import { FilterChips, Pagination, TableToolbar } from "./table";
import { ToastProvider, useToast } from "./toast";
import { Badge } from "./badge";
import { Switch } from "./switch";
import { PageHeader, Breadcrumbs } from "./page";

describe("Field", () => {
  it("wires label, hint and error to the control", () => {
    render(
      <Field label="Email" hint="Work address" error="Invalid email">
        {(p) => <Input {...p} />}
      </Field>,
    );
    const input = screen.getByLabelText("Email");
    expect(input).toHaveAttribute("aria-invalid", "true");
    const described = input.getAttribute("aria-describedby") ?? "";
    expect(described.split(" ")).toHaveLength(2);
    expect(document.getElementById(described.split(" ")[1] ?? "")).toHaveTextContent(
      "Invalid email",
    );
  });

  it("omits aria attributes when there is nothing to describe", () => {
    render(<Field label="Name">{(p) => <Input {...p} />}</Field>);
    const input = screen.getByLabelText("Name");
    expect(input).not.toHaveAttribute("aria-invalid");
    expect(input).not.toHaveAttribute("aria-describedby");
  });
});

describe("Modal / ConfirmDialog", () => {
  function Harness() {
    const [open, setOpen] = useState(false);
    return (
      <>
        <Button onClick={() => setOpen(true)}>Open</Button>
        <Modal
          open={open}
          onOpenChange={setOpen}
          title="Add note"
          description="Visible to you only"
        >
          <Input aria-label="Note" />
        </Modal>
      </>
    );
  }

  it("is a labelled dialog, closes on Escape and returns focus to the opener", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Open" });
    await user.click(opener);
    const dialog = screen.getByRole("dialog", { name: "Add note" });
    expect(dialog).toHaveAccessibleDescription("Visible to you only");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opener).toHaveFocus();
  });

  it("confirm dialog focuses Cancel first and only confirms on explicit action", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <ConfirmDialog
        open
        onOpenChange={onOpenChange}
        title="Archive lead?"
        description="Hidden from lists."
        confirmLabel="Archive"
        destructive
        onConfirm={onConfirm}
      />,
    );
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onConfirm).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Archive" }));
    expect(onConfirm).toHaveBeenCalledOnce();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});

describe("Pagination", () => {
  it("shows ranges, disables edges and reports page changes", async () => {
    const user = userEvent.setup();
    const onPage = vi.fn();
    const { rerender } = render(
      <Pagination page={1} pageSize={10} total={23} onPageChange={onPage} noun="leads" />,
    );
    expect(screen.getByText("1–10 of 23 leads")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Next page" }));
    expect(onPage).toHaveBeenCalledWith(2);
    rerender(<Pagination page={3} pageSize={10} total={23} onPageChange={onPage} noun="leads" />);
    expect(screen.getByText("21–23 of 23 leads")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
  });

  it("handles empty results and clamps out-of-range pages", () => {
    render(<Pagination page={9} pageSize={10} total={0} onPageChange={() => {}} />);
    expect(screen.getByText("0–0 of 0 results")).toBeInTheDocument();
    expect(screen.getByText("Page 1 of 1")).toBeInTheDocument();
  });
});

describe("FilterChips / TableToolbar", () => {
  it("removes chips by accessible name and clears all", async () => {
    const user = userEvent.setup();
    const onRemove = vi.fn();
    const onClear = vi.fn();
    render(
      <FilterChips
        chips={[{ id: "a", label: "Stage: New" }]}
        onRemove={onRemove}
        onClear={onClear}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Remove filter: Stage: New" }));
    expect(onRemove).toHaveBeenCalledWith("a");
    await user.click(screen.getByRole("button", { name: "Clear all" }));
    expect(onClear).toHaveBeenCalled();
  });

  it("renders nothing without chips", () => {
    const { container } = render(<FilterChips chips={[]} onRemove={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("announces selection count", () => {
    render(<TableToolbar selectedCount={3} bulkActions={<Button>Tag</Button>} />);
    expect(screen.getByRole("status")).toHaveTextContent("3 selected");
    expect(screen.getByRole("toolbar", { name: "Table controls" })).toBeInTheDocument();
  });
});

describe("Toasts", () => {
  function Trigger() {
    const { toast } = useToast();
    return (
      <Button
        onClick={() => toast({ title: "Saved", description: "Lead updated", tone: "success" })}
      >
        Go
      </Button>
    );
  }
  it("shows a toast with a dismiss control", async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <Trigger />
      </ToastProvider>,
    );
    await user.click(screen.getByRole("button", { name: "Go" }));
    expect(await screen.findByText("Lead updated")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dismiss notification" })).toBeInTheDocument();
  });

  it("useToast outside a provider fails loudly", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Trigger />)).toThrow(/ToastProvider/);
    spy.mockRestore();
  });
});

describe("States", () => {
  it("error state is an alert, offers retry and shows a reference but no raw error", async () => {
    const user = userEvent.setup();
    const retry = vi.fn();
    render(<ErrorState onRetry={retry} detail="abc123" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Reference: abc123");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalled();
  });

  it("empty state heading level is configurable", () => {
    render(<EmptyState title="Page not found" titleAs="h1" />);
    expect(screen.getByRole("heading", { level: 1, name: "Page not found" })).toBeInTheDocument();
  });
});

describe("Checkbox", () => {
  it("toggles via its label and reports changes", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Checkbox label="Notify me" description="Daily digest" onCheckedChange={onChange} />);
    await user.click(screen.getByLabelText("Notify me"));
    expect(onChange).toHaveBeenCalledWith(true);
    expect(screen.getByRole("checkbox", { name: "Notify me" })).toHaveAccessibleDescription(
      "Daily digest",
    );
  });
});

describe("axe: composed screens have no structural a11y violations", () => {
  it("form + states + header", async () => {
    const { container } = render(
      <main>
        <Breadcrumbs items={[{ label: "Home", href: "/" }, { label: "Leads" }]} />
        <PageHeader
          title="Leads"
          badge={<Badge tone="info">Demo data</Badge>}
          actions={<Button>Add lead</Button>}
        />
        <form aria-label="Example">
          <Field label="Stage">
            {(p) => (
              <Select {...p}>
                <option>New</option>
              </Select>
            )}
          </Field>
          <Field label="Email" error="Required">
            {(p) => <Input {...p} />}
          </Field>
          <Checkbox label="Remember" />
        </form>
        <Notice title="Heads up">Preview only</Notice>
        <EmptyState title="Nothing yet" />
        <PermissionDeniedState />
        <Pagination page={1} pageSize={5} total={12} onPageChange={() => {}} />
        <FilterChips chips={[{ id: "x", label: "Stage: New" }]} onRemove={() => {}} />
      </main>,
    );
    expect(await axeViolations(container)).toEqual([]);
  });

  it("open dialog", async () => {
    render(<Modal open onOpenChange={() => {}} title="Dialog" description="desc" />);
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "Close" })).toBeInTheDocument();
    expect(await axeViolations(dialog)).toEqual([]);
  });
});

describe("Switch", () => {
  it("is a named switch that toggles with click and keyboard, and respects disabled", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { container, rerender } = render(
      <Switch checked={false} onCheckedChange={onChange} label="Use in drafts" />,
    );
    const sw = screen.getByRole("switch", { name: "Use in drafts" });
    expect(sw).toHaveAttribute("aria-checked", "false");
    await user.click(sw);
    expect(onChange).toHaveBeenLastCalledWith(true);
    sw.focus();
    await user.keyboard(" ");
    expect(onChange).toHaveBeenCalledTimes(2);
    expect(await axeViolations(container)).toEqual([]);
    rerender(<Switch checked onCheckedChange={onChange} label="Use in drafts" disabled />);
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("switch")).toBeDisabled();
  });
});
