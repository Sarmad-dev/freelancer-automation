import base from "@freelancer-os/shared-config/eslint";
import nextVitals from "eslint-config-next/core-web-vitals";

// eslint-disable-next-line import/no-anonymous-default-export
export default [...base, ...nextVitals, { ignores: ["next-env.d.ts"] }];
