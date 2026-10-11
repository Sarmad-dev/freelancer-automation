import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Button } from "./button";
import { cn } from "./cn";
import { contrastRatio, darkTokens, lightTokens } from "./tokens";

describe("tokens", () => {
  it.each([
    ["dark", darkTokens],
    ["light", lightTokens],
  ] as const)("%s theme meets WCAG AA for text and accent buttons", (_name, t) => {
    expect(contrastRatio(t.text, t.canvas)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(t.text, t.surface)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(t.textMuted, t.surface)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(t.accentContrast, t.accent)).toBeGreaterThanOrEqual(4.5);
  });
});

describe("Button", () => {
  it("defaults to type=button so it never submits forms by accident", () => {
    expect(renderToStaticMarkup(<Button>Save</Button>)).toContain('type="button"');
  });

  it("merges custom classes and supports disabled", () => {
    const html = renderToStaticMarkup(
      <Button disabled className="w-full">
        Save
      </Button>,
    );
    expect(html).toContain("w-full");
    expect(html).toContain("disabled");
  });

  it("cn resolves conflicting tailwind classes", () => {
    expect(cn("px-2", "px-4")).toBe("px-4");
  });
});
