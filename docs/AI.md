# AI service layer

_Added in MVP Prompt 8. Code: `apps/api/app/ai/`. Nothing in the product depends on a particular vendor._

## What it is

`AiService` is the only thing the rest of the API calls to use a model. It offers six tasks, each with a typed input,
a strictly validated output, a versioned prompt and a safe failure mode:

| Task | Input | Output | If the provider fails |
|---|---|---|---|
| `classify_reply` | reply subject + text | one of 8 categories, confidence, rationale | labelled **rule-based fallback** |
| `assess_lead_fit` | lead facts + approved profile/facts | strong / possible / weak / unknown, reasons that each cite a field, gaps | failure |
| `extract_profile_facts` | document text | proposed facts, each with an exact source quote, always `pending_review` | failure |
| `draft_outreach` | lead + recipient first name + goal + approved facts | subject, body, ids of facts used, things to review | failure (never a template) |
| `summarize_conversation` | up to 20 message snippets | summary, key points, open questions | failure |
| `recommend_next_action` | status, last classification, opt-out flag | one action, rationale, optional days | failure |

Every result is an `AiOutcome`: `ok`, `data` or `failure` (stable `code`, safe message, `retryable`, `retry_after`),
`warnings`, and `meta` (provider, model, prompt version, latency, attempts, tokens, `is_mock`, `context_hash`,
`source`). `meta.label` is the sentence to show next to anything a person might rely on. **The service never raises for a
provider problem and never performs an action:** results are suggestions that a person reviews.

Call it from other features like this:

```python
from app.ai.factory import ai_service_for
from app.ai import inputs
from app.services.ai_context import build_context

ai = ai_service_for(request, ctx, settings)
target, first_name = inputs.draft_target(db, ctx, lead_id)        # workspace-scoped, no email/phone
out = ai.draft_outreach(DraftOutreachInput(lead=target, recipient_first_name=first_name), build_context(db, ctx))
if not out.ok:
    ...                                                           # show out.failure.message; offer to write it manually
```

Call it **before** you open a write transaction or after you commit: usage is recorded in its own short transaction.

## Providers

| `AI_PROVIDER` | What it is | Default |
|---|---|---|
| `mock` | A rule-based stand-in. **Not a model.** Everything it produces is labelled; drafts start with a visible `[DEMO DRAFT …]` line so they cannot be sent unnoticed. | development, test |
| `gateway` | An OpenAI-compatible `POST {AI_BASE_URL}/chat/completions` endpoint. | – |
| `disabled` | Every call fails with `ai_disabled`; nothing is sent anywhere. Classification still works by rules. | production |

`AI_PROVIDER=mock` is refused in production.

### What is and is not verified

The **gateway adapter is verified only against a simulated server** (`tests/test_ai_gateway.py`): request shape, the
`Authorization` header, tier-to-model routing, status-code mapping, redirects, oversize and malformed replies. It has
**not** been run against any live vendor. The playbook suggests "Jev" as the gateway; no Jev credentials or API
documentation were available, so Jev support is **unverified**. If Jev (or any other service) exposes the common
chat-completions shape, point `AI_BASE_URL` at it and run `python -m app.cli ai-eval` against it before relying on it. If
it does not, add an adapter (below). The same goes for any claim that "the AI works": until a live provider has been
evaluated, only the safety layer and the stand-in are known to behave.

### Configure a real provider securely

1. Put the settings in the **server's environment** (or a secret manager that injects it), never in code, the web app's
   `NEXT_PUBLIC_*` variables, a committed `.env`, or a ticket:
   ```
   AI_PROVIDER=gateway
   AI_BASE_URL=https://your-gateway.example/v1     # https required in production; no user:pass@ in the URL
   AI_API_KEY=...                                    # server-side only; kept as a SecretStr and never logged
   AI_MODEL=...                                      # drafting, fit, recommendations
   AI_MODEL_FAST=...                                 # optional: classification, extraction, summaries
   ```
2. Use a key that is **scoped to this app, rate-limited and budget-capped at the provider**, and rotate it by changing the
   environment variable. Prefer a provider/account setting that disables training on your data.
3. Optional price list so usage shows an *estimated* cost: `AI_INPUT_COST_MICROS_PER_1K`, `AI_OUTPUT_COST_MICROS_PER_1K`.
4. Tune limits if needed: `AI_TIMEOUT_SECONDS` (per attempt, default 20), `AI_MAX_ATTEMPTS` (default 2, max 4),
   `AI_TOTAL_BUDGET_SECONDS` (default 45), `AI_RATE_LIMIT_PER_MINUTE` (per workspace, default 30).
5. Start the API (a missing URL, key or model fails fast with the variable names), open
   `GET /api/v1/workspaces/{id}/ai/status`, then run `python -m app.cli ai-eval` and read the failures before enabling
   anything that depends on the model.

