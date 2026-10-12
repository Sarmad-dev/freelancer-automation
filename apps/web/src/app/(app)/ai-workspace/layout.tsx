import { PageHeader } from "@freelancer-os/ui";
import { AiWorkspaceTabs } from "@/components/ai-workspace/tabs";

export default function AiWorkspaceLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="AI Workspace"
        description="Your profile and the approved knowledge AI is allowed to use. Everything here works without an AI provider connected."
      />
      <AiWorkspaceTabs />
      {children}
    </div>
  );
}
