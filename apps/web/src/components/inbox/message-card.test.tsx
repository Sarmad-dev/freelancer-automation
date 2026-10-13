import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { describe, expect, it } from "vitest";
import type { ThreadMessage } from "./inbox-model";
import { MessageCard, formatBytes } from "./message-card";

const message = (over: Partial<ThreadMessage> = {}): ThreadMessage => ({
  id: "00000000-0000-4000-8000-000000000001",
  direction: "inbound",
  from_address: "sam@acme.example",
  to_addresses: ["me@gmail.example"],
  subject: "Re: Hello",
  sent_at: "2026-10-12T14:05:00Z",
  is_bounce: false,
  delivery_state: "unknown",
  delivery_label: "",
  delivery_error_code: null,
  attachments: [],
  body: {
    available: true,
    text: "Sounds good.\n\nLet's talk Tuesday.",
    html: null,
    images_blocked: false,
    text_truncated: false,
  },
  ...over,
});

const outbound = (over: Partial<ThreadMessage> = {}) =>
  message({
    direction: "outbound",
    from_address: "me@gmail.example",
    to_addresses: ["sam@acme.example", "lee@acme.example"],
    ...over,
  });

describe("formatBytes", () => {
  it.each([
    [0, "0 B"],
    [512, "512 B"],
    [1024, "1 KB"],
    [20480, "20 KB"],
    [1536 * 1024, "1.5 MB"],
    [2 * 1024 * 1024, "2 MB"],
    [null, ""],
    [undefined, ""],
    [-1, ""],
    [Number.NaN, ""],
  ])("%s -> %j", (input, expected) => {
    expect(formatBytes(input)).toBe(expected);
  });
});

