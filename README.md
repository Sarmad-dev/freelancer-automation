# Freelancer OS

AI-assisted CRM and visual workflow automation for independent freelancers (working name, configurable).
Blueprint and build prompts: [`freelancer_os_build_prompt_playbook.md`](freelancer_os_build_prompt_playbook.md).
Project docs: [`docs/`](docs).

> Status: **scaffold only** (MVP Prompt 1). No product features yet.

## Prerequisites
- Node.js ≥ 20.11 and [pnpm](https://pnpm.io) 10 (`corepack enable`)
- Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/)
- Docker (for local PostgreSQL + Redis), or your own PostgreSQL 16 (UTF-8) and Redis 7

## Quick start
```bash
cp .env.example .env           # development-only defaults; nothing secret
pnpm install
(cd apps/api && uv sync)       # Python dependencies

pnpm db:up                     # PostgreSQL + Redis via Docker Compose
pnpm db:migrate                # apply migrations to an empty database
pnpm db:seed                   # optional, idempotent dev seed

pnpm dev:api                   # http://localhost:8000  (docs at /docs)
pnpm dev                       # http://localhost:3000  (second terminal)
```
Verify: `curl localhost:8000/health`, `curl localhost:8000/ready`, `curl localhost:3000/api/health`, and open
http://localhost:3000 — the page should report API connectivity as **Connected**.

## Scripts
| Command | Purpose |
|---|---|
| `pnpm dev` / `pnpm dev:api` | Run web / API with reload |
| `pnpm format` / `pnpm format:check` | Prettier + ruff format |
| `pnpm lint` | ESLint (all packages) + ruff |
| `pnpm typecheck` | `tsc` (all packages) + mypy (strict) |
| `pnpm test` | vitest (all packages) + pytest |
| `pnpm build` | Production build |
| `pnpm check` | All of the above — what CI runs |
| `pnpm db:migrate` / `db:downgrade` / `db:seed` | Alembic upgrade head / roll back one / seed |
| `pnpm contracts:generate` / `contracts:check` | Regenerate / verify OpenAPI types |

## Testing against PostgreSQL
API tests default to a throwaway SQLite file for speed. To run them (including migrations) on PostgreSQL:
```bash
TEST_DATABASE_URL=postgresql://freelancer:freelancer@localhost:5432/freelancer_os_test pnpm test:api
```
(create the `freelancer_os_test` database first; CI does this automatically).

## Migrations
- Create: `cd apps/api && uv run alembic revision --autogenerate -m "describe change"` — review the output.
- Apply: `pnpm db:migrate`; roll back one revision: `pnpm db:downgrade`.
- Never edit an applied migration; add a new one. Databases must be UTF-8.

## Secrets
No secrets are committed. `.env` is git-ignored; `.env.example` contains names and safe placeholders only.
Production requires a random `APP_SECRET_KEY` (the API refuses to start otherwise).

## Layout
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
