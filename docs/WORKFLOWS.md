# Workflow engine

_Added in MVP Prompt 11. Code: `apps/api/app/workflows/` (definition, catalogue, validator, executors, engine, approvals, events),
`app/services/workflow_defs.py`, routers `workflows`, `workflow-runs`, `approvals`; TypeScript mirror of the structural checks:
`packages/workflow-core`. There is no editor yet (Prompt 12) and no approval-centre page (Prompt 13): this is the backend they will use._

## What works, and what has been verified

| Piece | Status |
|---|---|
| Definition, validation, versions, activation, test/live mode | Works; covered by unit and API tests (SQLite, PostgreSQL 16, Python 3.12). |
| Execution: branching, retries, delays, approvals, cancel, manual retry, crash recovery | Works; covered by tests that drive the worker by hand with a controllable clock. |
| AI nodes | Run through the AI layer. With `AI_PROVIDER=mock` the "AI" is a **stand-in** (the fit and draft steps say `demo_ai: true` in their output; classifications record their source). Nothing here measures a real model. |
| `send_email` in **live** mode | Uses the Prompt 9 guarded send. Verified against the **fake provider** and the demo mailbox only; the Gmail adapter is still **not verified live**. |
| Triggers | `manual` (API), `lead_created` (API-created leads), `reply_received` (mail sync). `follow_up_due` is a valid trigger event with the same machinery but **nothing emits it yet**. |

## The model

A **workflow** has immutable **versions**. A version is a graph of **nodes** and **edges** (`definition.py`):

```json
{ "schemaVersion": 1,
  "nodes": [{ "id": "t", "type": "trigger", "config": { "event": "lead_created" } }, ...],
  "edges": [{ "id": "e1", "source": "t", "target": "assess", "branch": null }] }
```

An edge leaves one **output port** of its source: `next` (the default, `branch` empty) for most nodes, `true`/`false` for a
condition, `approved`/`rejected` for an approval gate. An `end` node has none.

### Node types (12)

| Type | Does | Needs | Gives | Test mode |
|---|---|---|---|---|
| `trigger` | starts the run: `manual`, `lead_created`, `reply_received`, `follow_up_due` | – | a lead or a conversation | same |
| `condition` | picks `true`/`false` by checking one value (`fit.rating`, `classification.category`, `lead.score`, `contact.suppressed`, ...) | the fact it reads | – | same |
| `ai_assess_fit` | AI fit rating for the lead | lead | `fit` | same (AI call) |
| `ai_classify_reply` | classifies the latest reply (reuses an existing classification of that message) | conversation | `classification` | same (writes the classification as the inbox does, including its auto-suppression of an explicit opt-out) |
| `ai_draft` | writes a draft from approved facts (`outreach` for a lead, `reply` for a conversation). **Never sends.** | lead / conversation | `draft` | same |
| `upsert_record` | moves a lead to a pipeline stage, or opens an opportunity | lead | `opportunity` | **simulated** |
| `create_task` | adds a task (+ due date), idempotent per run and node | placeholders' facts | `task` | same |
| `approval_gate` | pauses until the owner approves or rejects (default expiry 72 h) | – | `approved_draft` on the approved path if a draft exists | same |
| `send_email` | sends the **approved** draft through the guarded send | `draft` + `approved_draft` | – | **simulated** |
| `delay` | waits 1 minute to 30 days | – | – | same |
| `notify` | in-app notification to the owner | placeholders' facts | – | same |
| `end` | finishes as `success` or `failure` | – | – | same |

Titles and messages may use only these placeholders: `{lead_title}`, `{company_name}`, `{category}`, `{fit_rating}`. Message
text, addresses and other untrusted values can never be pulled into a template.

