import { describe, expect, it } from "vitest";
import {
  DEFAULT_THEME_PREFERENCE,
  THEME_INIT_SCRIPT,
  THEME_STORAGE_KEY,
  readStoredTheme,
  resolveTheme,
  writeStoredTheme,
} from "./theme";

const store = (value: string | null) => ({ getItem: () => value });
const throwing = {
  getItem: () => {
    throw new Error("blocked");
  },
  setItem: () => {
    throw new Error("blocked");
  },
};

describe("theme preference", () => {
  it("defaults to dark", () => {
    expect(DEFAULT_THEME_PREFERENCE).toBe("dark");
    expect(readStoredTheme(store(null))).toBe("dark");
    expect(readStoredTheme(undefined)).toBe("dark");
  });

  it("accepts valid values and rejects tampered ones", () => {
    expect(readStoredTheme(store("light"))).toBe("light");
    expect(readStoredTheme(store("system"))).toBe("system");
    expect(readStoredTheme(store("<script>"))).toBe("dark");
  });

  it("never throws when storage is blocked", () => {
    expect(readStoredTheme(throwing)).toBe("dark");
    expect(() => writeStoredTheme(throwing, "light")).not.toThrow();
  });

  it("resolves system preference", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("light", true)).toBe("light");
  });

  it("pre-paint script is valid JS, sets data-theme and falls back to dark on error", () => {
    expect(THEME_INIT_SCRIPT).toContain(THEME_STORAGE_KEY);
    const attrs: Record<string, string> = {};
    const run = (ls: unknown, dark = false) => {
      const fn = new Function("localStorage", "window", "document", THEME_INIT_SCRIPT);
      fn(
        ls,
        { matchMedia: () => ({ matches: dark }) },
        { documentElement: { setAttribute: (k: string, v: string) => (attrs[k] = v) } },
      );
      return attrs["data-theme"];
    };
    expect(run({ getItem: () => "light" })).toBe("light");
    expect(run({ getItem: () => null })).toBe("dark");
    expect(run({ getItem: () => "system" }, false)).toBe("light");
    expect(run({ getItem: () => "bogus" })).toBe("dark");
    expect(
      run({
        getItem: () => {
          throw new Error("x");
        },
      }),
    ).toBe("dark");
  });
});
