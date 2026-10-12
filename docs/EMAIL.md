# Email integration framework

_Added in MVP Prompt 9. Code: `apps/api/app/mailbox/` (providers), `app/services/email_accounts.py`, `app/services/drafts.py`,
`app/services/suppression.py`; UI: `/integrations`._

## What works, and what has been verified

| Piece | Status |
|---|---|
| **Demo mailbox** (local, fictional, nothing delivered) | Works end to end: add, sync (idempotent), draft, approve, simulated send. Verified in tests and in a real browser. |
| **Gmail connector** (OAuth + PKCE, sync, send, revoke) | Implemented and tested against **simulated Google responses only**. **Not verified against a real Google account.** |
| Outlook | Not implemented. |

**There is no claim of live email sync.** The Gmail adapter was written from Google's documented endpoints; no OAuth client
credentials were available and the official documentation could not be fetched from the build sandbox, so every URL, parameter and
error shape in `app/mailbox/gmail.py` must be re-checked against Google's current documentation before first use. The app shows
"Not verified live" next to Gmail and reports an account as **Connected only after a real request to the provider succeeded**.

## Account states

`connected` (a real test or sync succeeded) · `demo` (the local mailbox) · `needs_reauth` (the grant was revoked or expired, or permissions
are missing: reconnect) · `error` (the provider keeps rejecting requests) · `disconnected` (you disconnected; credentials deleted). A
transient failure (timeout, 5xx, rate limit) never downgrades a working account; it records a plain-language `last_error` and a
`rate_limited_until` back-off instead.

## The connector interface

`app/mailbox/connector.py` defines what every provider implements: `authorization_url`, `exchange_code`, `refresh`, `revoke`,
`profile` (identity **and** health check), `sync`, `fetch_body`, `create_draft`, `send`. Each connector has a manifest (capabilities,
scopes and why each is requested, setup doc, notes). Domain code never branches on a provider; it asks the registry
(`app/mailbox/registry.py`) for a connector. To add one (for example Outlook): implement the interface, map the provider's errors to
`app/mailbox/errors.py` (never put a response body or token in an error), register it, add its settings, add tests with simulated
responses, and mark it unverified until a real account has been used end to end.

## Connecting (OAuth)