Each node that does work accepts `max_attempts` (1–5) and `timeout_seconds` (5–300); defaults are per node type
(`GET /workflows/catalog` lists them with each node's JSON Schema).

## Validation (`validate.py`)

Issue codes: `unknown_node_type`, `missing_config`, `invalid_config`, `unknown_placeholder`, `duplicate_node_id`,
`duplicate_edge_id`, `dangling_edge`, `unknown_port`, `ambiguous_branch`, `unhandled_branch`, `missing_trigger`,
`multiple_triggers`, `trigger_has_incoming`, `unreachable_node`, `cycle`, `missing_end`, `missing_input`,
`send_without_approval`.

- **Missing or invalid settings** are reported per node and field (a delay over 30 days, an unknown setting, a condition value that
  is not one of the field's values...).
- **Branches:** every output port of every node needs exactly one edge. A condition needs *true* and *false*; an approval gate needs
  *approved* and *rejected* (a rejection must lead somewhere on purpose).
- **No cycles** (loops are not supported yet) and no node the trigger cannot reach; at least one `end`.
- **Typed flow:** each node declares the *facts* it needs; the validator proves every path to it produces them (a reply-classification
  node needs a conversation, so it cannot follow a `lead_created` trigger).
- **Unsafe actions:** an email can only be sent on the **approved** path of an approval gate that comes *after* the draft was written
  and with no new draft in between, on **every** path. `send_without_approval` otherwise.

A version that does not validate can be **saved** (an editor needs work in progress) but never switched on or run.
`POST /workflows/validate` checks a definition without saving it. The editor's instant checks (`packages/workflow-core`) cover only
the **structural** problems and are tested against the same fixtures (`packages/workflow-core/fixtures/structure.json`) as the server;
settings, typed flow and safety are server-only.

## Runs and steps

Run states: `queued` · `running` · `waiting_approval` · `waiting_delay` · `succeeded` · `failed` · `cancelled`.
Step states: `running` · `waiting` · `succeeded` · `failed` · `cancelled`.

A **run** is pinned to the version it started with (a later version never changes it), records its start/finish, the node it is at,
its `correlation_id`, a `context` of ids and short enumerations (never message text), and, when it fails, an error **category** with a
fixed plain-language summary. Every **step** is a row: attempt number, start/end, output summary (ids, counts, enumerations; at most 20
short scalars), error category, the port it left through.

### The queue is the database

There is no in-memory timer and no Redis queue. A run is *due* when it is `queued` (and its `wake_at`, a retry backoff, has passed),
`waiting_delay` with `wake_at` passed, or `running` with an expired lease. A worker:

1. **claims** runs with a conditional `UPDATE` (two workers cannot take the same run) and takes a 5-minute **lease**;
2. refreshes the lease before every step and **stops touching the run if the lease is no longer its own**;
3. commits a step as `running` **before** the executor does anything, then finishes the step, applies the executor's own writes and
   moves the run's cursor in **one transaction**;
4. handles at most 25 steps per claim (then gives the run back) and at most 100 per run.

Run it with `python -m app.cli process-workflows [--loop]` (like `process-jobs`). The API also starts a worker after a request that
made runs due (starting a run, deciding an approval, retrying, creating a lead or syncing mail when a workflow listens).

**Recovery limits (be honest about them):** a crashed worker's run is picked up after its lease expires (up to 5 minutes later). The step that
was running is marked `interrupted` and counted as a failed attempt. Internal writes (task, notification, record changes) commit together with
the step, so a crash leaves nothing half-done; **the provider send is the one external effect**: it carries an idempotency key, the send path
refuses a second send, and a step that finds its own earlier send already delivered records it as a replay instead of sending again. A send
whose outcome the provider never confirmed (`outcome_unknown`) is **never retried automatically**. This is a polling queue in one database: latency
is the worker's poll interval, and throughput is whatever one or a few workers can do. It is not a distributed workflow engine (post-MVP).

### Retries, timeouts, failures

Failures have a fixed vocabulary (`errors.py`). Only **retryable** categories retry automatically (`ai_unavailable`, `ai_rate_limited`,
`ai_invalid_output`, `rate_limited`, `provider_error`, `timeout`, `interrupted`, `internal`), with backoff (30 s, 2 min, 10 min, 30 min,
1 h, or the provider's `Retry-After`) up to the node's `max_attempts`. Everything else fails the run at once with a clear reason
(`missing_data`, `suppressed`, `insufficient_context`, `not_approved`, `approval_invalidated`, `outcome_unknown`, ...). A person can **retry the
failed step** by hand (`POST /workflow-runs/{id}/retry`): it gets a new attempt and its own attempt budget; a run that ended as a failure *by
design* and a send awaiting `resolve-send` on the draft cannot be retried until it is resolved.

**Timeouts:** the per-node `timeout_seconds` bounds AI calls (it caps the whole call, retries included) and the mail connector has its own
HTTP timeout; a step that overran its node's timeout is logged and flagged `slow`. A step cannot be interrupted from outside: a hung worker is
recovered by the lease. There is no hard kill.

### Approvals: the durable pause

An approval gate creates an `approval_requests` row (bound to a hash of the draft's recipient, subject and body), notifies the owner and
pauses the run. Nothing is held in memory. The owner decides with `POST /approvals/{id}/decide`:

- **approve** approves exactly the text that was requested (the draft's own approval is set at that moment), and the run continues on the
  `approved` path; **reject** continues on `rejected`;
- an approval nobody decides **expires** (worker) and takes the `rejected` path;
- if the draft is edited after the request, the approval is **invalidated** and the run fails with `approval_invalidated`; retrying asks again
  for the new text;
- cancelling or failing the run cancels its open approvals; a decided approval cannot be decided again.

Only the workspace **owner** decides; members can read approvals and runs.

### Test mode and live mode

A new workflow is `draft` + `test`. Switching it on (`activate`) keeps `test`; going **live** needs the workflow to be active **and** an explicit
`confirm: true` (audited). A workflow that is not switched on can only be run by hand, in test mode. In **test mode** `upsert_record` and
`send_email` are simulated (the step output says `simulated: true`); drafts, approvals, tasks, notifications and AI calls are real, so the whole path
can be rehearsed. In **live mode** the same steps do their work.

### Duplicate and concurrent execution

- The **same event** cannot start a workflow twice: runs have a unique `(workspace, workflow, idempotency_key)`; events use
  `event + a token for the occurrence` (a lead id, a message id), manual starts accept an `idempotency_key` and otherwise get a random one.
- A workflow does not run **twice at once for the same lead or conversation** (a manual start gets `409 run_in_progress`; an event is skipped).
- Syncing the same mail again, or creating the same lead twice, therefore never multiplies runs.

### Limits and permissions

Per workspace: `WORKFLOW_MAX_WORKFLOWS` (25), `WORKFLOW_MAX_ACTIVE_RUNS` (50), `WORKFLOW_MAX_RUNS_PER_DAY` (500); at most 50 nodes, 100 edges and about
200 KB per definition; a delay of at most 30 days. Runs act as the **workspace owner**; without one nothing runs. Reading is open to members;
creating, saving, switching on, mode changes, starting, cancelling, retrying and deciding need the owner role. Everything is workspace-scoped:
another workspace's ids are a 404.

### What is never stored or logged

Step and run records hold ids, counts, enumerations and fixed error text. Never message bodies, drafts' text, addresses, prompts or provider
responses. Audit events (`workflow.created`, `version_saved`, `activated`, `paused`, `archived`, `mode_changed`, `run_started`, `run_finished`,
`run_cancelled`, `run_retried`, `approval_decided`, `approval_expired`) carry only ids, versions, modes, states and categories. Log lines name the exception *type*
only.

## API (`/api/v1/workspaces/{id}/…`)

| Endpoint | Purpose |
|---|---|
| `GET /workflows/catalog` | node types, settings schemas, ports, condition fields, placeholders |
| `POST /workflows/validate` | check a definition |
| `GET/POST /workflows` · `GET/PATCH /workflows/{id}` | list, create (optionally with a first version), get, rename |
| `POST /workflows/{id}/versions` · `GET …/versions/{n}` | save a new immutable version; read one |
| `POST /workflows/{id}/activate` · `/pause` · `/archive` · `/mode` | lifecycle |
| `POST /workflows/{id}/runs` | start a run by hand (`subject_type`, `subject_id`, optional `idempotency_key`) |
| `GET /workflow-runs` · `GET /workflow-runs/{id}` | list (filters: workflow, subject, status); run with steps and approvals |
| `POST /workflow-runs/{id}/cancel` · `/retry` | cancel (a running one stops before its next step); retry the failed step |
| `GET /approvals` (default pending; `status=all`) · `GET /approvals/{id}` · `POST /approvals/{id}/decide` | the approval queue |

## Known gaps

- No editor (Prompt 12), no starter automations and no approval-centre page (Prompt 13). The seeded demo workflow is a valid, inactive example.
- Nothing emits `follow_up_due`; there is no scheduler beyond the worker's poll loop and no automatic periodic mail sync.
- No loops, parallel branches or sub-workflows; one path per run.
- `upsert_record` can move a lead to a stage or open an opportunity; richer field updates and connector writes come later.
- A hung worker is recovered by lease expiry, not killed; delays are accurate to the worker's poll interval.
- Workflow definitions saved with problems create version rows that accumulate (no pruning yet).
