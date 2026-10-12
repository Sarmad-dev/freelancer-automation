import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { DesignSystemDemo } from "./demo";

export const metadata: Metadata = { title: "Design system" };

export default function DesignSystemPage() {
  // Internal reference page: development and test builds only.
  if (process.env.NODE_ENV === "production" && process.env.ENABLE_DESIGN_SYSTEM_PAGE !== "1") {
    notFound();
  }
  return <DesignSystemDemo />;
}
