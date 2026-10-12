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

## D17 — Tenant isolation enforced in the database, not only in code
Every tenant-to-tenant foreign key is composite `(workspace_id, id)`, so a cross-workspace reference is
impossible even if application code is wrong. Cost: a `UNIQUE(workspace_id, id)` on referenced tables and
slightly wider keys. Guarded by structural tests that also cover future tables. Rejected alternative: Postgres
row-level security (stronger for ad-hoc SQL, but harder to run identically on SQLite and to test; revisit for teams).

## D18 — String columns + CHECK constraints instead of native enums
Portable across PostgreSQL/SQLite, readable in migrations, and changing the allowed values is a one-statement
revision. Values live in `app/domain.py`.

## D19 — UUIDv4 primary keys
Unguessable in URLs, generatable in workers, no coordination. Time-ordered ids (ULID/UUIDv7) can be adopted later by
changing `mixins.new_uuid` only.

## D20 — Credential store behind a protocol; Fernet in the database for the MVP
Meets "no raw tokens in general tables" now; envelope binds ciphertext to workspace + purpose; key rotation supported.
Production hardening is swapping in KMS/Vault behind `CredentialStore`.

## D21 — Message metadata only
No body column yet: privacy by default and a retention decision is needed first (MVP Prompt 10).

## D22 — Workflow versions stored as rows (nodes/edges), not a JSON blob
Queryable ("which workflows send email?"), referential integrity between edges and nodes, checksum for integrity.
The editor still exchanges the JSON shape from `workflow-core`; conversion lives in the (future) workflow service.

## D23 — Offset pagination with deterministic ordering
Simple and adequate for MVP data sizes; the envelope can gain a cursor additively if a list outgrows it.

## D24 — SQLite foreign-key enforcement turned on
SQLite ignores foreign keys by default. Enabling `PRAGMA foreign_keys=ON` makes the fast test database enforce the same
tenant/cascade rules as PostgreSQL (tests also run on PostgreSQL in CI).

## D25 — Knowledge approval is bound to an exact version
`POST /knowledge/{id}/approve` carries the version the user reviewed. If the item changed in the meantime the API answers 409
instead of approving content nobody saw. Editing approved content sends it back to `pending_review`, so approved text can
never silently change under the AI. History snapshots make each version reviewable.

## D26 — `is_enabled` is separate from review status
"Is this fact true and reviewed?" and "should drafts use it right now?" are different questions. A switch lets a freelancer
pause an approved fact (a retired service, a stale price) without losing the approval or forcing a re-review.

## D27 — The AI context builder is the only gate to AI input
`services/ai_context.build_context` is the single place that selects what an AI step may see: approved **and** enabled
knowledge plus filled profile fields, with a deterministic `context_hash`, a size budget and a `missing`/`excluded_counts`
report. Unreviewed extraction, drafts, rejected items and private notes are never selected. Later AI features must call it
rather than querying tables.

## D28 — Import splits text; it does not interpret it
"Import text" splits pasted material into sentences/bullets verbatim (max 25 items, 15–500 characters each, de-duplicated)
and creates `pending_review` items. No model is involved, so the feature works without an AI provider and cannot invent
case studies, client names, certifications or outcomes. When extraction by a model arrives it must use the same
`pending_review` path.

## D29 — Invisible characters are stripped from free text
Zero-width and bidi-control characters (except ZWNJ/ZWJ, needed in some scripts) are removed and control characters rejected
in all user text, so an approved fact cannot hide content from the reviewer ("what you approve is what the AI reads").

## D30 — Fit scoring is rule-based and explainable, with no model involved
A freelancer can check and tune a rule; they cannot check a model's hunch. Five criteria (service match, industry, geography, company size, budget) look only at data the user entered, produce match / partial / miss / unknown with the evidence that decided it, and combine by user-set weights. It works with no AI provider. A model may later *propose* evidence, but the score stays a function of recorded, citable facts.

## D31 — Unknown is not a miss, and too little data means no number
Criteria without data are left out of the maths; the score is rounded to the nearest 5; below half of the weighting (or fewer than two known criteria) the lead is "not enough information" with no score. A lead that mentions a client type the user excluded is capped at 25 and says so. This avoids false precision: "0" would otherwise mean "we know nothing".

## D32 — An import preview is the real import, rolled back
The preview runs the same code as the import inside the request's transaction and rolls it back, so what the wizard says will happen (creates, updates, skipped duplicates, row errors, do-not-contact warnings) is exactly what happens. The cost is that a preview of a large file does the work twice; files are capped at 5,000 rows.

## D33 — Duplicate rules are explicit and shared by every path
A contact is identified by normalised email (unique per workspace, enforced by the database); a company by website domain, then by exact case-insensitive name unless the websites differ; an email-less lead by (title, company). Manual entry, API and CSV import all go through the same find-or-create code. The import offers `skip` (default) or `update` (fill from non-empty cells, never blank, add tags, never remove).

## D34 — CSV safety and limits
Files are UTF-8 text up to 2 MB / 5,000 rows / 60 columns; unclosed quotes, stray characters after a closing quote, extra values in a row and duplicate headers are rejected or reported rather than guessed at. Every CSV the app writes (export, error report) prefixes cells that start with `= + - @` (except phone-number shapes) so a spreadsheet cannot run them. The import is synchronous: simple, atomic and fast enough at this size; larger files wait for the job runner (Prompt 11).

## D35 — Lists sort case-insensitively with NULLs last
SQLite and PostgreSQL disagree about NULL order and PostgreSQL's collation depends on the server, so name/title sorts use `lower(...)` and every sort puts NULLs last. Without it, "unscored" leads would float to the top on one database and the bottom on the other.

## D36 — Export is owner-only and counted
A lead export is bulk personal data leaving the app, so it requires the owner role, refuses more than 10,000 rows instead of silently truncating, and is audited with a count (never the content).

