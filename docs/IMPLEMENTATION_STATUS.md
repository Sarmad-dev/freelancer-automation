# Implementation status

_Last updated: MVP Prompt 11 (workflow schema, validator and execution engine)._

## Completed — MVP Prompt 11: workflow schema, validator and execution engine
- **Definition and catalogue** ([WORKFLOWS.md](WORKFLOWS.md), `apps/api/app/workflows/`): a versioned graph of 12 node types (trigger, condition, AI fit, AI reply classification, AI draft, update lead / create opportunity, create task, approval gate, send approved email, delay, notify, end), each with a settings schema, output ports and the typed facts it needs and gives. `GET /workflows/catalog` exposes them to an editor.
- **Validator:** missing or invalid settings, unknown node types, duplicate ids, dangling edges, unknown ports, ambiguous and **unhandled branches**, missing trigger/end, unreachable nodes, cycles, typed-flow gaps and **unsafe sends** (an email must follow an approval gate that came after the draft, on every path). Versions can be saved with problems but only a valid one can be switched on or run. The structural checks are mirrored in `packages/workflow-core` and tested against shared fixtures (19 cases) so the editor and server agree.
- **Engine:** a run is pinned to one immutable version and records a step row (committed *before* the executor runs, finished atomically with its effect) with attempts, times, port, safe output summary, error category and a correlation id. The **queue is the database** (conditional-UPDATE claim, 5-minute lease, heartbeat, lost-lease detection); delays and retry backoff are a `wake_at`, so nothing depends on an in-memory timer or an open request. Retries with backoff only for retryable categories, per-node attempt limits, manual retry of a failed step, cancellation (a running run stops before its next step), duplicate-event protection (unique key per event, one run at a time per lead/conversation), workspace limits, owner-only changes.
- **Approvals:** a durable pause bound to a hash of the draft; only the owner decides; approving approves exactly that text; an edited draft voids the approval and the run stops; unanswered approvals expire onto the *rejected* path; cancelling a run cancels its approvals.
- **Safety:** test mode (default) simulates record changes and sending; going live needs an active workflow and an explicit, audited confirmation. A new send goes through the Prompt 9 guarded send with a per-attempt idempotency key; a send the provider never confirmed is never retried automatically and blocks manual retry until the draft is resolved. Runs, steps, approvals and audit events hold ids, enumerations and fixed error text only.
- **Triggers wired:** manual start (API), `lead_created` (leads created through the API) and `reply_received` (mail sync, once per message). Run workers with `python -m app.cli process-workflows [--loop]`; the API also starts one after requests that made runs due.
- **API:** `workflows` (catalogue, validate, CRUD, versions, activate/pause/archive/mode, start run), `workflow-runs` (list, detail with steps, cancel, retry), `approvals` (list, get, decide). Migration **0009**. Contracts regenerated. The seeded demo workflow is now a valid, inactive example.

## Verification: MVP Prompt 11
- API: 1,492 pytest tests (100 new) pass on **SQLite, PostgreSQL 16 and Python 3.12**; ruff and mypy (strict) clean; migrations 0001→0009 apply on PostgreSQL (and 0009 downgrades/upgrades). New suites: validator (41), engine (41: branching, delay resume, retries and manual retry, duplicate events, cancellation, approval resume/reject/expiry/edit, crash and lease recovery, idempotent send, unknown-outcome send, test vs live, suppression, reply-triggered run), API (18: catalogue, versions, activation rules, limits, isolation, member read-only, no content stored).
- Web/packages: 944 web tests, 43 `workflow-core` tests (incl. the shared fixtures), lint, typecheck, format and `pnpm contracts:check` pass.
- Mutation checks (each made tests fail): retry of non-retryable failures, attempt limit, lease recovery, lost-lease check, subject-busy, cancel of a running run, open approvals not cancelled on cancel, test-mode simulation, approval hash check on decide, new draft clearing a prior approval, approval expiry, each condition of the send guard (status, run, draft, hash), unresolved-send gate on manual retry, draft-edit invalidation hook, subject workspace scoping, delay due time, backoff wake time, live-mode confirmation, activating/starting an invalid version, owner-only approval decisions. Survivors found and fixed with new tests: the decision's own hash check, and the runtime clearing of an old approval when a new draft is written.
- Real process (uvicorn + PostgreSQL, demo data): a workflow assess → draft → approval → send → notify started through the API, ran in the background worker, paused at the approval, resumed after the owner approved, and finished with the send simulated (test mode); `python -m app.cli process-workflows` ran cleanly.
- Bugs found by the tests and fixed: a circular import between the event hook and the engine; the approvals list had no way to ask for "all"; manual retry stayed blocked after the unconfirmed send was resolved; the seeded workflow no longer matched the new rules.

