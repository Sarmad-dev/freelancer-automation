import { z } from "zod";

const schema = z.object({
  /** Base URL of the FastAPI service as reached from the Next.js server (never exposed to the browser). */
  API_URL: z
    .url({ message: "must be a valid URL, e.g. http://localhost:8000" })
    .default("http://localhost:8000"),
  /** Product name is configurable ("Freelancer OS" is a working name). */
  NEXT_PUBLIC_APP_NAME: z.string().min(1).max(60).default("Freelancer OS"),
});

export type Env = z.infer<typeof schema>;

export class EnvError extends Error {}

export function parseEnv(source: Record<string, string | undefined>): Env {
  const result = schema.safeParse({
    API_URL: source.API_URL || undefined,
    NEXT_PUBLIC_APP_NAME: source.NEXT_PUBLIC_APP_NAME || undefined,
  });
  if (!result.success) {
    const lines = result.error.issues.map((i) => `  - ${i.path.join(".")}: ${i.message}`);
    throw new EnvError(
      `Invalid environment configuration. Fix these variables (see .env.example):\n${lines.join("\n")}`,
    );
  }
  return result.data;
}

let cached: Env | undefined;

/** Validated environment, parsed once per server process. */
export function getEnv(): Env {
  cached ??= parseEnv(process.env);
  return cached;
}
