import { PageHeader } from "@freelancer-os/ui";
import { LeadTabs } from "@/components/leads/lead-tabs";

export default function LeadsListsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Leads"
        description="People and companies you might work with. Add them by hand, import a CSV, or start from the sample data. Nothing here needs an outside lead source."
      />
      <LeadTabs />
      {children}
    </div>
  );
}
