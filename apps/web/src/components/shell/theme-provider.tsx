"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import {
  DEFAULT_THEME_PREFERENCE,
  THEME_STORAGE_KEY,
  isThemePreference,
  resolveTheme,
  type ResolvedTheme,
  type ThemePreference,
} from "@freelancer-os/ui";
import { useLocalValue } from "./local-store";

interface ThemeContextValue {
  preference: ThemePreference;
  resolved: ResolvedTheme;
  setPreference: (value: ThemePreference) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used inside <ThemeProvider>");
  return ctx;
}

const DARK_QUERY = "(prefers-color-scheme: dark)";

function subscribeSystem(cb: () => void) {
  const mql = window.matchMedia(DARK_QUERY);
  mql.addEventListener("change", cb);
  return () => mql.removeEventListener("change", cb);
}

/**
 * The pre-paint script in the root layout sets `data-theme` before hydration (no flash).
 * This provider owns changes after that and keeps the preference in localStorage.
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [stored, store] = useLocalValue(THEME_STORAGE_KEY);
  const preference: ThemePreference = isThemePreference(stored) ? stored : DEFAULT_THEME_PREFERENCE;
  const systemDark = useSyncExternalStore(
    subscribeSystem,
    () => window.matchMedia(DARK_QUERY).matches,
    () => true,
  );
  const resolved = resolveTheme(preference, systemDark);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", resolved);
  }, [resolved]);

  const setPreference = useCallback((value: ThemePreference) => store(value), [store]);
  const value = useMemo(
    () => ({ preference, resolved, setPreference }),
    [preference, resolved, setPreference],
  );
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
