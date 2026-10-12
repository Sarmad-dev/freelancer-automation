import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Button } from "./button";
import { cn } from "./cn";
import { blend, contrastRatio, darkTokens, lightTokens } from "./tokens";

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

describe("status colours as badge text", () => {
  it.each([
    ["dark", darkTokens],
    ["light", lightTokens],
  ] as const)(
    "%s theme: accent/status text on its 10%% tint meets AA on every surface",
    (_n, t) => {
      for (const color of [t.accent, t.success, t.warning, t.danger, t.info]) {
        for (const bg of [t.canvas, t.surface, t.elevated, t.sidebar]) {
          expect(contrastRatio(color, blend(color, bg, 0.1))).toBeGreaterThanOrEqual(4.5);
        }
      }
    },
  );
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