describe("MessageCard", () => {
  it("shows an inbound message with sender, route, UTC time and plain text", () => {
    render(<MessageCard message={message()} />);
    const card = screen.getByRole("article", {
      name: "Message from sam@acme.example, 2026-10-12 14:05 UTC",
    });
    expect(within(card).getByText("sam@acme.example")).toBeInTheDocument();
    expect(within(card).getByText("sam@acme.example → me@gmail.example")).toBeInTheDocument();
    expect(within(card).getByText("2026-10-12 14:05 UTC")).toBeInTheDocument();
    const pre = card.querySelector("pre")!;
    expect(pre.textContent).toBe("Sounds good.\n\nLet's talk Tuesday.");
    expect(pre.className).toContain("whitespace-pre-wrap");
    expect(within(card).queryByRole("group")).toBeNull(); // no html, no toggle
    expect(within(card).queryByText(/Sent|Demo only|Queued/)).toBeNull(); // no delivery badge inbound
  });

  it("never turns text into markup", () => {
    const { container } = render(
      <MessageCard
        message={message({
          body: {
            available: true,
            text: '<img src=x onerror="alert(1)"> <b>bold</b>',
            html: null,
            images_blocked: false,
            text_truncated: false,
          },
        })}
      />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(container.querySelector("pre")!.textContent).toContain("<b>bold</b>");
  });

  it("says 'You' for outbound mail and lists every recipient", () => {
    render(<MessageCard message={outbound({ delivery_state: "sent", delivery_label: "Sent" })} />);
    const card = screen.getByRole("article", { name: /Message from you/ });
    expect(within(card).getByText("You")).toBeInTheDocument();
    expect(
      within(card).getByText("me@gmail.example → sam@acme.example, lee@acme.example"),
    ).toBeInTheDocument();
  });

  it.each([
    ["demo", "Demo only", "text-info"],
    ["queued", "Queued to send", "text-muted"],
    ["sent", "Sent", "text-success"],
    ["failed", "Not delivered", "text-danger"],
    ["unknown", "Delivery not confirmed", "text-warning"],
  ] as const)("shows the %s delivery state from the server's label", (state, label, tone) => {
    render(<MessageCard message={outbound({ delivery_state: state, delivery_label: label })} />);
    const badge = screen.getByText(label);
    expect(badge).toHaveAttribute("title", label);
    expect(badge.className).toContain(tone);
  });

  it("flags a delivery failure notice", () => {
    render(<MessageCard message={message({ is_bounce: true })} />);
    expect(screen.getByText("Delivery failure notice")).toBeInTheDocument();
  });

  it("explains when only a preview is stored", () => {
    render(
      <MessageCard
        message={message({
          body: {
            available: false,
            text: "Short preview…",
            html: null,
            images_blocked: false,
            text_truncated: false,
          },
        })}
      />,
    );
    expect(screen.getByText("Only a short preview of this message is stored.")).toBeInTheDocument();
    expect(screen.getByText("Short preview…")).toBeInTheDocument();
  });

  it("has a fallback for an empty body", () => {
    render(
      <MessageCard
        message={message({
          body: {
            available: true,
            text: "  ",
            html: null,
            images_blocked: false,
            text_truncated: false,
          },
        })}
      />,
    );
    expect(screen.getByText("There is no text in this message.")).toBeInTheDocument();
  });

  it("notes blocked images and shortened text", () => {
    render(
      <MessageCard
        message={message({
          body: {
            available: true,
            text: "Long",
            html: null,
            images_blocked: true,
            text_truncated: true,
          },
        })}
      />,
    );
    expect(screen.getByText("Images and other remote content are not loaded.")).toBeInTheDocument();
    expect(screen.getByText("This long message was shortened.")).toBeInTheDocument();
  });

  it("lists attachments with sizes, and never offers to open them", () => {
    render(
      <MessageCard
        message={message({
          attachments: [
            { filename: "proposal.pdf", mime_type: "application/pdf", size: 20480 },
            { filename: "notes.txt", mime_type: "text/plain", size: null },
          ],
        })}
      />,
    );
    const list = screen.getByRole("list", { name: "Attachments" });
    const [pdf, txt] = within(list).getAllByRole("listitem");
    expect(pdf).toHaveTextContent("proposal.pdf application/pdf, 20 KB");
    expect(txt).toHaveTextContent("notes.txt text/plain");
    expect(txt!.textContent).not.toMatch(/,/);
    expect(within(list).queryByRole("link")).toBeNull();
    expect(
      screen.getByText("Attachment contents aren't stored or opened here."),
    ).toBeInTheDocument();
  });

  it("shows no attachment note when there are none", () => {
    render(<MessageCard message={message()} />);
    expect(screen.queryByText(/Attachment contents/)).toBeNull();
  });

  describe("formatted view", () => {
    const withHtml = () =>
      message({
        body: {
          available: true,
          text: "Plain version",
          html: "<p>Rich <b>version</b></p>",
          images_blocked: false,
          text_truncated: false,
        },
      });

    it("defaults to text and switches to a sandboxed frame and back", async () => {
      const user = userEvent.setup();
      render(<MessageCard message={withHtml()} />);
      const group = screen.getByRole("group", { name: "Message view" });
      const text = within(group).getByRole("button", { name: "Text" });
      const formatted = within(group).getByRole("button", { name: "Formatted" });
      expect(text).toHaveAttribute("aria-pressed", "true");
      expect(formatted).toHaveAttribute("aria-pressed", "false");
      expect(screen.getByText("Plain version")).toBeInTheDocument();
      expect(screen.queryByTitle("Formatted message")).toBeNull();

      await user.click(formatted);
      expect(formatted).toHaveAttribute("aria-pressed", "true");
      expect(text).toHaveAttribute("aria-pressed", "false");
      const frame = screen.getByTitle("Formatted message");
      expect(frame.getAttribute("srcdoc")).toContain("<p>Rich <b>version</b></p>");
      expect(screen.queryByText("Plain version")).toBeNull();

      await user.click(text);
      expect(screen.queryByTitle("Formatted message")).toBeNull();
      expect(screen.getByText("Plain version")).toBeInTheDocument();
    });

    it("is operable from the keyboard", async () => {
      const user = userEvent.setup();
      render(<MessageCard message={withHtml()} />);
      await user.tab();
      await user.tab();
      expect(screen.getByRole("button", { name: "Formatted" })).toHaveFocus();
      await user.keyboard("{Enter}");
      expect(screen.getByTitle("Formatted message")).toBeInTheDocument();
    });

    it("offers no toggle when only a preview is stored", () => {
      render(
        <MessageCard
          message={message({
            body: {
              available: false,
              text: "Preview",
              html: "<p>x</p>",
              images_blocked: false,
              text_truncated: false,
            },
          })}
        />,
      );
      expect(screen.queryByRole("group")).toBeNull();
    });
  });

  it("has no accessibility violations", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <ol>
        <li>
          <MessageCard
            message={outbound({
              delivery_state: "failed",
              delivery_label: "Not delivered",
              is_bounce: true,
              attachments: [{ filename: "a.pdf", mime_type: "application/pdf", size: 10 }],
              body: {
                available: true,
                text: "Hi",
                html: "<p>Hi</p>",
                images_blocked: true,
                text_truncated: true,
              },
            })}
          />
        </li>
      </ol>,
    );
    // jsdom cannot message into a sandboxed frame, so axe is told to skip frame contents.
    const rules = { iframes: false, rules: { "color-contrast": { enabled: false } } };
    expect((await axe.run(container, rules)).violations).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Formatted" }));
    expect((await axe.run(container, rules)).violations).toEqual([]);
  });
});
