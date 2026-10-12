import { PageHeader, PlannedFeature, Badge } from "@freelancer-os/ui";
import { findNavItem } from "@/config/navigation";

/** Honest placeholder for a destination that ships in a later phase. */
export function PlannedPage({ id }: { id: string }) {
  const item = findNavItem(id);
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={item.label}
        description={item.description}
        badge={<Badge tone="info">Coming soon</Badge>}
      />
      <PlannedFeature
        title={`${item.label} isn't available yet`}
        description={item.description}
        phase={item.phase ?? "a later phase"}
      />
    </div>
  );
}
