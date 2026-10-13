import { describe, expect, it } from "vitest";
import { formatDate, safeExternalUrl } from "./safe-url";

describe("safeExternalUrl", () => {
  it.each(["https://example.com/work", "http://example.com", "https://sub.example.co.uk/a?b=1#c"])(
    "allows %s",
    (url) => expect(safeExternalUrl(url)).toBeTruthy(),
  );

  it.each([
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    "data:text/html,<script>1</script>",
    "vbscript:x",
    "file:///etc/passwd",
    "ftp://example.com",
    "mailto:a@b.example",
    "https://user:pass@example.com",
    "//example.com",
    "example.com",
    "",
    "   ",
  ])("rejects %j", (url) => expect(safeExternalUrl(url)).toBeNull());

  it("handles null and undefined", () => {
    expect(safeExternalUrl(null)).toBeNull();
    expect(safeExternalUrl(undefined)).toBeNull();
  });
});

describe("formatDate", () => {
  it("is timezone-independent", () => {
    expect(formatDate("2026-10-12T23:59:59.000Z")).toBe("2026-10-12");
  });
});
