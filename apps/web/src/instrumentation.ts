// Runs once when the Next.js server starts, so bad configuration fails fast with an actionable message.
export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    const { getEnv } = await import("./env");
    getEnv();
  }
}
