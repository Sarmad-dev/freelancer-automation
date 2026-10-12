# API conventions

_Reference implementation: `apps/api/app/routers/tags.py` and `pipeline.py`; helpers in `app/api/` and `app/errors.py`.
Contracts: FastAPI → `packages/contracts/openapi.json` → generated TypeScript (`pnpm contracts:generate`)._

## URLs and versioning
- Everything lives under `/api/v1`. Breaking changes get `/api/v2`; additive changes (new optional fields/params) do not.
- Workspace data is nested: `/api/v1/workspaces/{workspace_id}/<resource>[/{id}]`. The workspace is **authorised, not trusted**: it is resolved through the signed-in user's membership; a workspace you are not a member of is indistinguishable from one that does not exist (`404 workspace_not_found`). Bodies never accept a `workspace_id` (`extra="forbid"`).
- IDs are UUIDs; a malformed id is `422`, an unknown or foreign id is `404`.
- Browsers call the Next.js origin (`/api/v1/*`), which proxies to the API (see SECURITY.md).

## Methods and status codes
`GET` list/read · `POST` create → `201` with the resource · `PATCH` partial update (omitted fields untouched, explicit `null` clears nullable fields) → `200` · `DELETE` → `204` (a second delete is `404`).
`401` not signed in / session expired · `403` forbidden or CSRF · `404` not found · `409` conflict (duplicates) · `422` validation · `429` rate limited (`Retry-After`) · `503` dependency unavailable.

## Errors
One envelope everywhere (`ErrorResponse` in OpenAPI):
```json
{"error": {"code": "tag_exists", "message": "A tag with this name already exists.", "fields": {"name": "Already exists."}}}
```
`code` is stable and machine-readable; `message` is safe to show; `fields` (optional) maps input names to messages (always the innermost field name, e.g. `urls`, not `body.urls.0`). Internals, SQL and stack traces never appear.

## Lists: pagination, sorting, filtering
Every list returns `{"items": [...], "total": N, "limit": L, "offset": O}` (`Page[T]`).

| Param | Rules |
|---|---|
| `limit` | 1-100, default 25 |
| `offset` | 0-100000, default 0 |
| `sort` | comma-separated, `-` prefix = descending, max 3 fields, **allow-listed per endpoint**; anything else is `422` with `fields.sort` listing the allowed names |
| filters | explicit, documented query params (e.g. `q`); `LIKE` wildcards in user input are escaped |

Ordering is always deterministic (a unique tie-breaker is appended), so pages never overlap or skip. Offset pagination is fine for the MVP's data sizes; switch hot lists to keyset pagination if they grow (the response envelope can gain `next_cursor` additively).

## Writes
- **Duplicates:** checked case/space-insensitively in the service and enforced by a database unique constraint; a race loses with the same `409`.
- **Idempotency:** creates that can be retried by clients or workers accept an idempotency key where the table has one (tasks, draft sends, workflow runs and steps).
- **Audit:** mutations write an `audit_events` row in the same transaction (action names like `crm.tag_created`; details are allow-listed).
- **Authorisation:** writes call `require_owner(ctx)` today; the call site is where finer roles plug in.
- **CSRF:** all non-GET requests need an allowed `Origin` or `X-Requested-With: freelancer-os`.

## Schemas
Pydantic request/response models live in `app/schemas/` and are deliberately separate from ORM models: the API is a contract, tables are an implementation detail. Responses use `from_attributes` models so ORM objects are never serialised directly; request models forbid unknown fields; text is trimmed, whitespace-collapsed and rejects control characters (`app/schemas/text.py`).

## Time, money, nulls
Timestamps are ISO-8601 UTC instants; a `*_timezone` field carries the user's intended zone for display. Money is a decimal string with a 3-letter currency. Absent optional values are `null`.

## Adding a resource (checklist)
1. Model with `TenantMixin`, `tenant_fk` for parent links, `UNIQUE(workspace_id, id)` if referenced, CHECKs, indexes (the schema guard tests will tell you what you missed).
2. Migration (`alembic revision --autogenerate`, then review) + a test for each new constraint.
3. Schemas in `app/schemas/`, router using `WorkspaceDep`, `scoped_select`/`get_scoped_or_404`, `page_params`/`paginate`.
4. Isolation tests with two users (see `tests/test_api_conventions.py`), then `pnpm contracts:generate`.
