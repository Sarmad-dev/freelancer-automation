"use client";

import type { ReactNode } from "react";
import { ToastProvider, TooltipProvider } from "@freelancer-os/ui";
import { ThemeProvider } from "@/components/shell/theme-provider";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider>
      <TooltipProvider delayDuration={200}>
        <ToastProvider>{children}</ToastProvider>
      </TooltipProvider>
    </ThemeProvider>
  );
}
