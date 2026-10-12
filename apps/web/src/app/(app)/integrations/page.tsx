import type { Metadata } from "next";
import { PlannedPage } from "@/components/planned-page";

export const metadata: Metadata = { title: "Integrations" };

export default function Page() {
  return <PlannedPage id="integrations" />;
}
