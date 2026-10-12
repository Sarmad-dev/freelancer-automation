# Decisions

Format: context → decision → consequences. Newest last.

## D1 — pnpm workspaces + Turborepo for the JS side
Playbook suggests a Turborepo-style monorepo. pnpm gives strict dependency isolation and fast installs; Turbo
orchestrates `lint`/`typecheck`/`test`/`build` with caching. Python is deliberately **not** part of the JS
workspace; root scripts shell out to `uv`.

## D2 — "Just-in-time" internal packages (TypeScript source, no build step)
`ui`, `contracts` and `workflow-core` export `src/index.ts`; Next compiles them via `transpilePackages`.
Fewer moving parts now. Revisit if a non-Next consumer (Electron main process, worker) needs compiled output.

## D3 — uv + pyproject.toml for the API; SQLAlchemy pinned to `<2.1`
uv for locking and running. SQLAlchemy 2.1.x was released recently; during the scaffold we pinned to the 2.0
series (matches the playbook's "2.x") rather than adopt a brand-new minor release. Lift the pin deliberately.

## D4 — psycopg 3 as the PostgreSQL driver
`postgresql://` URLs are normalised to `postgresql+psycopg://`. Note: databases must use UTF-8 encoding
(the official Docker image does by default); a SQL_ASCII database makes psycopg return bytes and breaks
SQLAlchemy's dialect initialisation.

## D5 — Contracts from OpenAPI, committed, with a drift check
Generated types are committed so the web build never needs the Python toolchain; CI regenerates and diffs.

## D6 — Fail-fast configuration
Both services validate environment at startup with messages that name the variable and point to `.env.example`.

## D7 — Database-backed vs Redis queue: deferred
The MVP queue choice (MVP Prompt 11) is intentionally not made in the scaffold. Redis is provisioned so either
choice remains open.

## D8 — Geist font via the `geist` npm package
Self-hosted by the package, so builds do not need network access to Google Fonts.

## D9 — Auth: API-owned opaque server-side sessions (decided in MVP Prompt 3)
Alternatives considered: Auth.js/NextAuth in the web app, a hosted IdP, or JWTs. We chose first-party
sessions in FastAPI because the API is the only place that can enforce workspace isolation for every
data access, server-side sessions are instantly revocable (sign-out, password reset), and nothing secret
reaches the browser. Cost: we own password handling, rate limiting and reset flows (documented in
SECURITY.md). A hosted IdP/SSO can later be added behind the same session interface.

## D10 — Radix primitives + Tailwind for accessible components
Radix (dialog, dropdown, tabs, tooltip, checkbox, toast) and cmdk provide tested keyboard/focus behaviour;
we own the styling. Native `<select>` is used for Select for best AT support. Components live in
`packages/ui` so the future Electron shell reuses them.

## D11 — Themes via CSS variables + `data-theme`
Dark is the default. A tiny inline script sets `data-theme` before paint; React owns later changes with
`useSyncExternalStore` (no setState-in-effect). Components use semantic Tailwind utilities (`bg-surface`,
`text-muted`) so adding a theme means editing one token file.

## D12 — Planned destinations are real routes with honest placeholders
All 11 playbook destinations exist with stable URLs, marked "Soon" in the nav and "Planned" on the page.
Auth pages are disabled visual shells until MVP Prompt 3. The `/design-system` page is dev-only.

## D13 — Same-origin proxy instead of browser→API CORS
The browser calls `/api/v1/*` on the Next.js origin, which forwards to the API at runtime-configured
`API_URL`. Keeps cookies first-party, avoids third-party-cookie breakage, hides the API address, and lets
us allow-list paths. Cost: one extra hop and a small, tested proxy handler.

## D14 — Hard navigation at authentication boundaries
Sign-in/up/out and finishing onboarding use `window.location.assign`. A soft `router.replace` +
`router.refresh` raced and could leave a blank page (reproduced in the browser test), and a hard navigation also
discards the client router cache so no authenticated page can be shown after sign-out.

## D15 — Cookie lifetime = absolute session cap; idle expiry server-side only
Server-rendered pages cannot set cookies, so a short sliding cookie could expire in the browser while the
session was still valid. See SECURITY.md.

## D16 — Onboarding data model
Onboarding answers write straight into `freelancer_profiles` (extended in MVP Prompt 5); `onboarding_progress`
tracks status/steps. List-shaped answers are JSON columns for now (portable across SQLite/PostgreSQL); revisit
if they need querying. Resume point is computed from completed steps, not trusted from the client.
