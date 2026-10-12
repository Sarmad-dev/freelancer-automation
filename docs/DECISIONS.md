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

## D9 — Auth approach: deferred to MVP Prompt 3
No session/auth code in the scaffold; CORS allows credentials only for configured origins.

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
