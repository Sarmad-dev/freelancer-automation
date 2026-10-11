# Implementation status

_Last updated: MVP Prompt 1 (scaffold)._

## Completed — MVP Prompt 1: repository scaffold and local development
- pnpm + Turborepo monorepo; `apps/web`, `apps/api`, `packages/{ui,contracts,workflow-core,shared-config}`.
- FastAPI app factory, `/health`, `/ready`, request-id + nosniff middleware, restricted CORS, docs disabled in production.
- Environment validation (API: pydantic-settings; web: zod via `instrumentation.ts`).
- SQLAlchemy 2.0 + Alembic (`0001_app_metadata`), idempotent `seed` command (refuses in production).
- OpenAPI export → generated TS types → typed client; `contracts:check` drift script.
- Design tokens (dark default, light alternative, WCAG AA contrast test), `Button`, `cn`.
- `workflow-core`: workflow definition schema + structural validator (trigger, edges, reachability, cycles,
  condition branches, approval-before-send).
- Web home page that checks API readiness (connected / degraded / unreachable states).
- Docker Compose for PostgreSQL 16 + Redis 7; GitHub Actions CI.

## Verification performed
Run against real PostgreSQL 16 and Redis 7 (not Docker — the sandbox has no Docker daemon):
API tests (15), migrations upgrade/downgrade/upgrade from an empty DB, seed twice, `/ready` 200,
web build + start, web → API "Connected", API down → "Unreachable", invalid `API_URL` → refuses to start.
JS: lint, typecheck, vitest (workflow-core 8, ui 5, contracts 1, web 5), `next build`.

## Not verified / known gaps
- `docker compose up` itself was only syntax-checked (`docker compose config`), not run.
- CI workflow has not run on GitHub yet.
- No authentication, tenancy, business entities, worker or queue (later phases). No light/dark toggle UI yet (Prompt 2).

## Next
MVP Prompt 2 — design system, app shell and navigation.

## Commands
See the README. Migrations: `pnpm db:migrate`, rollback one step: `pnpm db:downgrade`.
