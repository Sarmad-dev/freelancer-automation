# Data model

_Status: MVP Prompt 4. 35 application tables (plus Alembic's version table). Source of truth: `apps/api/app/db/models*.py`;
migrations: `apps/api/alembic/versions` (`0003_domain_model` added 26 tables: everything except the Identity group, `freelancer_profiles` and `audit_events`)._

## Entities

| Group | Tables | Notes |
|---|---|---|
| Identity & tenancy | `users`, `workspaces`, `memberships`, `sessions`, `password_reset_tokens`, `onboarding_progress` | MVP: one personal workspace, one `owner` membership. Roles `owner/admin/member` are CHECK-constrained so teams can be added without a schema change. |
| Profile & knowledge | `freelancer_profiles`, `knowledge_items` | Knowledge has provenance (`source_type`, `source_ref`), review `status`, `version`, approver. Only `approved` items may reach AI context. |
| CRM | `companies`, `contacts`, `leads`, `tags`, `lead_tags`, `pipeline_stages`, `opportunities`, `activities`, `tasks` | Leads carry `fit_score` + `fit_explanation` (JSON) and provenance (`source`, `source_retrieved_at`). |
| Email & outreach | `email_accounts`, `conversations`, `messages`, `drafts`, `suppression_entries` | Message **metadata only** (no body column yet). Drafts carry `content_hash` / `approved_content_hash` so approval binds to exact content. |
| Integrations & secrets | `integration_connections`, `credential_secrets` | Connections hold a `credential_id` only. Secrets live encrypted in `credential_secrets`. |
| Workflows | `workflows`, `workflow_versions`, `workflow_nodes`, `workflow_edges`, `workflow_runs`, `workflow_step_runs`, `approval_requests` | Versions are immutable snapshots (nodes/edges are rows). A run is pinned to one version. |
| Operations | `usage_records`, `notifications`, `audit_events` | Usage never stores prompts/content. Notifications de-dupe on `(user_id, dedupe_key)`. |

## Conventions (enforced by `tests/test_schema_guards.py`, which also protects tables added later)

1. **IDs:** random UUIDv4 primary keys (`id`), unguessable in URLs and generatable anywhere. (`lead_tags` uses its composite key.)
2. **Timestamps:** `created_at` on every row; `updated_at` on mutable rows; all `timestamptz` (UTC instants). `usage_records` uses `occurred_at`; workflow nodes/edges are immutable parts of a timestamped version.
3. **Tenancy:** every tenant-owned table has `workspace_id NOT NULL → workspaces(id) ON DELETE CASCADE` and an index/unique starting with `workspace_id`. The one exception is `audit_events` (nullable, `SET NULL`) so the audit trail outlives a deleted workspace.
4. **Tenant-safe references:** a foreign key from one tenant table to another is **composite** `(workspace_id, x_id) → target(workspace_id, id)` (`app.db.mixins.tenant_fk`; targets declare `UNIQUE(workspace_id, id)`). The database itself refuses a lead that points at another tenant's company — application bugs cannot create cross-tenant links. 30 such references are tested with real cross-tenant inserts. Nullable relations are not checked when NULL (MATCH SIMPLE).
5. **Enumerations:** strings with named CHECK constraints (`app/domain.py` is the single list), not native enums, so adding a value is a small migration and SQLite/PostgreSQL behave alike.
6. **Duplicate protection (unique constraints, per workspace):** company domain, contact email, tag name (normalised), pipeline-stage key, suppression email, email account `(provider, provider_account_id)`, integration `(connector, external_account_id)`, conversation `(account, thread)`, message `(account, provider_message)`, workflow `(workflow, version)`, node/edge key per version, run event `(workflow, idempotency_key)`, step attempt `(run, node, attempt)`, side-effect `idempotency_key`, task and draft-send idempotency keys, notification `(user, dedupe_key)`. Provider ids make sync idempotent (upsert, never duplicate).
7. **Integrity beyond tenancy:** a run's pinned version must belong to the run's workflow; an edge's endpoints must be nodes of the same version; an activity needs a subject; money is `NUMERIC(14,2)` with a 3-letter currency; scores/probabilities are range-checked.
8. **No secrets outside the vault:** no column anywhere is named like a token/key/secret (tested). `email_accounts` and `integration_connections` reference `credential_secrets` by id. See "Credentials" below.
9. **Sample data:** `is_sample` on companies, contacts, leads, opportunities, tasks, conversations, messages and drafts marks seeded demo data so it can be labelled and cleaned up.

## Credentials

`app/security/credentials.py`: `EncryptedDbCredentialStore` (Fernet: AES + HMAC) behind a `CredentialStore` protocol.
Keys come from `CREDENTIAL_ENCRYPTION_KEYS="v2:<key>,v1:<key>"` (first = current; required in production, ephemeral in dev).
The plaintext envelope embeds `workspace_id` and `purpose`, both verified on read, so a ciphertext re-pointed at another
tenant or purpose is rejected. Rotation: add a new first key, call `rewrap()` per secret, then retire the old key.
Reads need the workspace id, so code that forgot scoping fails closed. A KMS/Vault-backed implementation can replace it
behind the same protocol.

## Deletion and retention

| Data | Behaviour |
|---|---|
| Companies, contacts, leads | **Soft delete** via `archived_at` (users archive and restore). Hard delete is for erasure requests and cascades dependents. |
| A lead's tags, activities, opportunities, drafts, tasks | Deleted with the lead (privacy erasure). Companies/tags/stages shared with other leads are kept. |
| Pipeline stages, companies referenced by leads, credentials referenced by accounts | **RESTRICT**: cannot be deleted while in use (reassign or archive first). |
| Tags | Hard delete; only the `lead_tags` links go. |
| Workspace | Hard delete cascades **every** tenant row (tested against a fully seeded workspace). `audit_events` are kept with `workspace_id = NULL`. The user account remains. |
| Disconnecting an integration | App deletes the `credential_secrets` row and nulls `credential_id`; metadata rows stay for history. |
| Audit events | Append-only; retention period to be set with the governance work (post-MVP). |
| Message content | Not stored (metadata + 500-char snippet). Body storage/retention is decided in MVP Prompt 10. |
| Usage records | Kept for metering; contain no content. |

Soft deletion is used only where users reasonably want records back; everything else is hard-deleted to keep erasure simple.

## Migrations

- Autogenerated, then reviewed and hand-extended (`0003`: membership role CHECK, default-stage backfill). Frozen data (default stages) is copied into the migration, never imported from app code.
- **Backfill:** existing workspaces receive the 8 default pipeline stages (tested on SQLite with pre-existing data; found and fixed a SQLite-only string-id bug).
- **Rollback:** `pnpm db:downgrade` / `alembic downgrade 0002` drops all 26 tables created in `0003`, **destroying CRM, email-metadata and workflow data**. Export first. Downgrade is repeatable (tested up→down→up→down). Identity/auth tables are untouched.
- PostgreSQL runs DDL transactionally (a failed migration leaves nothing behind). **SQLite does not**: a failed migration can leave a half-applied schema; delete the dev database file and re-run.
- `alembic check` runs in the tests (models and migrations must not drift).
- Never edit an applied migration; add a new one. Destructive changes need an expand/contract sequence.

## Safe evolution path

- **Add a column:** nullable (or with a server default) in a new revision; backfill separately for large tables.
- **Add an enum value:** edit `app/domain.py`, add a revision that replaces the CHECK constraint (batch mode on SQLite).
- **Message bodies:** add `message_bodies(workspace_id, message_id, body_text, retention_until)` rather than widening `messages`.
- **Teams/organisations:** add `organizations` and move `workspaces.organization_id`; `memberships` already carries roles. RBAC rules go in `deps.py` (`require_owner` is the pattern).
- **Search/scale:** add `pg_trgm`/GIN indexes (`leads.title`, `companies.name`) once Prompt 6 defines the queries; partition `audit_events`/`usage_records` by month if volume demands.
- **Lead fit criteria, saved views, custom fields:** new tables referencing `(workspace_id, id)` with `tenant_fk`; the guard tests will enforce the rules automatically.
- **ULIDs:** if time-ordered ids are wanted later, switch the default factory in `mixins.new_uuid`; the column type is unchanged.
