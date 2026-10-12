import { describe, expect, it } from "vitest";
import { safeNextPath } from "./safe-redirect";

describe("safeNextPath", () => {
  it.each([
    ["/leads", "/leads"],
    ["/leads?stage=new&q=a", "/leads?stage=new&q=a"],
    ["/pipeline/123#notes", "/pipeline/123#notes"],
  ])("keeps same-origin path %s", (input, expected) => {
    expect(safeNextPath(input)).toBe(expected);
  });

  it.each([
    "https://evil.example",
    "http://evil.example/x",
    "//evil.example",
    "///evil.example",
    "/\\evil.example",
    "\\\\evil.example",
    "javascript:alert(1)",
    "evil.example",
    "/ok\nSet-Cookie: x=1",
    "/ok\u0000",
    "/sign-in",
    "/sign-up?x=1",
    "/reset-password?token=abc",
    "/" + "a".repeat(600),
    "",
  ])("rejects %j", (input) => {
    expect(safeNextPath(input)).toBe("/");
  });

  it("handles missing values and custom fallbacks", () => {
    expect(safeNextPath(undefined)).toBe("/");
    expect(safeNextPath(null, "/home")).toBe("/home");
  });
});
