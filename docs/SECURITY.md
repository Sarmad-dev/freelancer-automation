# Authentication, sessions and tenancy

_Status: MVP Prompt 3. This documents what is implemented and what is deliberately not yet._

## Where identity lives

**The FastAPI API is the identity and session authority.** There is no external identity provider and no
JWT. The web app never validates credentials or sessions itself; it asks the API.

| Concern | Owner |
|---|---|
| Password hashing, sign-up/in/out, reset | API (`app/routers/auth.py`) |
| Session issue/validate/expire/revoke | API (`app/deps.py`, `sessions` table) |
| "Is there a cookie?" redirect shortcut | Web `src/proxy.ts` (UX only, not a security boundary) |
| Authoritative page gate | Web server components call `GET /api/v1/auth/me` (`src/lib/session.ts`) |
| Workspace authorisation | API (`get_workspace_context`) on every workspace route |

## Request path

```
Browser ── same-origin ──► Next.js  /api/v1/*  (route handler, allow-listed proxy)
                              └──────────────► FastAPI /api/v1/*
```

The browser only talks to the Next.js origin, so the session cookie is first-party: no CORS, no
third-party-cookie behaviour, and the API address stays private. The proxy forwards only `auth/*` and
`workspaces/*`, rejects dot/empty/encoded-slash segments, forwards an allow-list of headers, relays every
`Set-Cookie`, and forces `Cache-Control: no-store`. Server components call the API directly with the
forwarded cookie.

## Sessions

