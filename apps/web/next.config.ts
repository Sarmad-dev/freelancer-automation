import { loadEnvConfig } from "@next/env";
import type { NextConfig } from "next";

// One root .env for the whole monorepo (see .env.example).
loadEnvConfig(new URL("../../", import.meta.url).pathname);

const config: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Workspace packages ship TypeScript source; Next compiles them.
  transpilePackages: [
    "@freelancer-os/ui",
    "@freelancer-os/contracts",
    "@freelancer-os/workflow-core",
  ],
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
};

export default config;
