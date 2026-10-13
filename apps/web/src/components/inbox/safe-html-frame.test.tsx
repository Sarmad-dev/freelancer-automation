import { render, screen } from "@testing-library/react";
import axe from "axe-core";
import { describe, expect, it } from "vitest";
import { SafeHtmlFrame, buildEmailDocument } from "./safe-html-frame";

const WITHHELD = "This message&#39;s formatted view was withheld for safety.";

describe("buildEmailDocument", () => {
  it("wraps the html in a locked-down document", () => {
    const doc = buildEmailDocument("<p>Hello <b>there</b></p>");
    expect(doc.startsWith('<!doctype html><html><head><meta charset="utf-8">')).toBe(true);
    expect(doc).toContain(
      `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; form-action 'none'">`,
    );
    expect(doc).toContain('<base target="_blank">');
    expect(doc).toMatch(/<style>[\s\S]*blockquote[\s\S]*<\/style>/);
    expect(doc).toContain("<body><p>Hello <b>there</b></p></body>");
    expect(doc).not.toContain(WITHHELD);
  });

  it.each([
    ["a script tag", "<p>x</p><script>alert(1)</script>"],
    ["an upper-case script tag", "<SCRIPT SRC=x></SCRIPT>"],
    ["a javascript: link", '<a href="JavaScript:alert(1)">x</a>'],
    ["an inline handler", '<img src="x" onerror="alert(1)">'],
    ["an upper-case handler without a space", '<a href="#"ONCLICK = "x">x</a>'],
    ["a handler after a newline", "<div\nonmouseover=alert(1)>x</div>"],
  ])("withholds the message when it contains %s", (_name, html) => {
    const doc = buildEmailDocument(html);
    expect(doc).toContain(WITHHELD);
    expect(doc).not.toMatch(/alert\(1\)/);
    expect(doc).not.toMatch(/<script/i);
    expect(doc).toContain("default-src 'none'");
  });

  it("does not mistake ordinary words for event handlers", () => {
    const doc = buildEmailDocument("<p>It is only = a test, on Monday = fine</p>");
    expect(doc).toContain("only = a test");
    expect(doc).not.toContain(WITHHELD);
  });
});

describe("SafeHtmlFrame", () => {
  it("is sandboxed with no scripts and no same-origin access", () => {
    render(<SafeHtmlFrame html="<p>Hi</p>" />);
    const frame = screen.getByTitle("Formatted message");
    expect(frame.tagName).toBe("IFRAME");
    const sandbox = frame.getAttribute("sandbox") ?? "";
    expect(sandbox.split(/\s+/).sort()).toEqual(["allow-popups", "allow-popups-to-escape-sandbox"]);
    expect(sandbox).not.toContain("allow-scripts");
    expect(sandbox).not.toContain("allow-same-origin");
    expect(frame).toHaveAttribute("referrerpolicy", "no-referrer");
    expect(frame).toHaveAttribute("loading", "lazy");
    expect(frame.getAttribute("srcdoc")).toBe(buildEmailDocument("<p>Hi</p>"));
  });

  it("has no accessibility violations", async () => {
    const { container } = render(<SafeHtmlFrame html="<p>Hi</p>" />);
    // jsdom cannot message into a sandboxed frame, so axe is told to skip frame contents.
    const rules = { iframes: false, rules: { "color-contrast": { enabled: false } } };
    expect((await axe.run(container, rules)).violations).toEqual([]);
  });
});
