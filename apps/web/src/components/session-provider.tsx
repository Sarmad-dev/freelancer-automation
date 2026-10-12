"use client";

import { createContext, useContext, type ReactNode } from "react";
import type { MeResponse, WorkspaceOut } from "@freelancer-os/contracts";

interface SessionValue {
  user: MeResponse["user"];
  workspace: WorkspaceOut;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ me, children }: { me: MeResponse; children: ReactNode }) {
  const workspace = me.workspaces[0];
  if (!workspace) throw new Error("Authenticated user has no workspace");
  return (
    <SessionContext.Provider value={{ user: me.user, workspace }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used inside <SessionProvider>");
  return ctx;
}
