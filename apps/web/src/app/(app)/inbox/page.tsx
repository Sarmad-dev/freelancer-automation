import type { Metadata } from "next";
import { PlannedPage } from "@/components/planned-page";

export const metadata: Metadata = { title: "Inbox" };

export default function Page() {
  return <PlannedPage id="inbox" />;
}
