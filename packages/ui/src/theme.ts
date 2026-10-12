/**
 * Theme preference logic shared by the app and tests. Dark is the product default.
 * Storage access is always wrapped: it can throw (private mode, blocked site data).
 */
export const THEME_STORAGE_KEY = "fos-theme";
export const THEME_PREFERENCES = ["dark", "light", "system"] as const;
export type ThemePreference = (typeof THEME_PREFERENCES)[number];
export type ResolvedTheme = "dark" | "light";
export const DEFAULT_THEME_PREFERENCE: ThemePreference = "dark";

export function isThemePreference(value: unknown): value is ThemePreference {
  return typeof value === "string" && (THEME_PREFERENCES as readonly string[]).includes(value);
}

export function readStoredTheme(storage: Pick<Storage, "getItem"> | undefined): ThemePreference {
  try {
    const value = storage?.getItem(THEME_STORAGE_KEY);
    return isThemePreference(value) ? value : DEFAULT_THEME_PREFERENCE;
  } catch {
    return DEFAULT_THEME_PREFERENCE;
  }
}

export function writeStoredTheme(
  storage: Pick<Storage, "setItem"> | undefined,
  value: ThemePreference,
): void {
  try {
    storage?.setItem(THEME_STORAGE_KEY, value);
  } catch {
    // Preference simply won't persist; the UI still works for this session.
  }
}

export function resolveTheme(
  preference: ThemePreference,
  systemPrefersDark: boolean,
): ResolvedTheme {
  if (preference === "system") return systemPrefersDark ? "dark" : "light";
  return preference;
}

/**
 * Inline script that runs before first paint to avoid a theme flash.
 * Must stay dependency-free and mirror readStoredTheme/resolveTheme.
 */
export const THEME_INIT_SCRIPT = `(function(){try{var p=localStorage.getItem(${JSON.stringify(
  THEME_STORAGE_KEY,
)});if(p!=="light"&&p!=="system"&&p!=="dark")p="${DEFAULT_THEME_PREFERENCE}";var d=p==="system"?window.matchMedia("(prefers-color-scheme: dark)").matches:p==="dark";document.documentElement.setAttribute("data-theme",d?"dark":"light")}catch(e){document.documentElement.setAttribute("data-theme","dark")}})()`;
