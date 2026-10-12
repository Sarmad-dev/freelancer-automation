import "server-only";
import { redirect } from "next/navigation";
import { getSession } from "./session";
import { serverApi } from "./server-api";

/** Signed-in server-side context for workspace pages: API client + the current workspace id. */
export async function requireWorkspace() {
  const session = await getSession();
  if (session.status === "expired") redirect("/sign-in?reason=expired");
  if (session.status !== "authenticated") redirect("/sign-in");
  const workspace = session.me.workspaces[0];
  const api = await serverApi();
  if (!workspace || !api) redirect("/sign-in");
  return { api, workspaceId: workspace.id, workspace };
}
