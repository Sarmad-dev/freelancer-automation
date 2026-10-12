"""Structural guards over the whole schema. These fail when a future model forgets tenancy rules,
so the guarantees below hold for tables that do not exist yet."""

from __future__ import annotations

import re

import pytest
from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.types import Uuid

from app.db import models  # noqa: F401  (registers every table)
from app.db.base import Base

TABLES: dict[str, Table] = dict(Base.metadata.tables)
TENANT = {n: t for n, t in TABLES.items() if "workspace_id" in t.c}

# Prompt 4's required entities (User/Workspace/Membership/FreelancerProfile/AuditEvent came earlier).
REQUIRED = {
    "users",
    "workspaces",
    "memberships",
    "freelancer_profiles",
    "knowledge_items",
    "companies",
    "contacts",
    "leads",
    "tags",
    "lead_tags",
    "activities",
    "tasks",
    "opportunities",
    "pipeline_stages",
    "email_accounts",
    "conversations",
    "messages",
    "drafts",
    "suppression_entries",
    "integration_connections",
    "workflows",
    "workflow_versions",
    "workflow_nodes",
    "workflow_edges",
    "workflow_runs",
    "workflow_step_runs",
    "approval_requests",
    "usage_records",
    "notifications",
    "audit_events",
    "credential_secrets",
}

# Intentional exceptions, each justified.
NULLABLE_WORKSPACE = {
    "audit_events"
}  # events survive workspace deletion for the audit trail (SET NULL)
NON_COMPOSITE_TENANT_FKS = {
    # Both endpoints are rows of the same workflow version, which itself has a tenant FK.
    "fk_workflow_edges_source_workflow_nodes",
    "fk_workflow_edges_target_workflow_nodes",
    # The pinned version must belong to the run's workflow (both already tenant-scoped).
    "fk_workflow_runs_version_belongs_to_workflow",
}


def test_all_required_entities_exist() -> None:
    assert set(TABLES) >= REQUIRED, sorted(REQUIRED - set(TABLES))


@pytest.mark.parametrize("name", sorted(TENANT))
def test_tenant_table_is_scoped_cascading_and_indexed(name: str) -> None:
    table = TENANT[name]
    column = table.c.workspace_id
    assert isinstance(column.type, Uuid | PG_UUID)

    fks = [
        fk
        for fk in column.foreign_keys
        if fk.constraint is not None and len(fk.constraint.columns) == 1
    ]
    assert fks, f"{name}.workspace_id must reference workspaces.id"
    fk = fks[0]
    assert fk.column.table.name == "workspaces"
    if name in NULLABLE_WORKSPACE:
        assert column.nullable and fk.ondelete == "SET NULL"
    else:
        assert not column.nullable, f"{name}.workspace_id must be NOT NULL"
        assert fk.ondelete == "CASCADE", f"{name}: deleting a workspace must delete its data"

    # Some index or unique constraint must lead with workspace_id so tenant queries stay fast.
    leading = [list(i.columns)[0].name for i in table.indexes if list(i.columns)]
    leading += [
        list(c.columns)[0].name
        for c in table.constraints
        if hasattr(c, "columns") and len(c.columns)
    ]
    assert "workspace_id" in leading, (
        f"{name} needs an index/unique constraint starting with workspace_id"
    )


@pytest.mark.parametrize("name", sorted(TENANT))
def test_tenant_to_tenant_references_are_composite(name: str) -> None:
    """A foreign key from one tenant table to another must include workspace_id, so the database itself
    rejects cross-tenant links (see app.db.mixins.tenant_fk)."""
    table = TENANT[name]
    for constraint in table.foreign_key_constraints:
        target = constraint.referred_table.name
        if target in ("workspaces", "users") or target not in TENANT:
            continue
        if constraint.name in NON_COMPOSITE_TENANT_FKS:
            continue
        cols = {c.name for c in constraint.columns}
        assert "workspace_id" in cols, (
            f"{name}: foreign key {constraint.name} to {target} is not tenant-scoped; "
            "use tenant_fk() so cross-workspace references are impossible"
        )


