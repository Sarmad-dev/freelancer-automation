import type { Metadata } from "next";
import { PlannedPage } from "@/components/planned-page";

export const metadata: Metadata = { title: "Automations" };

export default function Page() {
  return <PlannedPage id="automations" />;
}