- Opaque 256-bit random token in an **HttpOnly, SameSite=Lax, Path=/** cookie. `Secure` and the
  `__Host-` name prefix are used in production (`COOKIE_SECURE` defaults to on there). Tokens are never in
  JSON bodies, `localStorage`, `sessionStorage` or page HTML (verified by the browser test).
- The database stores only `SHA-256(token)`, so a database leak does not yield usable sessions.
- A new session is issued on every sign-in (no fixation). Sign-out deletes the row server-side, so a
  replayed cookie fails.
- **Expiry:** idle timeout (`SESSION_IDLE_TIMEOUT_MINUTES`, default 7 days, measured from `last_seen_at`,
  refreshed at most every 5 minutes) **and** an absolute cap (`SESSION_ABSOLUTE_TIMEOUT_DAYS`, default 30).
  Both are enforced server-side. The cookie's Max-Age equals the absolute cap and is not re-issued on activity
  (server-rendered pages cannot update browser cookies, so a sliding cookie could lapse while the server
  session was still valid).
- An expired session returns `401 session_expired`; pages redirect to `/sign-in?reason=expired`, client calls
  go through `redirectToSignIn`. An unreachable API shows an error state instead of a misleading sign-in bounce.

## Passwords

Argon2id (`argon2-cffi` defaults, re-hashed on sign-in if parameters change). Policy: 12-128 characters,
no trivially common values, must not contain the email's local part. Sign-in applies only a length cap (to
bound hashing cost). A dummy hash is verified for unknown accounts so timing does not reveal registration.
A k-anonymity breached-password check is a planned improvement.

## Password reset

`POST /auth/password-reset/request` always answers `202` (no account enumeration) and is rate limited per
email and IP. Tokens: 256-bit random, hashed at rest, single use, 60-minute TTL, only the newest link works.
Confirming a reset revokes **all** sessions for that user. A rejected (weak) new password does not burn the
token. Delivery goes through `app/mailer.py`:

- `console` (development default) logs the link to the API log. **Never enabled in production** (config
  validation refuses it).
- `disabled` (production default until a mail provider exists): the API answers `503
  password_reset_unavailable`, `GET /auth/config` reports `password_reset_enabled: false`, and the UI hides
  the "Forgot password?" link.

## Abuse controls

Fixed-window rate limits (`app/ratelimit.py`): sign-in 10 / 15 min per email (reset on success) and 60 / 15 min
per IP; sign-up 10 / hour per IP; reset request 5 / hour per email and 20 / hour per IP; reset confirm
30 / hour per IP. `429` carries `Retry-After`. Backend: in-memory (dev/test) or Redis (required in
production). If Redis is down the limiter fails **open** and logs a warning (availability over strictness; the
per-account lockout is the primary protection).

Client IP: `X-Forwarded-For` is honoured only for `TRUSTED_PROXY_COUNT` hops (default 0 = direct peer). Behind
the Next.js proxy and a load balancer, set it correctly or all users share one IP bucket.

## CSRF

Defence in depth on top of SameSite=Lax: every state-changing request must carry an `Origin` on the
allow-list (`CORS_ALLOWED_ORIGINS`) or, when no Origin is sent, the `X-Requested-With: freelancer-os` header
(which cross-site forms cannot set). `Origin: null` and foreign origins get `403 csrf_rejected`. This also
blocks login-CSRF and forced sign-out.

## Tenancy

`User -> Membership(role) -> Workspace`. The MVP only creates one personal workspace with an `owner`
membership, but the schema supports many workspaces per user and many users per workspace.

- Workspace routes are `/api/v1/workspaces/{workspace_id}/...` and resolve through `get_workspace_context`,
  which joins on **the signed-in user's membership**. A non-member gets the same `404 workspace_not_found` as a
  non-existent id (ids cannot be probed). Request bodies reject unknown fields, so a `workspace_id` can never
  be smuggled in via the body.
- Service functions take the resolved context and filter every query by `ctx.workspace_id`.
- Writes additionally call `require_owner` (the pattern for future roles).
- Tests: `tests/test_onboarding.py::TestWorkspaceIsolation` (read/write/skip/complete/demo with a second
  real user, indistinguishable 404s, per-workspace profile storage).

## Secrets at rest (credential store)

OAuth tokens and API keys never appear in general tables (a schema test fails if a column even looks like one).
They are stored via `app/security/credentials.py`: Fernet authenticated encryption, per-row `key_id` for rotation, the
`workspace_id`/`purpose` sealed inside the ciphertext and verified on read, reads scoped by workspace. Keys come from
`CREDENTIAL_ENCRYPTION_KEYS` (required in production; dev falls back to an ephemeral key and logs a warning). Details and
rotation steps: [DATA_MODEL.md](DATA_MODEL.md#credentials). Known gap: keys live in the process environment; a KMS-backed
store is the production hardening step.

## Audit trail

`audit_events` rows are written in the same transaction as the change: `auth.sign_up`, `auth.sign_in`,
`auth.sign_in_failed`, `auth.sign_in_blocked`, `auth.sign_out`, `auth.password_reset_requested`,
`auth.password_reset_completed`, `onboarding.step_saved|skipped|completed`, `workspace.demo_mode_changed`.
`details` is filtered through an allow-list (`app/audit.py`), so passwords, tokens and profile contents cannot
be stored even by mistake. Failed sign-ins record only a 12-character hash of the email. IP and a truncated
user-agent are stored; retention/deletion policy is a later governance task.

## Input handling

All input is validated by Pydantic at the API boundary (types, lengths, enums, IANA time zones, control
characters, whitespace normalisation, `extra="forbid"` on onboarding bodies). Portfolio URLs must be public
`http(s)` URLs without credentials; localhost, `.local/.internal`, and non-global IPs are rejected so a future
fetcher cannot be pointed at internal addresses. Text is stored verbatim and must always be rendered as text.
Zero-width/bidi-control characters are stripped (D29). Knowledge `source_ref` accepts only a public `http(s)` URL or a
plain label (`javascript:`, `data:` and any `scheme://` are refused). Knowledge and profile writes are owner-only; members
get read access. Audit details for these actions are limited to field *names*, counts, kinds and versions, never content.

## CSV import and export
Imports accept only data in the file the user chose; nothing is fetched. Files are size/row/column limited, parsed strictly (a malformed quote is an error, not silently swallowed data) and every cell is validated like the equivalent form field (email, public website, phone, lengths, control and invisible characters). Preview and import are owner-only. The raw file is never stored; the import record keeps counts and a capped list of row problems, and its audit event only carries counts. Exports and error reports are owner-only, audited by count, capped, served with `no-store`/`nosniff`, and neutralise spreadsheet formulas in every cell. Do-not-contact is derived from the suppression list and is shown on leads and contacts and in imports; nothing in this phase sends email.

## Pipeline, tasks and notifications
Deal and task writes are owner-only and workspace-scoped (stages, leads, deals and conversations a request refers to must belong to the workspace; the database also refuses cross-tenant links). Audit events for stage moves carry only the destination stage key; task events carry no titles or descriptions. Notifications are per user: another member of the same workspace cannot read or mark them, and notification links are relative paths only (validated on the server and again in the browser). Task creation is idempotent by key so retries cannot duplicate records.

## AI calls
Details in [AI.md](AI.md). The provider key lives only in the server environment (`SecretStr`, never logged, never returned by the status endpoint, never in an error message); production refuses the demo provider, a non-https gateway URL and URLs with embedded credentials; redirects from the gateway are not followed. Emails, imports, documents and notes are untrusted: personal data is removed, text is fenced, replies are validated and nothing a model says is executed. Prompts, emails and replies are never stored or logged; usage rows and log lines carry metadata only. Context is workspace-scoped and built from approved facts only; drafting never receives pricing guidance or excluded-customer notes. Calls are rate-limited per workspace before the provider is contacted.

## Email connections and sending
Details in [EMAIL.md](EMAIL.md). Provider tokens exist only in the encrypted credential store (never in responses, logs, the audit trail or the browser); the OAuth `state` is single-use, expiring and bound to the signed-in owner, PKCE protects the code exchange, a grant missing a required permission is refused, and the access log redacts the callback query. The web proxy opens exactly one `email` route (the callback) and passes on a redirect only if it is a path on this site. Revoked grants stop all provider calls until reconnected; disconnect always deletes our copy of the credentials. A send requires an approved draft whose text is unchanged since approval, an idempotency key, a recipient not on the suppression list and a usable mailbox within send limits, and is recorded before the provider is called; ambiguous results are never retried automatically. Header injection is prevented by single-line subjects, address validation and the standard library's header guard. Audit events carry provider, state and reason codes only.

Inbox (details in [INBOX.md](INBOX.md)): incoming mail is untrusted. Bodies are rebuilt by an allow-list sanitiser, images and remote content are removed (reading mail never contacts a third party), HTML renders only in a sandboxed iframe with a restrictive CSP, and attachments are metadata only. Message text reaches a model only after minimisation and fencing, and model output must quote evidence that really appears in the message. Only a deterministic opt-out rule (never the model alone) suppresses a sender automatically; suppression is enforced again server-side at send time. Suggested replies are drafts that a person must approve. Message text never appears in logs or audit events, and an owner can delete synced mail.

Workflows (details in [WORKFLOWS.md](WORKFLOWS.md)): a workflow can only send email after a person approved exactly that draft in the same run (proved by the validator and checked again by the engine), and only the owner decides approvals. Runs start in test mode, where record changes and sending are simulated; going live needs an explicit, audited confirmation. The engine never stores message text, addresses or exception text in run records, step logs or audit events, only ids, counts, enumerations and fixed error categories. Templates can only use four allow-listed placeholders. Everything is workspace-scoped, and workspace limits (workflows, runs in progress, runs per day) apply.

## Known gaps (tracked)

- **No email verification yet** (`email_verified_at` is always null). Consequently sign-up reveals whether an
  email is already registered (`409 email_in_use`); mitigated by per-IP rate limiting.
- No MFA / passkeys / social login; no "sign out everywhere" or session list UI.
- No breached-password check; reset email delivery is not implemented (dev console only).
- Rate limiter fails open if Redis is unavailable.
- Security headers on the web app are minimal (nosniff, frame deny, referrer policy); a CSP is part of
  MVP Prompt 16.