1. An owner calls `POST /api/v1/workspaces/{id}/email/accounts/connect` (the Integrations page's **Connect Gmail** button). The server
   stores a single-use pending record (random token, PKCE verifier, user, workspace) in the **encrypted credential store**, and returns
   the provider's consent URL carrying `state = workspace.record.token`.
2. The provider redirects the browser to `{WEB_BASE_URL}/api/v1/email/oauth/callback?code=…&state=…`. The web app's proxy forwards that
   one route (nothing else under `/email`), and the API validates: the record exists, belongs to **this signed-in user**, is under 10
   minutes old, the token matches in constant time, and the user is still the workspace owner. The record is deleted whatever happens.
3. The code is exchanged with the PKCE verifier. The grant must include **every** required scope (Google lets people untick
   permissions) and a refresh token. A real profile call must succeed. Only then is the account saved as `connected`.
4. The browser is redirected to `/integrations?email=connected` or `?email=error&reason=<code>`: a path on this site, containing no
   code, state, token or provider text.

Tokens: the refresh token and access token live only in `credential_secrets` (Fernet, bound to workspace and purpose). They never reach a
response, the browser, the audit trail or a log line. Access tokens are refreshed shortly before expiry; a refresh that fails with
`invalid_grant` marks the account `needs_reauth` and stops all provider calls until the owner reconnects. The API's access log redacts the
callback's query string. **Disconnect** revokes at the provider (best effort), deletes the stored credentials and reports honestly if the
provider could not confirm revocation (then remove access in the provider's account settings too).

## Sync

Messages are stored as metadata plus a 500-character snippet (bodies are fetched on demand and not stored; the retention decision belongs to
the inbox, Prompt 10). Provider ids are unique per account, so repeating a page changes nothing; the cursor only moves after a page is
stored; a stale cursor (Gmail history too old) restarts with a full sync; each run fetches at most `EMAIL_SYNC_MAX_PAGES` pages and resumes
from the cursor next time; a provider rate limit keeps progress and blocks further calls until `rate_limited_until`. New messages link to a
known contact/lead by address and add one `email` entry to the lead's timeline. Demo and real data are separated (`is_demo`, provider
`demo`, `is_sample` rows) and a demo account can never be synced by a real connector or vice versa.

## Sending

`POST /drafts/{id}/send` with an `idempotency_key`. Every rule is enforced server-side, in this order: the draft must be **approved and
unchanged since approval** (approval binds to a hash of recipient, subject and body; any edit withdraws it) → a repeated key returns the
earlier outcome and no other key can start a second send → the recipient must **not be on the suppression list** → the mailbox must be
usable and the workspace under its send limits (`EMAIL_SEND_LIMIT_PER_HOUR` / `_PER_DAY`) → the attempt is committed as `queued` **before**
the provider is called → the provider is called exactly once.

| Delivery state | Meaning | Next step |
|---|---|---|
| `demo` | Demo mailbox: simulated, nothing delivered | none |
| `queued` | Recorded; the provider has not confirmed | wait or resolve |
| `sent` | The provider confirmed | none |
| `failed` | Definitely not sent (rate limit, rejected, revoked, unreachable) | fix and retry; the same message row is reused |
| `unknown` | Timeout or provider error after the request left; **never retried automatically** | check the mailbox, then `POST /drafts/{id}/resolve-send` with `sent` or `not_sent` |

Every outcome writes an audit event (`email.send_queued`, `email.sent`, `email.send_failed`, `email.send_unknown`, `email.send_blocked`,
`email.send_resolved`) containing only the provider, state and a reason code: never an address or message text.

## Configure Gmail

> These steps come from knowledge of Google's console and API at the time of writing and **could not be checked against the live
> documentation from the build environment**. Google renames menus and changes verification and token-lifetime rules; follow the current
> documentation where it differs, and treat anything below as a checklist, not a guarantee.

1. **Project.** In the [Google Cloud console](https://console.cloud.google.com/) create (or choose) a project.
2. **Enable the API.** APIs & Services → Library → **Gmail API** → Enable.
3. **Consent screen** (APIs & Services → OAuth consent screen, or Google Auth Platform in newer consoles). Choose **External** (or **Internal**
   for a Google Workspace organisation). Set the app name and support/developer emails. Add the scopes
   `https://www.googleapis.com/auth/gmail.readonly` and `https://www.googleapis.com/auth/gmail.send`. While the app is in **Testing**, add
   your own Google account as a **test user**.
   - In Testing, Google issues refresh tokens that **expire after about 7 days**, so the mailbox will ask to be reconnected weekly.
   - Reading mail is a **restricted scope**. Public distribution needs Google's app verification (and a security assessment). For personal
     or small-team use, check Google's current rules for unverified apps and test users.
4. **Credentials.** APIs & Services → Credentials → Create credentials → **OAuth client ID** → application type **Web application**. Under
   **Authorized redirect URIs** add exactly:
   - development: `http://localhost:3000/api/v1/email/oauth/callback`
   - production: `https://<your web origin>/api/v1/email/oauth/callback`
5. **Server settings.** Put the client id and secret in the **API's** environment (never in the web app's `NEXT_PUBLIC_*` variables or a
   committed file) and restart it:
   ```
   GOOGLE_CLIENT_ID=<client id>
   GOOGLE_CLIENT_SECRET=<client secret>
   # only if the public address differs from WEB_BASE_URL:
   # GOOGLE_REDIRECT_URI=https://app.example.com/api/v1/email/oauth/callback
   ```
   Set `WEB_BASE_URL` to the web app's public origin, and in production set `CREDENTIAL_ENCRYPTION_KEYS` (tokens are stored encrypted
   with it). The server refuses to start if only one of the two Google values is set, or if the production redirect URI is not https.
6. **Connect.** Sign in as the workspace owner, open **Integrations**, press **Connect Gmail**, and approve **both** permissions (keep every box
   ticked). You should land back on Integrations with "Mailbox connected".
7. **Verify end to end before relying on it:** press **Test connection**; **Sync now** and confirm real conversations appear; create a draft
   to **your own other address**, approve it and send it; confirm it arrives and shows `sent`; revoke access in your Google account's
   permissions page and confirm the next sync shows **Reconnect needed**; disconnect and confirm the credentials are gone. Only after all of
   these pass for you can anyone say Gmail is verified.

## Known gaps

- The Gmail adapter has not been run against Google (above). Outlook does not exist.
- Gmail's `create_draft` (provider-side drafts) is not offered: it needs the broader `gmail.compose` scope, which is deliberately not requested.
- Message bodies are not stored; the inbox decides retention and safe HTML rendering in Prompt 10.
- Bounce and unsubscribe detection from incoming mail (adding to suppression automatically) is Prompt 10; today suppression is managed by hand
  (`/suppressions`) and checked at send time.
- Sync runs when asked (button or API); background scheduling arrives with the job runner (Prompt 11).
- The send-rate limiter fails open if Redis is down (as the sign-in limiter does); approval, suppression and idempotency still hold.
- A crash between "queued" and the provider call leaves a `queued` message that an owner must resolve by hand.
