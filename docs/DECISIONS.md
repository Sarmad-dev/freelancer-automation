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

## D37 — Deals are opportunities created from leads; stage moves are checked, never patched
A lead is a person or company you might work with; a deal (opportunity) is a piece of work you might win from it, with a value, a chance and a close date. Deals change stage only through `move` and `reopen`, which enforce the rules in one place: the stage must exist in this workspace, a closed deal must be reopened explicitly, and a lost deal can carry a reason. Every move is written to the deal's and the lead's timeline.

## D38 — Concurrent moves are decided by the client's view of the world
A board can be stale (another tab, another day). Every move carries `expected_stage_id`; if the deal is no longer there the answer is 409 `stale_stage` and nothing changes, so a drag on an old board can't silently undo someone else's move. The row is also locked during the check on PostgreSQL. No version column was needed.

## D39 — Money is exact, per currency, and a probability is never guessed
Values are `NUMERIC(14,2)` and travel as strings. Totals are grouped by currency and never added across currencies. The chance of winning is the user's own number; deals without one are simply left out of weighted totals (and said so) instead of being given a stage-based default that looks like knowledge.

## D40 — Wall-clock times are resolved in the zone they were meant in
A task due "9am Monday, Europe/Berlin" is stored as a UTC instant plus the zone name. The API accepts either an exact instant or a wall-clock time with a zone; a time that clocks skip is rejected rather than shifted, a repeated hour resolves to its first occurrence. "Today" is the local day in the zone being viewed (23 or 25 hours on clock-change days). Overdue = already past due; Today = still due before local midnight; Upcoming = later: the buckets never overlap.

## D41 — Task creation is idempotent by client key
The task form generates a key once when it opens and sends it with every submit. The same key returns the original task (200 instead of 201); the same key with a different task is a 409. The database's unique `(workspace, key)` decides races, so a double click, a retry after a flaky connection, or two tabs can't create duplicates.

## D42 — Task notifications are produced when notifications are read
Until a job runner exists (Prompt 11) the API creates "task due" and "task reminder" notifications lazily when the unread count or list is requested, with one dedupe key per (task, kind, instant), looking back 14 days and capping each read at 50. Completing, dismissing or rescheduling a task marks its pending notifications read. The same function can be called from a scheduled job later without any change in behaviour.

## D43 — Domain code talks to `AiService`, never to a vendor
All model use goes through one service with six typed tasks. A provider only has to turn a prompt into text (`complete`); everything else — prompts, validation, retries, fallback, metering — is ours and identical for every vendor. The default is a labelled rule-based stand-in so the product works and is testable without credentials; production defaults to `disabled`, and `mock` is refused there so fake output can never pass as AI.

## D44 — Model output is validated, never repaired, and never executed
A reply must be JSON that matches the task's schema exactly (one ```json fence is tolerated), then pass task checks (fields cited exist; facts cited were supplied; numbers, links and addresses in a draft must come from supplied facts; extracted facts need an exact source quote). Anything else is discarded and retried within a small bound. Results are suggestions: nothing in the AI layer sends, saves, approves or changes records.

## D45 — Prompt injection is handled by structure, not by detection
Untrusted text is minimised (no addresses, phones, URL queries), fenced with a per-call random boundary, and described to the model as data; the output is then validated as above. An injection phrase detector exists only to warn the person and cap confidence. Two things are deterministic because a mistake is costly: an explicit opt-out is always classified `unsubscribe`, and a recommendation to contact someone who opted out is replaced.

## D46 — Only classification has a fallback; drafts are never templated
When the provider is down, classification falls back to labelled keyword rules (confidence ≤ 0.6) because a rough category is better than none. Drafting, fit, extraction and summaries fail with a clear message instead of producing look-alike text: a templated "AI draft" would be an unsupported claim about what the system knows.

## D47 — Usage is metered without content
Each call writes a `usage_records` row (task, provider, model, prompt version, tokens when reported, estimated cost, latency, success, short error code) and one log line of the same metadata. Prompts, emails and replies are never stored or logged and no setting enables it. Metering failures never fail the user's request.

## D48 — The gateway adapter targets the common chat-completions shape and is labelled unverified
The playbook names "Jev" as the preferred gateway, but no credentials or verified documentation were available. The adapter speaks the widely used OpenAI-compatible shape, is tested against a simulated server only, does not follow redirects, never copies response bodies into errors, and the docs say plainly that no live provider has been evaluated. `python -m app.cli ai-eval` is the check to run before trusting one.

## D49 — The demo mailbox is a real connector, kept apart from real data
Demo mode runs through the same `EmailConnector` interface as a real provider, so everything above it (sync, linking, drafts, sending) is exercised by the demo. It is separated from real data by an `is_demo` account, the `demo` provider, `is_sample` rows and a `demo` delivery state; a demo account can never be synced or sent from by a real connector, or vice versa. Its sends are simulated and say so.

