# Implementation status

_Last updated: MVP Prompt 5 (freelancer profile and approved knowledge)._

## Completed — MVP Prompt 5: freelancer profile and approved knowledge
- **API (owner writes, members read; all workspace-scoped):** `GET/PATCH /profile` (optimistic `expected_version`),
  `GET /profile/summary` (public-facing preview built only from entered, non-private fields), `GET /ai-context`;
  knowledge CRUD with filters/sort/search, `GET /knowledge/stats`, `POST /knowledge/import-text`,
  `POST /{id}/approve` (bound to the reviewed version), `POST /{id}/reject`, `GET /{id}/versions`, delete.
- **Approval model:** `draft/pending_review/approved/rejected` + independent `is_enabled`; editing approved content returns it
  to review; every version is snapshotted. See [DATA_MODEL.md](DATA_MODEL.md) and decisions D25–D29.
- **AI context builder** (`services/ai_context.py`): the only gate. Includes approved + enabled facts and filled profile
  fields; reports what is missing and how many items were excluded; deterministic hash; size budget. It never selects
  unreviewed, rejected, disabled or private material, and nothing in the app invents case studies, names or outcomes.
- **No AI provider needed:** import splits pasted text verbatim into items that need review.
- **Safety:** URLs validated server-side (public http(s) only) and re-validated in the browser; all stored text rendered
  as text; invisible/bidi characters stripped; audit details carry no content.
- **Web:** AI Workspace is now live with Overview, Profile (sectioned editor, unsaved-changes guard, conflict banner,
  live public-summary preview, "what the AI may use") and Knowledge (filters, pagination, status badges, enable switch,
  review/edit drawer with provenance and history, add, import, delete with confirmation). New shared `Switch`.
- **Seed:** the fictional demo profile and six knowledge items covering approved, switched-off, pending (extracted),
  draft and rejected, each with history.
- **Migration `0004`:** hand-reviewed; converts legacy `disabled` rows, backfills version 1 history; reversible.

## Verification: MVP Prompt 5
- API: 580 pytest tests pass on **SQLite and PostgreSQL 16 and on Python 3.12 and 3.13**; ruff and mypy (strict) clean;
  OpenAPI document byte-identical on 3.12 and 3.13. Highlights: workspace isolation for every endpoint (including a second
  workspace's ids), member read-only, approval status rules and version binding, stale-version conflicts, deletion + history
  cascade, invalid/unsafe URLs, invisible-character stripping, AI-context selection (only approved + enabled, private fields
  excluded, hash stable, truncation), migration upgrade/downgrade with legacy data on both databases, drift check.
- Mutation checks: removing the tenant filter, admitting every status into the context, and ignoring `is_enabled` each made
  tests fail.
- Web: 139 vitest tests (new: model, profile editor, knowledge manager incl. inert markup, conflict, delete confirmation,
  axe) and 29 ui tests (Switch). Lint, typecheck, format and production build pass.
- Real browser (Chromium via Playwright): axe (WCAG 2 A/AA, best practice) clean on Overview/Profile/Knowledge (+filter
  states) at 1440/820/390 px in dark and light themes with no page-level overflow; end-to-end add -> invalid link error ->
  save -> approve -> switch off/on -> edit approved (returns to review) -> import -> delete, checked against the database; a
  `<img onerror>` title stayed inert. Bugs found and fixed this way: heading order in the summary preview (h2 -> h4), and
  a visually-hidden table header escaping the scroll container and causing horizontal page scroll on mobile.

## Not verified / known gaps (Prompt 5)
- No file upload or URL fetching: "upload"/"extracted" provenance exists in the model but only text import is wired; model-based
  extraction arrives with the AI prompts and must reuse the `pending_review` path.
- Single owner per workspace in practice: member role behaviour is covered by API tests, not by a browser run.
- Knowledge search is substring matching (no full-text index). Offset pagination.
- No diff view between versions; history shows snapshots only.
- Deleting a knowledge item does not (yet) invalidate drafts that quoted it (there are no drafts until later prompts).
- The profile "public summary" is a preview only; there is no public page.

## Completed — MVP Prompt 4: database domain model and API foundations
- **Schema (migration `0003_domain_model`):** 26 new tables: knowledge, companies, contacts, leads, tags/lead_tags,
  activities, tasks, opportunities, pipeline stages, email accounts/conversations/messages/drafts/suppression,
  integration connections, credential secrets, workflows/versions/nodes/edges/runs/step runs/approvals, usage, notifications.
  Documented in [DATA_MODEL.md](DATA_MODEL.md) (tenancy, retention/deletion, rollback, evolution).
- **Tenant isolation in the database:** composite `(workspace_id, id)` foreign keys; CASCADE from workspaces; unique
  constraints for provider ids/duplicates/idempotency; CHECK constraints for statuses and ranges.
- **Credential store:** encrypted (Fernet), workspace+purpose-bound, rotation, key config; no secret-like column exists
  anywhere (tested).
- **API foundations:** `Page[T]` pagination, allow-listed multi-field sorting, filters, workspace scoping helpers,
  consistent errors; reference resources `tags` (CRUD) and `pipeline/stages`; default stages created at sign-up and
  backfilled for existing workspaces. See [API_CONVENTIONS.md](API_CONVENTIONS.md).
- **Seed:** fictional freelancer + `.example`-only companies/contacts across every table, all flagged `is_sample`,
  development/test only, idempotent.
- **Contracts:** OpenAPI + generated TypeScript regenerated and type-tested.

## Verification: MVP Prompt 4
- API: 421 pytest tests passing on **SQLite and PostgreSQL 16** (and on Python 3.12 and 3.13): 126 structural schema
  guards (tenancy, cascade, indexes, composite FKs, no secrets, timestamps, CHECKs; they also protect future tables),
  97 behavioural constraint tests (18 uniqueness rules, 30 cross-tenant references refused by the database, 29 invalid
  values refused, cascades, restrict rules, a fully seeded workspace deleted to prove every cascade), credential store
  (encryption, tamper/transplant detection, rotation), pagination/sort/filter/isolation through the HTTP API,
  seed (idempotent, fictional-only, dev-only), migration backfill + rollback + repeatability, model/migration drift.
- A mutation check (removing the tenant filter) made 6 isolation tests fail and 14 error, so the guards do detect regressions.
- Bugs found by these tests and fixed: (1) deleting a workspace through the ORM failed (missing `passive_deletes`), which
  would have broken data-erasure; (2) the stage backfill crashed on SQLite databases that already had workspaces
  (string vs UUID ids); (3) validation errors for tagged-union bodies used a dotted key (fixed in Prompt 3).

## Not verified / known gaps (Prompt 4)
- No CRUD endpoints yet for leads/contacts/tasks/etc. (their prompts add them using the conventions above); only tags and
  stage listing exist as the reference implementation.
- Offset pagination only; no keyset cursors. No full-text/trigram search indexes yet (queries are undefined until Prompt 6).
- Message bodies, attachments binary storage, and saved views/custom fields are intentionally not modelled.
- The credential store keeps keys in the environment (no KMS); nothing stores real credentials yet (email connector is Prompt 9).
- PostgreSQL row-level security is not used (see D17). Composite-FK tenancy was verified with cross-tenant inserts, not a
  penetration test.
- The migration was run against PostgreSQL 16 and SQLite only.

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
MVP Prompt 6 — leads (see the playbook).

## Commands
See the README. Migrations: `pnpm db:migrate`, rollback one step: `pnpm db:downgrade`.