## Not verified / known gaps (Prompt 11)
- **No editor yet (Prompt 12), no starter automations or approval-centre page (Prompt 13).** The API is exercised by tests and scripts, not a UI.
- A live-mode send is verified against the **fake provider and the demo mailbox only**; the Gmail adapter is still not verified against Google. The AI is the demo stand-in, so classification and draft quality are unmeasured.
- The queue is a polling database queue: latency is the worker's poll interval, a dead worker's run waits up to the 5-minute lease, a hung step is recovered by the lease, not killed, and `timeout_seconds` is enforced for AI calls (and flagged `slow` otherwise). It is not a distributed engine.
- `follow_up_due` is a valid trigger but nothing emits it yet; leads imported from CSV do not emit `lead_created`; no scheduler or periodic mail sync exists.
- No loops, parallel branches or sub-workflows. Saved versions accumulate (no pruning). `upsert_record` moves a stage or opens an opportunity only.
- Runs act as the workspace owner; there are no per-workflow permissions or approver roles (teams are post-MVP).

## Completed — MVP Prompt 10: inbox, reply classification and draft review
- **Inbox UI** (`/inbox`, [INBOX.md](INBOX.md)): conversation list (search, unread, needs-review, category filters, mailbox filter, paging, counts), thread view in source-timestamp order with attachment metadata, classification card (category, confidence, plain-language explanation, quoted evidence, who/what produced it, manual override, classify again), stop banner for unsubscribe/bounce/no-further-contact with an owner-only "remove from do-not-contact list", and a reply editor (suggest, regenerate, edit, save, approve, discard, send dialog with a stable idempotency key, unknown-outcome resolution, "written using" approved facts). Members see everything read-only.
- **Safe rendering:** bodies are stored cleaned (nh3 allow-list; images and remote content removed and flagged; text normalised and capped). Plain text is the default; formatted HTML is shown only inside a sandboxed iframe with a restrictive CSP. Owners can delete synced mail.
- **Pipeline:** idempotent sync stores bodies, links contacts and enqueues one classification job per message; DB-backed job queue (atomic claim, 5-minute lease, backoff, failure → needs review, superseded messages skipped); bounce detection suppresses the failed recipient; deterministic opt-out confirmation is required before anything is suppressed automatically; reply notifications; `follow_ups.check()` gate for future automation. Run workers with `python -m app.cli process-jobs [--loop]` (also run after a sync).
- **Classification:** eight categories, confidence, explanation and evidence that must really appear in the message; low confidence (< 0.7), fallback, injection suspicion, unconfirmed unsubscribe or a failed job go to review with a reason.
- **Suggested replies:** `draft_outreach` with the incoming message as fenced untrusted data and approved facts only; creates an ordinary AI draft; never sends; refused for stopped contacts or insufficient approved facts.
- **API:** `GET /inbox/counts`, `GET /inbox/conversations[/{id}]`, read/unread, `POST …/classify`, `PUT …/classification`, `POST …/suggest-reply`, `DELETE /email/accounts/{id}/mail`. Migration **0008**. Contracts regenerated.

## Verification: MVP Prompt 10
- API: 1,392 pytest tests pass on **SQLite, PostgreSQL 16 and Python 3.12**; ruff and mypy (strict) clean; migrations 0001→0008 apply on PostgreSQL. New suites: sanitiser (48), pipeline/jobs/bounce/follow-up/bodies/ordering (33), inbox API incl. isolation, members, suggest-reply, delete mail, CLI, migration and seed (~28), plus additions to AI-service and Gmail tests.
- Web: 944 vitest tests pass (inbox model, list, view, thread, message card, safe-HTML frame, classification card, stop banner and reply editor with axe); lint, typecheck, format, production build and `pnpm contracts:check` pass.
- Mutation checks (each made tests fail): unsubscribe auto-suppression without rule confirmation, review threshold off, unconfirmed-unsubscribe review off, superseded-job skip off, bounce handling off, sanitiser relative links allowed. One survivor, `dedupe_key` on reply notifications: equivalent in practice because a message is only notified once by the idempotent sync; the unique key is a second line of defence.
- Real browser (Chromium, built app, PostgreSQL): demo mailbox synced from Integrations produced six conversations classified as expected (interested, objection, out of office, unsubscribe → stopped, bounce → stopped, an injection-laden question → needs review); thread view, stop banner, "replies turned off" state, suggest reply with facts used, approve and demo send all worked with no console errors; no sideways scroll at 1440/820/390 in dark and light; axe reports one `label-content-name-mismatch` on the workspace switcher button in the app shell, which also appears on `/leads` (it is not from this prompt).
- Bugs found by tests and fixed: migration downgrade constraint naming; the seed lacked an `email_jobs` row (the every-tenant-table test caught it); a loophole letting numbers from a suspected-injection email into a reply; sanitiser let relative links through; the shell navigation tests assumed Inbox was "Soon".

