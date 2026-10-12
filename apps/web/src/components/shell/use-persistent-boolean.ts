"use client";

import { useCallback } from "react";
import { useLocalValue } from "./local-store";

/** Boolean UI preference persisted in localStorage; tolerant of storage being unavailable. */
export function usePersistentBoolean(key: string, initial = false) {
  const [raw, setRaw] = useLocalValue(key);
  const value = raw === "1" ? true : raw === "0" ? false : initial;
  const update = useCallback((next: boolean) => setRaw(next ? "1" : "0"), [setRaw]);
  return [value, update] as const;
}
