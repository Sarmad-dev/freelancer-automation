import { Badge } from "@freelancer-os/ui";
import { fitMeta, statusMeta } from "./lead-model";

export function StatusBadge({ status }: { status: string }) {
  const meta = statusMeta(status);
  return <Badge tone={meta.tone}>{meta.label}</Badge>;
}

/** Score badge: always words first, number second ("Strong fit · 75"). */
export function FitBadge({
  band,
  score,
}: {
  band: string | null | undefined;
  score: number | null | undefined;
}) {
  const meta = fitMeta(band, score);
  return <Badge tone={meta.tone}>{meta.text}</Badge>;
}

export function SampleBadge() {
  return (
    <Badge tone="info" title="Fictional demo data. Nothing here is a real person or company.">
      Sample
    </Badge>
  );
}

export function DoNotContactBadge() {
  return (
    <Badge
      tone="danger"
      title="This email is on your do-not-contact list. Nothing will be sent to it."
    >
      Do not contact
    </Badge>
  );
}