## Not verified / known gaps (Prompt 10)
- **Gmail bodies and sync are still unverified against Google** (simulated responses only). The demo AI is a rule-based stand-in: classification quality and reply quality with a real model are **not measured**.
- Jobs run after sync or by a separate worker process; there is no scheduler or automatic periodic sync yet (Prompt 11). No sequence engine exists, so "replies stop follow-ups" is enforced by `follow_ups.check()` and tested, but nothing automated calls it yet.
- Attachments are listed (name, type, size) but cannot be opened. No domain-level suppression, snooze, assignment, labels, or archive UI (the API filters archived).
- The classification evidence quote can include the subject line text joined to the body (cosmetic).
- Shared `Modal` focus restoration (packages/ui) does not return focus when the dialog's own button is autofocused; the reply editor works around it for the send dialog.

## Completed — MVP Prompt 9: email integration framework and demo mode
- **Connector framework** (`apps/api/app/mailbox/`, [EMAIL.md](EMAIL.md)): an `EmailConnector` interface (authorize, callback/exchange, refresh, revoke, profile/health check, sync, fetch body, create draft, send), a capability/scope manifest per connector, a registry, normalised types, and defensive MIME helpers. Decisions D49–D54.
- **Demo mailbox:** a real connector with fictional data (shares ids with the seed, so syncing never duplicates it), separated from real data by `is_demo`, provider `demo`, `is_sample` rows and a `demo` delivery state. Sends are simulated and labelled.
- **Gmail connector** (OAuth 2.0 web flow with PKCE, offline access, minimal scopes `gmail.readonly` + `gmail.send`, full and incremental sync with history cursors, pagination, rate-limit/auth/transient error mapping, send, revoke): **implemented and tested against simulated Google responses only; not verified against a real account.** The UI and API say "Not verified live".
- **Connections** (`services/email_accounts.py`): server-side single-use OAuth state bound to user and workspace (10-minute expiry, constant-time check, owner required), tokens only in the encrypted credential store, refresh before expiry, `invalid_grant` → `needs_reauth` and no more provider calls, scope and refresh-token checks, "Connected" only after a real profile call, disconnect that revokes (best effort) and always deletes our credentials, access-log redaction of the callback query.
- **Sync:** idempotent upserts (unique provider ids), cursor moves only after a page is stored, stale history → full sync, per-run page cap with a resumable cursor, provider rate limits keep progress and block calls until `rate_limited_until`, contact/lead linking and one timeline entry per new message.
- **Drafts and sending** (`services/drafts.py`): draft CRUD, approval bound to a hash of recipient/subject/body (edits withdraw it), `POST /drafts/{id}/send` requiring an idempotency key; suppression, mailbox state and workspace send limits enforced server-side; the attempt is committed as `queued` before the provider is called; `demo` / `queued` / `sent` / `failed` / `unknown` delivery states with plain labels; ambiguous results are never retried and wait for `resolve-send`; every outcome audited with fixed vocabulary only. A small owner-managed suppression list (`/suppressions`).
- **API:** `GET /email/providers`, `GET|POST /email/accounts…` (demo, connect, sync, test, disconnect), `GET /api/v1/email/oauth/callback`, drafts and suppressions. Migration **0007** (account health/rate-limit columns, `messages.draft_id` unique per draft, `delivery_error_code`, wider `sync_cursor`).
- **Web:** `/integrations` (no longer a placeholder): mailboxes with honest status, last sync/test times, plain-language problems, Sync / Test / Reconnect / Disconnect (confirmation), the connectors that exist with their scopes and notes, banners for the provider redirect, view-only for members. The web proxy opens exactly one `email` route (the callback) and passes a redirect on only if it is a path on this site.

