"use client";

import { useCallback, useSyncExternalStore } from "react";

/**
 * Tiny external store over localStorage for UI preferences. Uses useSyncExternalStore so server
 * and first client render agree (server snapshot) and the stored value applies right after hydration.
 * Falls back to in-memory values when storage is unavailable (private mode, blocked site data).
 */
const memory = new Map<string, string | null>();
const listeners = new Map<string, Set<() => void>>();

function read(key: string): string | null {
  if (memory.has(key)) return memory.get(key) ?? null;
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function notify(key: string) {
  listeners.get(key)?.forEach((cb) => cb());
}

export function setLocalValue(key: string, value: string) {
  memory.set(key, value);
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* in-memory only for this session */
  }
  notify(key);
}

function subscribeTo(key: string, cb: () => void) {
  const set = listeners.get(key) ?? new Set<() => void>();
  set.add(cb);
  listeners.set(key, set);
  const onStorage = (e: StorageEvent) => {
    if (e.key === key || e.key === null) {
      memory.delete(key);
      cb();
    }
  };
  window.addEventListener("storage", onStorage);
  return () => {
    set.delete(cb);
    window.removeEventListener("storage", onStorage);
  };
}

export function useLocalValue(key: string): readonly [string | null, (value: string) => void] {
  const subscribe = useCallback((cb: () => void) => subscribeTo(key, cb), [key]);
  const value = useSyncExternalStore(
    subscribe,
    () => read(key),
    () => null,
  );
  const set = useCallback((v: string) => setLocalValue(key, v), [key]);
  return [value, set] as const;
}

/** Test helper. */
export function resetLocalStoreForTests() {
  memory.clear();
  listeners.clear();
}
