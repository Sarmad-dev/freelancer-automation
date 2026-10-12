"use client";

import * as ToastPrimitive from "@radix-ui/react-toast";
import { CheckCircle2, Info, TriangleAlert, X, XCircle } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { cn } from "./cn";

export type ToastTone = "info" | "success" | "warning" | "danger";
export interface ToastInput {
  title: string;
  description?: string;
  tone?: ToastTone;
}
interface ToastItem extends ToastInput {
  id: number;
}

const icons = {
  info: <Info className="size-4 text-info" aria-hidden />,
  success: <CheckCircle2 className="size-4 text-success" aria-hidden />,
  warning: <TriangleAlert className="size-4 text-warning" aria-hidden />,
  danger: <XCircle className="size-4 text-danger" aria-hidden />,
};

const ToastContext = createContext<((t: ToastInput) => void) | null>(null);

export function useToast(): { toast: (t: ToastInput) => void } {
  const toast = useContext(ToastContext);
  if (!toast) throw new Error("useToast must be used inside <ToastProvider>");
  return useMemo(() => ({ toast }), [toast]);
}

let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const toast = useCallback((t: ToastInput) => {
    setItems((prev) => [...prev.slice(-3), { ...t, id: nextId++ }]);
  }, []);
  return (
    <ToastContext.Provider value={toast}>
      <ToastPrimitive.Provider swipeDirection="right" duration={6000} label="Notifications">
        {children}
        {items.map((t) => (
          <ToastPrimitive.Root
            key={t.id}
            // Errors interrupt screen readers; everything else is announced politely.
            type={t.tone === "danger" ? "foreground" : "background"}
            onOpenChange={(open) => {
              if (!open) setItems((prev) => prev.filter((x) => x.id !== t.id));
            }}
            className={cn(
              "flex items-start gap-3 rounded-md border border-line bg-elevated p-3 pr-2 shadow-[var(--fos-shadow-elevated)]",
              "data-[state=open]:animate-[fos-slide-in-right_180ms_ease-out]",
            )}
          >
            {icons[t.tone ?? "info"]}
            <div className="min-w-0 flex-1">
              <ToastPrimitive.Title className="text-sm font-medium text-fg">
                {t.title}
              </ToastPrimitive.Title>
              {t.description ? (
                <ToastPrimitive.Description className="mt-0.5 text-[13px] text-muted">
                  {t.description}
                </ToastPrimitive.Description>
              ) : null}
            </div>
            <ToastPrimitive.Close
              aria-label="Dismiss notification"
              className="flex size-6 items-center justify-center rounded-sm text-muted hover:bg-line hover:text-fg"
            >
              <X className="size-4" aria-hidden />
            </ToastPrimitive.Close>
          </ToastPrimitive.Root>
        ))}
        <ToastPrimitive.Viewport className="fixed right-4 bottom-4 z-[60] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2 outline-none" />
      </ToastPrimitive.Provider>
    </ToastContext.Provider>
  );
}