## Verification: MVP Prompt 9
- API: 1,272 pytest tests (152 new) pass on **SQLite, PostgreSQL 16 and Python 3.12**; ruff and mypy (strict) clean. New suites: Gmail connector against simulated responses (41), accounts/OAuth/sync/disconnect (52), drafts/suppression/sending (36), MIME/credentials/config/demo/migration (23).
- Web: 729 vitest tests (52 new: model, panel and proxy route/redirect tests) including axe; lint, typecheck, format and production build pass.
- Mutation checks (each made tests fail): approval not required, approval hash not checked, suppression off, idempotency replay off, queued not committed before the provider call, unknown treated as failed, send limits off, mailbox usability not checked, edits not withdrawing approval, state not bound to user, state not single-use, state expiry off, scope check off, owner check off, token compare off, disconnect not deleting credentials, rate-limit window ignored, demo flag dropped, cursor not advanced, redirects followed, callback query not redacted, web redirect allow-list off. Two survivors were equivalent mutants (the Gmail send's retry bound and subject check are each also enforced a second time by the HTTP/standard-library layer).
- Real browser (Chromium via Playwright, built app): axe clean and no sideways scroll on `/integrations` at 1440/820/390 px in dark and light; the seeded demo mailbox is labelled as demo; Gmail shows "Not set up" and cannot be clicked without credentials; demo sync created 4 new messages without duplicating the 2 seeded ones and a second sync was a no-op; the OAuth callback through the real proxy answered 303 with a same-site relative `Location` and the page showed the explained banner; every other `/api/v1/email/*` path is refused by the proxy.
- Bugs found by the tests and fixed: deleting a credential while the account still referenced it (foreign key) on reconnect and disconnect; the seed's placeholder draft hash; a test log capture mistaking the HTTP test client's own log for the server's.

## Not verified / known gaps (Prompt 9)
- **The Gmail connector has never talked to Google.** No OAuth client was available and Google's documentation could not be fetched from the build environment, so URLs, parameters, scopes and error shapes must be re-checked and the checklist in EMAIL.md run with a real account before anyone claims live sync. Outlook does not exist.
- No UI for drafts, approval or sending yet (Prompt 10 builds the inbox and draft review on this API); sending is API-only and was verified by tests and the demo path.
- Message bodies are not stored; retention and safe HTML rendering are Prompt 10. Bounce/unsubscribe detection that adds to suppression automatically is Prompt 10; today the list is managed by hand.
- Sync runs on demand; background scheduling arrives with the job runner (Prompt 11).
- The send limiter fails open if Redis is down; a crash between "queued" and the provider call leaves a `queued` message an owner must resolve by hand.
- Test-mode Google refresh tokens expire after about a week (per Google's rules at the time of writing), so a Testing-mode connection will ask to be reconnected.

## Completed — MVP Prompt 8: AI provider abstraction and safe structured outputs
- **Service layer** (`apps/api/app/ai/`, [AI.md](AI.md)): `AiService` with the six tasks (`classify_reply`, `assess_lead_fit`, `extract_profile_facts`,
  `draft_outreach`, `summarize_conversation`, `recommend_next_action`), typed inputs/outputs, versioned prompt templates, per-attempt
  timeouts, bounded retries with backoff, a total time budget, a per-workspace rate limit, and `AiOutcome` results that never raise for a
  provider problem. Decisions D43–D48.
- **Providers:** `mock` (labelled rule-based stand-in; default in development/test; refused in production), `gateway` (OpenAI-compatible
  chat-completions adapter), `disabled` (production default). Server-side configuration only (`AI_*` variables, key held as a `SecretStr`).
- **Safety:** inputs are minimised (no addresses, phones, URL queries) and fenced as untrusted data; replies are validated, never repaired
  (schema, cited fields exist, cited facts were supplied, no invented numbers/links/addresses/familiarity, extracted facts need an exact
  source quote and are always `pending_review`, no system-prompt/canary/credential echo); opt-outs are enforced by rules even if a model
  disagrees; drafting refuses (without calling a model) when there are no approved facts or profile basics; drafting never receives pricing
  guidance or exclusions. Only classification has a fallback (labelled keyword rules).
- **Metering:** every call writes a content-free `usage_records` row (migration **0006** adds `error_code`, `prompt_version`) and one log
  line of metadata; prompts, emails and replies are never stored or logged. `GET /api/v1/workspaces/{id}/ai/status` (members can read) shows
  the provider, models, limits, prompt versions and 24 h usage.
- **Evaluation:** 18 synthetic cases; `uv run python -m app.cli ai-eval` (exit 1 on any failure).
- **Input builders** (`ai/inputs.py`): workspace-scoped lead, draft-target (first name only) and conversation (newest N snippets) inputs.
- **New dependency:** `httpx` moved from dev to runtime dependencies (installed into `apps/api/.venv` with `uv add`).

## Verification: MVP Prompt 8
- API: 1,120 pytest tests (113 new) pass on SQLite, PostgreSQL 16 and Python 3.12; ruff and mypy (strict) clean. New suites: untrusted-text
  handling (18), the service (56: malformed output, timeouts, retries and budgets, fallback, injection-like emails, opt-out guard, missing
  profile facts, unsupported claims, rate limits, metering and log redaction), the gateway adapter against a simulated server (22), config
  (5), status endpoint/input builders/evals/migration (12).
- Mutation checks (each made tests fail): opt-out guard off, number-claim check off, unknown fact ids allowed, leak check off, pricing
  guidance sent to the model, insufficient-context refusal off, email addresses not removed, opted-out recommendation allowed, extraction
  quote check off, retry cap off, rate limit off, redirects followed, uncited evidence fields allowed, forged fences not defused, injection
  confidence cap off, fallback for throttled callers, summary claim check off.
- Evaluation: 18/18 with the demo provider. **That measures the stand-in and the safety layer only.**

## Not verified / known gaps (Prompt 8)
- **No live provider has been used.** The gateway adapter is verified only against a simulated server; "Jev" is unverified (no credentials or
  documentation were available). Run `ai-eval` against a real provider before relying on it.
- No UI calls the tasks yet (inbox, drafts and workflows arrive in Prompts 10–13); only the status endpoint exists.
- Messages store a 500-character snippet, so conversation inputs are short until email storage lands (Prompt 9).
- Injection detection is heuristic and English-centred; the validators are the protection. Cost figures are estimates from an optional price list.
- No per-provider privacy setting for sending message content (post-MVP).

## Completed — MVP Prompt 7: pipeline, tasks and activity timeline
- **API** (owner writes, members read; workspace-scoped, audited): `opportunities` list/create/edit, `move` and `reopen`, deal
  timeline (notes, calls, meetings; also shown on the lead); `GET /pipeline/board` (every stage with its deals, counts and
  per-currency totals); `tasks` list by view (overdue / today / upcoming / no date / done), summary counts, create (idempotent),
  edit, complete / reopen / dismiss, reschedule, snooze; `notifications` (list, unread count, mark read, mark all read).
- **Stage rules** (D37, D38): unknown or foreign stages are refused, closed deals must be reopened, a stale board cannot overwrite
  a newer move (`expected_stage_id` → 409 `stale_stage`), winning/losing closes the deal, a loss reason is recorded.
- **Money** (D39): exact decimals, per-currency totals, probability never guessed; a column with no probabilities shows no weighted figure.
- **Time** (D40): due times resolve in the zone they were meant in (skipped hour refused, repeated hour = first occurrence);
  views use the local day (23/25-hour days handled); overdue / today / upcoming never overlap.
- **Tasks from anywhere** (D41): lead, deal or conversation links validated (the deal's lead is filled in); creation is idempotent
  by key (double click, retry and race safe); creating/completing a task is written to the lead's timeline.
- **Notifications** (D42): "task due" and "task reminder" notifications are produced when notifications are read, deduplicated,
  settled when the task is completed, dismissed or rescheduled. Personal to each user; links are relative paths only.
- **Web:** `/pipeline` board (native drag and drop **and** an equal keyboard/screen-reader "Move to…" control, confirmation for won/lost with a loss
  reason, optimistic moves with exact rollback, live-region announcements) and table; `/pipeline/{id}` deal page (summary, move/reopen,
  edit, timeline, tasks); `/tasks` with the five views, time-zone control, complete / reschedule / snooze / dismiss / edit; a
  notification bell in the top bar; deals and follow-ups on each lead. Shared `TaskDrawer` and `OpportunityFields`.
- **Seed:** four deals (open in two currencies, one without a probability, one lost with a reason) and five tasks (overdue,
  due soon, later, undated, done).
- **New dependency:** `tzdata` (installed into `apps/api/.venv` with `uv add`) so time zones work on minimal systems.

## Verification: MVP Prompt 7
- API: 1,007 pytest tests pass on **SQLite, PostgreSQL 16 and Python 3.12/3.13**; ruff and mypy (strict) clean. New: 23 time-zone tests
  (DST gaps and repeats, 23/25-hour days, zone-dependent "today"), 57 deal tests (validation, every stage-move rule, stale board,
  closed deals, reopen, board totals, tenant isolation, member read-only), 61 task tests (idempotency incl. a simulated race,
  zone boundaries on a frozen clock, views, actions, links, permissions), 18 notification tests (once-only, settle on complete/
  reschedule, snooze, cap, personal scope), seed checks.
- Mutation checks (each made tests fail): unscoped stage lookup, stale-stage check off, closed deals movable, board mixing
  currencies, idempotency off, skipped hour accepted, "today" always UTC, overdue boundary off by one, unscoped task link,
  notifications for everyone, completing not settling notifications. (Removing the application-level dedupe lookup is harmless: the
  database's unique key still enforces once-only.)
- Web: 677 vitest tests (44 files) including drag-and-drop simulations, optimistic rollback, double-submit, axe on every view and
  dialog. Lint, typecheck, format and production build pass.
- Real browser (Chromium via Playwright): axe (incl. contrast) clean on every pipeline/tasks/lead page at 1440/820/390 px in dark and
  light themes; end-to-end checked against the database: real drag-and-drop, the Move control, cancel/confirm for won, loss reason,
  a stale board refused after another change, notes/edits/tasks on a deal, a double-clicked "Add task" creating one task, the skipped
  hour refused with a clear message, complete from the list, the bell showing due/reminder notifications and marking them read.
- Bugs found in the browser and fixed: the board's hidden text escaped its scroll box and made the page scroll sideways (the same
  class of bug as before); "≈ $0.00 weighted" was shown for deals with no probability (now omitted).

## Not verified / known gaps (Prompt 7)
- Dragging deals inside a column (ordering) isn't supported: a card's position is by last update. Moving between columns only.
- "Today" for the overdue badge on a deal's close date uses the server's UTC date, which can differ from the viewer's date near midnight.
- No calendar: the Tasks page says so; calendar events need a connected calendar (later).
- Reminders are in-app only and appear when the app polls (about once a minute while a tab is open); push/email reminders need the job runner.
- Notification preferences and a full notification page arrive with the dashboard work (Prompt 15).
- Tasks have a single assignee (the owner); dismissed tasks have no tab; conversation links are accepted by the API but there is no inbox yet to create them from.
- Deals have no delete (mark them lost); they are not archived; there is no deal-level proposal yet.
- Board columns show the 50 newest deals (the rest are reachable in the table view).

## Completed — MVP Prompt 6: leads, contacts, companies, CSV import and fit scoring
- **API** (owner writes, members read; all workspace-scoped; see [API_CONVENTIONS.md](API_CONVENTIONS.md)):
  `companies`, `contacts` and `leads` list/detail/create/edit/archive/restore with search, filters, sorting and pagination;
  lead tags (replace) and bulk tagging; activity timeline with notes, calls and meetings; lead status linked to the pipeline
  stage; `GET /leads/export` (CSV); `fit-scoring` criteria (get/save/recompute) and per-lead recompute; the CSV `imports`
  (preview, import, history, error report).
- **Fit scoring** (`services/fit_scoring.py`): five user-weighted criteria, rule-based and explainable (D30, D31). Every score
  stores its evidence, confidence, and the criteria/profile versions it used, so stale scores are flagged. Scores are rounded to
  the nearest 5; with too little data there is no number; clients the user excluded cap the score at 25.
- **CSV import** (`services/csvio.py`, `lead_import.py`): upload → map columns → preview → duplicate strategy → import →
  result and downloadable error report. Strict parsing, size/row/column limits, per-field validation, duplicate detection
  (D33), provenance (`source`, `source_retrieved_at`), tags created on the fly, do-not-contact flagged. The preview is the
  real import rolled back (D32). No scraping and no fetching of any kind.
- **Manual entry stays complete**: a lead needs only a title; companies and contacts can be described inline and are matched
  to existing records by website, name or email.
- **Safety:** spreadsheet-formula neutralising in every CSV written, owner-only import/export, export capped and audited,
  `no-store`/`nosniff` downloads, all text rendered as text, URLs validated server-side and in the browser.
- **Seed:** five fictional leads scored by the real rules (strong, weak-and-capped, and "not enough information"), saved
  criteria, a sample import record, all flagged as sample data.
- **Web** (`/leads`): tabs for Leads, Companies, Contacts and Fit scoring; detail pages for each; the import wizard
  (`/leads/import`). Lists are server-rendered from validated URL parameters (filters, sort and paging are links and a GET form,
  so they work without JavaScript). Lead detail shows the full score breakdown with evidence, provenance, timeline, tags and
  status/stage changes. Navigation marks Leads as available.
- **Migration `0005`**: new tables and columns; clears scores that were never computed (the old hard-coded demo values).

## Verification: MVP Prompt 6
- API: 849 pytest tests pass on **SQLite, PostgreSQL 16 and Python 3.12/3.13**; ruff and mypy (strict) clean. New: 38 company/
  contact tests, 75 lead tests (create, inline linking, validation, stage sync, listing filters/sorts, tags, bulk tagging,
  timeline, export, permissions, isolation), 57 scoring tests (every criterion and outcome, weights, rounding, insufficient
  data, exclusion cap, config API, stale scores), 90 CSV tests (parser edge cases, formula neutralising, mapping, preview,
  per-field validation, duplicates inside and across files, both strategies, error report, limits, permissions, isolation),
  migration 0005 with data on both databases, schema guards for the new tables.
- Mutation checks (each made tests fail): leads listing without the tenant filter, bulk tagging without the ownership check,
  export open to members, formula escaping off, unknown counted as a miss, no exclusion cap, no rounding, no email duplicate
  detection, unscoped company lookup in the importer, preview that commits, edits allowed on archived records.
  (A preview that merely flushes instead of rolling back is harmless: the request never commits, so it is not a bug.)
- Web: 365 vitest tests (29 files; every slice has DOM tests with axe, hostile input, member read-only and error mapping).
  Lint, typecheck, format and production build pass; OpenAPI is identical on Python 3.12 and 3.13.
- Real browser (Chromium via Playwright): axe (WCAG 2 A/AA incl. contrast, best practice) clean on every leads page (lists,
  filtered and empty states, both detail pages, scoring, import) at 1440/820/390 px in dark and light themes with no
  horizontal overflow; end-to-end through the UI and checked in the database: add a lead (invalid email error, then success;
  `<img onerror>` title stayed inert), search, bulk tag, change status (timeline entry), log a note, archive/restore, change
  criteria and recalculate, upload a CSV with a bad row and two kinds of duplicate → review → import → download the error
  report, export CSV (formulas neutralised), duplicate company website refused.
- Bugs found in the browser and fixed: the lead page asked the API for contacts sorted by an invalid field and therefore never
  loaded (unit tests with stubbed responses could not see it); a visually hidden table header escaping its scroll box (Prompt 5).
  Found by the tests: unscored leads sorted differently on SQLite and PostgreSQL, and name sorts depended on the database's
  collation (now NULLs-last and case-insensitive everywhere).

## Not verified / known gaps (Prompt 6)
- **Saved views** (optional in the playbook) are not built; filters are shareable URLs instead.
- Enrichment from approved sources is not implemented; the provenance columns it will use are in place.
- CSV files must be UTF-8; other encodings are not detected. Import is synchronous (5,000 rows max) with a result screen
  rather than a live progress bar; larger files wait for the job runner (Prompt 11).
- Scoring matches words with light stemming; it cannot understand meaning (the UI says so and offers keywords). Geography is
  text matching, not distance.
- Link pickers on forms list the first 100 companies/contacts (no typeahead endpoint yet); edits to leads, companies and
  contacts are last-write-wins (no version check).
- Do-not-contact is displayed and imported; enforcing it on send belongs to the email prompts.
- No bulk actions beyond tagging (archive, status change and delete in bulk come with the pipeline work).
- Member access (read-only) is covered by API and DOM tests, not by a browser session.

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
MVP Prompt 8 — AI provider abstraction and safe structured outputs (see the playbook).

## Commands
See the README. Migrations: `pnpm db:migrate`, rollback one step: `pnpm db:downgrade`.