## D50 — Real providers are labelled unverified until used end to end
The Gmail adapter is written from the documented API and tested against simulated responses. The product says "Not verified live", reports `Connected` only after a real provider call succeeded, and `docs/EMAIL.md` lists the checks that must pass with a real account before anyone claims live sync. Menus, scopes and token lifetimes are Google's to change; the docs say they must be re-checked.

## D51 — OAuth state lives on the server and the grant must be complete
The `state` is a single-use, expiring record in the encrypted credential store, bound to the user and workspace that started it, checked in constant time, and deleted whatever happens; PKCE protects the code exchange. A grant missing a required scope (people can untick permissions on Google's screen) or a refresh token is refused rather than saved half-working. The redirect back to the web app is a relative path with no code, state or provider text, and the access log redacts the callback's query.

## D52 — Least-privilege Gmail scopes: read and send, not compose
`gmail.readonly` (conversations) and `gmail.send` (only approved messages) are requested; `gmail.compose` is not, so provider-side drafts are not offered. Fewer permissions are easier to justify to users and to Google, and Freelancer OS keeps its own drafts anyway.

## D53 — A send is recorded before it happens, and ambiguity is never retried
Approval binds to a hash of recipient, subject and body, so what is sent is exactly what was approved. The attempt is committed as `queued` with its idempotency key before the provider is called; a repeated key returns the earlier outcome. Definite failures clear the key and keep the same message row (a retry cannot create a second message); an ambiguous result (timeout, 5xx, unexpected error) is stored as `unknown`, blocks any new key, and waits for the owner to check the mailbox and say what happened. Suppression, send limits and mailbox state are checked server-side at send time.

## D54 — Revocation and disconnect never depend on the provider being reachable
A failed token refresh (`invalid_grant`) moves the account to `needs_reauth` and stops provider calls. Disconnect deletes our copy of the credentials even if revocation could not be confirmed, and says so; keeping a credential because a provider is down would be worse than asking the person to remove access on the provider's side.


## D55 — Message bodies are stored cleaned, in their own table, and can be deleted
Prompt 9 kept only metadata and a snippet. The inbox needs readable threads, so a cleaned body is stored per message in `message_bodies` (text normalised and capped; HTML rebuilt by an allow-list sanitiser). It is separate so an owner can delete synced mail (`DELETE …/email/accounts/{id}/mail`) without touching classifications or the audit trail. Attachments stay metadata only. Logs and audit never carry message content.

## D56 — HTML is sanitised on the server and still rendered in a sandbox
The server removes scripts, styles, forms, event handlers, unsafe URL schemes and relative links, and **removes images and all remote content** (a flag says so) so reading mail never contacts a third party or reveals that it was read. The web app shows formatted HTML only inside a sandboxed iframe with a restrictive CSP; plain text is the default. Two independent layers because a sanitiser bug alone must not become cross-site scripting.

## D57 — Classification runs as database-backed jobs
One `email_jobs` row per (message, kind), claimed with a conditional UPDATE under a 5-minute lease, retried with backoff, and failed into a human review state (`classification_failed`) rather than guessed. A DB queue needs no new infrastructure and survives restarts; workers run after a sync request returns or via `python -m app.cli process-jobs`. A scheduler and external queue arrive with Prompt 11.

## D58 — Uncertain results go to a person, with a reason
Low confidence (< 0.7), a rule-based fallback, suspected injection, an unconfirmed unsubscribe, or a failed job flag the conversation `needs_review` with a stable reason code. The model must quote evidence that really appears in the message or its result is rejected.

## D59 — Only a deterministic opt-out rule can suppress automatically
An unsubscribe puts the sender on the do-not-contact list only when an explicit opt-out phrase is found by the rules; a model saying "unsubscribe" alone yields `needs_review`. A bounce notice from a mail-system sender suppresses the last outbound recipient. A person can still classify manually. Suppression is checked again server-side at send time regardless of what the UI showed.

## D60 — Suggested replies are ordinary drafts
A reply suggestion calls `draft_outreach` with the incoming message fenced as untrusted data and approved facts only, and stores the result as an AI draft that must be edited or approved and then sent through the Prompt 9 guard (approval hash, idempotency, suppression). The facts used are returned so the UI can show them. Nothing in the inbox sends mail.

## D61 — One follow-up gate for future automation
`follow_ups.check()` is the single place that decides whether an automated follow-up may go: not if the recipient is suppressed, not if they replied after our last message. Workflows (Prompt 11+) must call it; no sequence engine exists yet.
