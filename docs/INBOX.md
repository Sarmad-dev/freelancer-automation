# Inbox, reply classification and draft review

_Added in MVP Prompt 10. Code: `apps/api/app/services/{inbox,inbox_events,email_jobs,replies,follow_ups}.py`, `app/mailbox/{sanitize,signals}.py`,
`app/routers/inbox.py`; UI: `/inbox` (`apps/web/src/components/inbox/`)._

## What works, and what has been verified

| Piece | Status |
|---|---|
| Conversation list, search, filters, unread, counts, thread view | Works with the **demo mailbox** (11 fictional messages in 6 conversations). Verified by tests. |
| Reply classification (8 categories) | Works through the AI layer. With `AI_PROVIDER=mock` the "model" is a **stand-in** and every result says so; real model quality is **not measured** (see AI.md). Deterministic rules (opt-out, bounce) work independently of any model. |
| Suggested replies | Created as ordinary **drafts**; never sent without a person approving and pressing Send. |
| Gmail bodies | The Gmail adapter fills bodies from simulated responses only. **Not verified against a real Google account.** |

## Data kept, and for how long

Prompt 9 stored metadata plus a 500-character snippet. Prompt 10 additionally stores a **cleaned body** per message in its own table
(`message_bodies`), so it can be deleted without touching conversations, classifications or the audit trail.

- **Text**: control and bidirectional-override characters removed, whitespace normalised, capped (a `text_truncated` flag says so).
- **HTML**: parsed and rebuilt by an allow-list sanitiser (`app/mailbox/sanitize.py`, nh3): formatting, lists, tables and plain links only.
  Scripts, styles, forms, iframes, event handlers, `javascript:`/`data:` URLs and relative links are removed. **Images and any remote
  content are removed** (`images_blocked` says some were), so opening a message makes no request to a third party and cannot confirm to
  a sender that you read it. Links get `rel="noopener noreferrer nofollow"` and open in a new tab. The sanitiser version is stored with the body.
- **Attachments**: metadata only (name, type, size). Content is never fetched or stored.
- **Retention**: bodies stay until deleted. An owner can call `DELETE /api/v1/workspaces/{id}/email/accounts/{account_id}/mail`
  to remove synced bodies, messages and conversations for that mailbox; the next sync restores them. Disconnecting a mailbox already
  removes its credentials.
- **Logs and audit** never contain addresses, subjects or message text; only ids, counts, states and reason codes.

## How a message becomes a classified conversation

1. **Sync** (idempotent upsert by provider id, Prompt 9) stores the message and its cleaned body, links the sender to a known contact/lead,
   and enqueues **one** classification job per message (`email_jobs` has a unique `(message, kind)`, so repeating a page does nothing).
2. **Bounce check first.** A message from a mail-system sender (`mailer-daemon`, `postmaster`, …) with a delivery-failure subject is
   marked `is_bounce`, the last outbound recipient is added to the do-not-contact list (reason `bounce`) and no classification is run.
3. **Worker.** Jobs run after the sync request returns (FastAPI background task) or in a separate process:
   `python -m app.cli process-jobs [--loop]`. A worker claims jobs with a conditional UPDATE (two workers cannot take the same job),
   holds a 5-minute lease (a crashed worker's job is claimable again), retries with backoff (30 s, 2 min, 10 min, 3 attempts), and on final
   failure marks the conversation **needs review** (`classification_failed`) instead of guessing. A job whose message was superseded by a
   newer one in the same conversation is skipped.
4. **Classification** uses `AiService.classify_reply` with the *cleaned* body (injection-fenced and minimised as in AI.md). The result
   must quote evidence that **really appears** in the message; otherwise it is rejected.
5. **Review rules.** The conversation is flagged `needs_review` with a reason when: `injection_suspected`, `unsubscribe_unconfirmed`
   (the model says unsubscribe but no explicit opt-out phrase was found), `fallback` (rule-based fallback after a provider failure),
   `low_confidence` (< 0.7) or `classification_failed`. A person can always override a category (`PUT …/classification`, source `manual`).
6. **Stop status.** An unsubscribe confirmed by the deterministic opt-out rule adds the sender to the suppression list
   (source `classification`; a manual override to unsubscribe uses source `manual_classification`; the model alone never suppresses). The UI shows a banner such as *"Stopped: unsubscribed"* with the address and date and, for owners, a way to
   lift it (`DELETE /suppressions/{id}`). Out-of-office, bounce and "no further contact" are shown as stop or pause states too.
7. **Notifications.** A new reply creates one `reply_received` notification (deduplicated per conversation message).

## Suggested replies

`POST …/conversations/{id}/suggest-reply` calls `draft_outreach` with a `reply_to` context (the latest inbound message, fenced as untrusted) and the
workspace's **approved and enabled** facts. It creates or replaces the AI draft for that conversation and returns the facts it used so the
UI can show them. It refuses when there is no incoming message, when the sender is on the do-not-contact list (`contact_stopped`), when there are not
enough approved facts (`insufficient_context`, naming what to add) or when the provider fails (no template fallback). The category is passed to the
drafting prompt as context; the UI discourages replying to unsubscribe, out-of-office and irrelevant threads, but the server only hard-blocks stopped contacts. When the inbound message looks like
a prompt injection the reply may not reuse numbers or links from it. **It never sends.**

From there the existing Prompt 9 draft flow applies: edit → approve (bound to a hash of recipient, subject and body) → send with an
idempotency key. The suppression list is re-checked server-side at the moment of sending, whatever the UI showed.

## Stopping follow-ups

`app/services/follow_ups.py::check()` is the single gate future automation (Prompt 11+) must call before any automated follow-up. It
answers *not allowed* when the recipient is suppressed or when the conversation has an inbound reply after our last outbound message. No
sequence engine exists yet; the gate and its tests do.

## API

All under `/api/v1/workspaces/{id}/inbox`, membership-checked (non-members get 404); changing state needs the owner role.

| Endpoint | Purpose |
|---|---|
| `GET /counts` | open, unread, needs-review totals |
| `GET /conversations` | list; `q`, `classification`, `unread`, `needs_review`, `account_id`, `lead_id`, `status` (open/archived), paging |
| `GET /conversations/{id}` | thread (ordered by source timestamp), bodies, classification, stop status, draft |
| `POST /conversations/{id}/read` · `/unread` | read state |
| `POST /conversations/{id}/classify` | queue a fresh classification (202) |
| `PUT /conversations/{id}/classification` | manual category override |
| `POST /conversations/{id}/suggest-reply` | create/replace the suggested draft |

## Known gaps

See [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md): no live Gmail verification; the job runner is a database-backed queue (no scheduled sync yet);
suppression by domain and per-contact "snooze until" are not implemented; classification quality with a real model is unmeasured;
attachments are listed but cannot be opened.