def test_referenced_tenant_tables_declare_the_unique_pair() -> None:
    """Composite targets need UNIQUE (workspace_id, id)."""
    for name, table in TENANT.items():
        for constraint in table.foreign_key_constraints:
            target = TABLES[constraint.referred_table.name]
            if (
                "workspace_id" not in {c.name for c in constraint.columns}
                or len(constraint.columns) != 2
            ):
                continue
            if constraint.referred_table.name == "workspaces":
                continue
            pairs = [
                {c.name for c in u.columns}
                for u in target.constraints
                if getattr(u, "columns", None) is not None
            ]
            assert {"workspace_id", "id"} in pairs, (
                f"{target.name} must be UNIQUE(workspace_id, id) ({name})"
            )


@pytest.mark.parametrize("name", sorted(set(TABLES) - {"app_metadata", "lead_tags"}))
def test_primary_keys_are_uuids(name: str) -> None:
    pk = list(TABLES[name].primary_key.columns)
    assert len(pk) == 1 and pk[0].name == "id" and isinstance(pk[0].type, Uuid | PG_UUID), name


# Rows that are immutable children of an already-timestamped parent, or that carry a domain timestamp.
OWN_TIMESTAMP = {"usage_records": "occurred_at"}
TIMESTAMPED_VIA_PARENT = {
    "workflow_nodes",
    "workflow_edges",
}  # immutable parts of a workflow version


@pytest.mark.parametrize("name", sorted(set(TENANT) - {"audit_events"}))
def test_rows_are_timestamped(name: str) -> None:
    if name in TIMESTAMPED_VIA_PARENT:
        assert "created_at" in TABLES["workflow_versions"].c
        return
    column = OWN_TIMESTAMP.get(name, "created_at")
    assert column in TENANT[name].c, f"{name} needs {column}"


_SECRETISH = re.compile(
    r"(access|refresh|id|bearer|auth)_?token|api_?key|client_?secret|private_?key|^secret$|^password$",
    re.I,
)
_ALLOWED_SECRET_LIKE = {
    ("users", "password_hash"),  # Argon2id hash, not a credential
    ("sessions", "token_hash"),  # SHA-256 of the session token
    ("password_reset_tokens", "token_hash"),
}


def test_no_table_has_a_raw_secret_column() -> None:
    """OAuth tokens/API keys must live only in credential_secrets (encrypted). Nothing else may even have
    a column that looks like one."""
    offenders = [
        f"{t.name}.{c.name}"
        for t in TABLES.values()
        for c in t.columns
        if _SECRETISH.search(c.name) and (t.name, c.name) not in _ALLOWED_SECRET_LIKE
    ]
    assert offenders == []
    ciphertext = TABLES["credential_secrets"].c.ciphertext
    assert str(ciphertext.type).upper().startswith(("BLOB", "BYTEA", "LARGEBINARY"))
    # Connection/account tables reference secrets by id only.
    assert "credential_id" in TABLES["email_accounts"].c
    assert "credential_id" in TABLES["integration_connections"].c


def test_status_like_columns_are_guarded_by_check_constraints() -> None:
    expected = {
        "leads": "status",
        "tasks": "status",
        "opportunities": "status",
        "drafts": "status",
        "workflow_runs": "status",
        "workflow_step_runs": "status",
        "approval_requests": "status",
        "email_accounts": "status",
        "conversations": "status",
        "messages": "delivery_state",
        "suppression_entries": "reason",
        "knowledge_items": "status",
        "workflows": "status",
    }
    for table, column in expected.items():
        sql = " ".join(
            str(c.sqltext)
            for c in TABLES[table].constraints
            if c.__class__.__name__ == "CheckConstraint"
        )
        assert column in sql, f"{table}.{column} needs a CHECK constraint"
