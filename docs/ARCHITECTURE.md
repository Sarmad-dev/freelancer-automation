# Architecture (scaffold)

## Layout
```
apps/
  web/   Next.js 16 (App Router) + React 19 + strict TypeScript + Tailwind 4
  api/   FastAPI + Pydantic v2 + SQLAlchemy 2.0 + Alembic (managed with uv / pyproject.toml)
packages/
  ui/              design tokens (dark default + light) and first primitive (Button)
  contracts/       OpenAPI document exported from FastAPI + generated TS types + typed client
  workflow-core/   workflow definition schema (zod) + structural validator
  shared-config/   tsconfig base + ESLint flat config
docs/              PROJECT / ARCHITECTURE / DECISIONS / IMPLEMENTATION_STATUS
infra/scripts/     helper scripts (contract drift check)
```
Not yet created (added when needed): `apps/desktop`, `packages/workflow-editor`, `services/worker`.

## Runtime
```
Browser ──► Next.js server ──(API_URL, server-side)──► FastAPI ──► PostgreSQL
                                                          └──────► Redis
```
- The browser never learns `API_URL`; the web server calls the API (the home page performs a readiness check).
- API probes: `GET /health` (liveness, no dependencies) and `GET /ready` (PostgreSQL + Redis, 503 when degraded,
  error details never include connection strings). Web probe: `GET /api/health`.
- Every API response carries `X-Request-ID` (client value accepted only if `[A-Za-z0-9._-]{1,64}`).

## Authentication and tenancy (MVP Prompt 3)
The API owns identity and server-side sessions; the browser reaches it through a same-origin Next.js
proxy (`/api/v1/*`) so the HttpOnly session cookie is first-party. Full details, threat notes and known gaps:
[SECURITY.md](SECURITY.md). Workspace-scoped routes live under `/api/v1/workspaces/{id}/...` and are
authorised by membership. Error responses use one envelope, `{"error": {"code", "message", "fields?"}}`.

## Data model and API foundations (MVP Prompt 4)
35 tenant-aware tables; tenancy is enforced by the database (composite `(workspace_id, id)` foreign keys, cascades,
unique constraints) as well as by code. Secrets live only in an encrypted credential store. List endpoints share one
pagination/sorting/filter contract and error envelope. Full details: [DATA_MODEL.md](DATA_MODEL.md),
[API_CONVENTIONS.md](API_CONVENTIONS.md).

## Profile, knowledge and AI context (MVP Prompt 5)
Routers `profile` and `knowledge` call `services/profile.py`, `services/knowledge.py` (lifecycle, import) and
`services/ai_context.py` (the only selector of AI input; see D27). The web app's AI Workspace has three route-based tabs
(Overview, Profile, Knowledge). Pages are server components that read through the typed client with the visitor's session
cookie (`lib/server-api.ts`, `lib/workspace.ts`); editing UIs are client components that mutate through the same-origin
proxy and then `router.refresh()`. Stored text is always rendered as React text nodes, and links are re-validated to
http(s) in the browser (`lib/safe-url.ts`).

## Leads, scoring and import (MVP Prompt 6)
`routers/leads|companies|contacts|fit_scoring|imports` call `services/crm.py` (companies/contacts: find-or-create, duplicates, serialisation), `services/leads.py` (lead rules, stage sync, timeline, tags), `services/fit_scoring.py` (pure scoring functions plus config persistence), `services/lead_import.py` and `services/csvio.py` (strict CSV reading/writing) and `services/lead_export.py`. Scoring, import and export are plain functions of the database and the request, so they run the same from an API call, a test, or later from the workflow engine. In the web app, `/leads` is a section with four tabs (Leads, Companies, Contacts, Fit scoring) plus detail pages and the import wizard; list pages are server components driven by validated URL parameters, so filters, sorting and pagination are links and work without JavaScript.

## Contracts
FastAPI is the single source of truth. `pnpm contracts:generate` exports `packages/contracts/openapi.json`
and regenerates `src/generated/api.d.ts` (openapi-typescript). The web app uses `openapi-fetch` through
`createApiClient`. `pnpm contracts:check` (run in CI) fails when the committed output is stale.

## Configuration
One root `.env` (see `.env.example`). API: `pydantic-settings` validates at import/startup and raises an
actionable `ConfigError`; production additionally requires a strong `APP_SECRET_KEY` and forbids wildcard CORS.
Web: zod validation in `src/env.ts`, executed from `instrumentation.ts` so the server refuses to start with bad
config. Internal packages ship TypeScript source and are compiled by Next (`transpilePackages`), so there is no
per-package build step.

## Database
SQLAlchemy 2.0 declarative models with deterministic constraint names; Alembic migrations in
`apps/api/alembic/versions`. Migrations `0001`-`0003` create the scaffold, identity/onboarding and the full MVP domain (see DATA_MODEL.md).

## Known limitations
- Docker Compose provides PostgreSQL and Redis only; app containers are not provided yet.
- No background worker or queue yet; email verification, MFA and a mail provider are not implemented (see SECURITY.md).
- Redis backs the rate limiter in production (in-memory in dev/test) and the readiness check.
