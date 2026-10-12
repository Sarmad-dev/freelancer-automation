# Implementation status

_Last updated: MVP Prompt 2 (design system and app shell)._

## Completed — MVP Prompt 2: design system, app shell, navigation
- **Tokens/themes:** `packages/ui/src/tokens.css` (dark default, designed light theme), mapped to Tailwind
  semantic utilities via `@freelancer-os/ui/styles.css`. Light-theme accent/success/warning were darkened so
  status text on tinted badges meets WCAG AA (tests enforce this on every surface in both themes).
- **Theme switching:** Dark / Light / System, persisted in localStorage (blocked storage tolerated), applied by a
  pre-paint inline script so there is no flash. Reduced-motion honoured globally.
- **Components (`packages/ui`):** Button, Input, Textarea, Select (native), Field (label/hint/error wiring),
  Checkbox, Modal, ConfirmDialog (Cancel focused first), Drawer, DropdownMenu, Tabs, Tooltip, Badge, Toasts,
  Skeleton/TableSkeleton, EmptyState, ErrorState, PermissionDeniedState, Notice, PlannedFeature, PageHeader,
  Breadcrumbs, Table primitives, TableToolbar, FilterChips, Pagination, CommandPalette. Dialogs/palette return
  focus to the element that opened them.
- **App shell (`apps/web`):** responsive sidebar (workspace switcher, 11 primary destinations, collapse with
  persistence, status panel; off-canvas drawer below `lg`), top bar (breadcrumbs, Ctrl/⌘+K command palette,
  notifications empty-state menu, help, theme, account menu), skip link, route-level `loading`, `error`,
  `not-found`, `global-error`.
- **Routes:** Home (real API status), 10 placeholder destinations clearly marked "Soon"/"Planned" (no fake
  functionality), `/sign-in`, `/sign-up`, `/onboarding` as **disabled visual shells** (auth is MVP Prompt 3),
  `/design-system` reference page (404s in production unless `ENABLE_DESIGN_SYSTEM_PAGE=1`).

## Verification — MVP Prompt 2
- Unit/component tests: ui 28, web 18 (jsdom + axe-core structural checks, focus management, palette,
  persistence, blocked storage).
- Real Chromium via Playwright (scripts were run ad hoc, not committed): axe-core (WCAG 2.0/2.1 A/AA + best
  practices, **including colour contrast**) on 7 routes x desktop/tablet/mobile x dark/light = 0 violations; no
  horizontal overflow; keyboard/interaction checks (skip link, theme persistence across reload, sidebar
  collapse persistence, Ctrl+K navigation, dialog focus trap + focus return, toasts, filter chips, pagination,
  mobile drawer, reduced motion) all passed; no console errors.
- Not verified: Safari/Firefox, screen-reader testing with real AT, and the collapsed-sidebar state is applied
  after hydration (brief expanded->collapsed shift is possible on first paint for users who collapsed it).

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
- No authentication, tenancy, business entities, worker or queue (later phases). 

## Next
MVP Prompt 3 — authentication, workspace and onboarding.

## Commands
See the README. Migrations: `pnpm db:migrate`, rollback one step: `pnpm db:downgrade`.
