import { describe, expect, it } from "vitest";
import { EnvError, parseEnv } from "./env";

describe("parseEnv", () => {
  it("applies safe defaults", () => {
    expect(parseEnv({})).toEqual({
      API_URL: "http://localhost:8000",
      NEXT_PUBLIC_APP_NAME: "Freelancer OS",
    });
  });

  it("rejects an invalid API_URL with an actionable message", () => {
    expect(() => parseEnv({ API_URL: "not a url" })).toThrow(EnvError);
    expect(() => parseEnv({ API_URL: "not a url" })).toThrow(
      /API_URL.*\.env\.example|\.env\.example[\s\S]*API_URL/,
    );
  });
});
