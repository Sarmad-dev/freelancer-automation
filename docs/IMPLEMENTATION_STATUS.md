# Implementation status

_Last updated: MVP Prompt 3 (authentication, workspace, onboarding)._

## Completed — MVP Prompt 3: authentication, workspace, onboarding
- **Auth (API-owned, see [SECURITY.md](SECURITY.md)):** sign-up, sign-in, sign-out, `GET /auth/me`, password
  reset (request/confirm), `GET /auth/config`. Argon2id, opaque server-side sessions (HttpOnly/SameSite=Lax
  cookie, hashed at rest, idle + absolute expiry, rotated on sign-in, revoked on sign-out/reset), CSRF origin/header
  check, per-account/IP rate limiting (memory or Redis), enumeration-resistant sign-in and reset.
- **Tenancy:** `users`, `workspaces`, `memberships` (role-ready, owner-only in MVP), personal workspace created
  at sign-up; workspace routes authorised by membership with indistinguishable 404s.
- **Onboarding:** 10 steps (role, services, skills, target clients, industries, portfolio, experience, tone,
  time zone, goal; 7 required), validated server-side, resumable, skippable ("finish later"), demo-mode toggle,
  progress persisted in `onboarding_progress` / `freelancer_profiles`.
- **Audit:** `audit_events` with an allow-listed details payload; no credentials or profile content.
- **Web:** real sign-in/sign-up/forgot/reset pages, onboarding wizard, same-origin API proxy
  (`/api/v1/*`), `proxy.ts` route gate + authoritative server-side session check in layouts, session-aware
  shell (workspace name, account menu, sign-out, "finish setup" banner), open-redirect-safe `next` handling.
- **Migration `0002_auth_and_onboarding`** (rollback: `alembic downgrade 0001` drops these tables and their data).
- **API conventions introduced:** one error envelope `{"error": {"code", "message", "fields?"}}`; typed OpenAPI
  contracts regenerated.

## Verification — MVP Prompt 3
- API: 140 pytest tests on SQLite and on PostgreSQL 16 (auth/session/CSRF/reset/rate limit, onboarding
  validation, resume, workspace isolation with two real users, audit redaction, model/migration drift check,
  production config refusals).
- Web: 91 vitest tests (forms, wizard, proxy path/header allow-listing, open-redirect guard, shell, axe).
- Real browser (Chromium + real API/PostgreSQL/Redis), 43 checks, all passing: route protection, cookie flags
  (HttpOnly, SameSite=Lax; unreadable from JS), no token/password in storage or HTML, sign-up → onboarding →
  finish later → resume → complete, server-side validation errors in the UI, SSRF-style URLs rejected, DB holds
  argon2id hash and no raw session token, audit trail, cross-user isolation through the proxy, forged
  cross-origin sign-out rejected, back-button after sign-out, replayed cookie rejected, open-redirect neutralised,
  idle and absolute expiry, full password-reset flow (single-use link).
- axe-core incl. colour contrast, 6 screens x 3 widths x 2 themes: 0 violations, no horizontal overflow.
- A browser test found and fixed a real bug: `router.replace` + `router.refresh()` after sign-in could leave a
  blank page; auth boundaries now use a hard navigation (D14).

## Not verified / known gaps (Prompt 3)
- No email verification, MFA, social login, "sign out everywhere", or real mail delivery (dev console mailer
  only; production disables password reset). Sign-up reveals whether an email is registered (rate limited).
- The rate limiter fails open if Redis is down; per-IP limits need `TRUSTED_PROXY_COUNT` set correctly when
  deployed behind proxies.
- Production behaviour (`Secure`/`__Host-` cookies over HTTPS, Redis limiter) is covered by unit tests but was
  not exercised end to end over TLS here.
- The Playwright scripts used for the browser checks are not committed (no e2e suite yet; planned in Prompt 16).
- Settings page, workspace switching and team invitations remain placeholders.

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
MVP Prompt 4 — database domain model and API foundations.

## Commands
See the README. Migrations: `pnpm db:migrate`, rollback one step: `pnpm db:downgrade`.