### Add a provider

Implement `ModelProvider` (`app/ai/providers/base.py`): `name`, `is_mock`, `model_for(tier)` and `complete(request)`.
Read `request.system` and `request.user`; ignore `request.payload` (that is for the stand-in). Raise only the errors in
`app/ai/errors.py` (`ProviderTimeout`, `ProviderUnavailable`, `ProviderRateLimited`, `ProviderAuthError`,
`ProviderBadRequest`, `ProviderBadResponse`) and **never put a response body, prompt or key in an error message**. Return
token counts when the provider reports them. Register it in `app/ai/factory.py` and add its settings to `app/config.py`.

## How a call is protected

1. **Context is chosen, not dumped.** Facts come from `build_context` (approved **and** enabled only). Each task sees only the
   profile fields it needs; drafting never receives pricing guidance, business goals or excluded-customer notes. A lead
   contributes company, industry, location and notes, never an email address or phone number; a recipient is a first name.
2. **Personal data is minimised.** Email addresses, phone numbers, long digit runs and URL query strings in untrusted text are
   replaced with `[email]`, `[phone]`, `[number]` before the prompt is built.
3. **Untrusted text is fenced.** Emails, imported notes, documents and tool results go inside
   `<<<UNTRUSTED label boundary>>> … <<<END boundary>>>` with a per-call random boundary; look-alike fences inside the text are
   defused, control and bidirectional-override characters are removed, and length is capped. The system prompt says
   everything inside a fence is data and never an instruction.
4. **Replies are validated, not repaired.** JSON only (one ```json fence is tolerated), no unknown keys, ranges and lengths
   enforced. Then task checks: reasons must cite fields that exist; a draft may cite only supplied fact ids and may state only
   numbers, links and addresses that appear in the supplied facts (a "15-minute call" request is allowed); invented familiarity
   ("as we discussed") is refused; extracted facts need an exact source quote and may not add numbers; summaries may not add
   figures. A reply that echoes the system prompt, a per-call canary or something shaped like a credential is discarded.
5. **Deterministic guards beat the model.** An explicit request to stop ("remove me", "unsubscribe") is classified as
   `unsubscribe` even if the model said otherwise; a recommendation to contact someone who opted out is replaced; when an email
   contains injection-like phrasing the confidence is capped and `injection_suspected` is returned for the UI. The detector is a
   warning light: the defence is that nothing a model says is executed and every reply is checked.
6. **Failures are bounded and quiet.** Per-attempt timeout, at most `AI_MAX_ATTEMPTS` tries with backoff (a provider
   `Retry-After` is honoured up to 5 s), a total time budget, a per-workspace rate limit checked before the provider is called.
   Unexpected exceptions become `unavailable`. Only classification falls back (to labelled keyword rules, confidence ≤ 0.6).
7. **Refusing is a feature.** If there are no approved facts and no profile summary or services, drafting refuses with
   `insufficient_context` and a list of what is missing, without calling a model.

## Metering and logs

Every call writes a `usage_records` row (kind `ai`): provider, model, task, prompt version, tokens when reported, estimated
cost when a price list is set (0 for the stand-in), latency, success, `is_mock`, a short `error_code`, a correlation id. **No
prompt, email, draft or reply text is ever stored.** The log line `ai_call …` carries the same metadata and nothing else;
there is no setting that turns content logging on. A metering failure is logged and never fails the request.
`GET /ai/status` shows the provider, models, limits, prompt versions and the last 24 hours of calls for the workspace.

## Prompts and evaluations

Templates live in `app/ai/prompts.py`, one per task, each with a `version` (`2026-10-v1`) that is stored with every call. Change
a template ⇒ bump its version. `app/ai/evals.py` holds a small synthetic fixture set (18 cases: every reply category, two
injection emails, thin lead data, a supported-facts-only extraction, a grounded draft, a refused draft, an opted-out
recommendation). Run `python -m app.cli ai-eval`; it exits non-zero on any failure. Against the stand-in it measures the stand-in
and the safety layer; against a real provider it measures the model. Grow the set whenever a real failure is found.

## Known gaps

- The gateway adapter has not been run against a live provider (see above); Jev specifically is unverified.
- Nothing calls these tasks from the UI yet: the inbox (Prompt 10) and workflows (Prompt 11/13) will. Only the status endpoint
  is exposed.
- Messages carry a 500-character snippet, so summaries and classification of real mail will see short text until the email
  framework stores more (Prompt 9).
- Cost figures are estimates from a configured price list; the stand-in is always 0.
- No streaming, no tool use, no per-user opt-out of sending message content to a provider (post-MVP: "privacy settings controlling
  whether message content is sent to each AI provider").
- Prompt-injection detection is heuristic and English-centred; the validators, not the detector, are the protection.
