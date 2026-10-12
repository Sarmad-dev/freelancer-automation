import type { Metadata } from "next";
import { PlannedPage } from "@/components/planned-page";

export const metadata: Metadata = { title: "Leads" };

export default function Page() {
  return <PlannedPage id="leads" />;
}
