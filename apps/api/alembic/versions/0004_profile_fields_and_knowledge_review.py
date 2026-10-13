"""Profile fields, knowledge review lifecycle and version history.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-12

- freelancer_profiles: excluded_customers, differentiators, pricing_guidance, preferred_cta, version
- knowledge_items: is_enabled (separate from review status), created_by_user_id, UNIQUE(workspace_id, id)
- knowledge status values become draft | pending_review | approved | rejected; the old "disabled" status
  becomes status=draft + is_enabled=false (kept out of AI context either way)
- knowledge_item_versions: immutable content snapshots; existing items get a v1 snapshot

Rollback: ``alembic downgrade 0003`` drops the version history, the new profile columns (their data is
lost) and restores the old status set (rejected -> draft, disabled items -> status "disabled").
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

_OLD = "'draft', 'pending_review', 'approved', 'disabled'"
_NEW = "'draft', 'pending_review', 'approved', 'rejected'"


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # New NOT NULL columns carry server defaults so existing rows stay valid.
    with op.batch_alter_table("freelancer_profiles") as batch:
        batch.add_column(sa.Column("excluded_customers", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(sa.Column("differentiators", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(sa.Column("pricing_guidance", sa.String(length=1000), nullable=True))
        batch.add_column(sa.Column("preferred_cta", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")))
        batch.create_check_constraint(op.f("ck_freelancer_profiles_version_positive"), "version >= 1")

    with op.batch_alter_table("knowledge_items") as batch:
        batch.add_column(sa.Column("created_by_user_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.create_index("ix_knowledge_items_workspace_updated", ["workspace_id", "updated_at"], unique=False)
        batch.create_unique_constraint("uq_knowledge_items_workspace_id_id", ["workspace_id", "id"])
        batch.create_foreign_key(
            op.f("fk_knowledge_items_created_by_user_id_users"),
            "users",
            ["created_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # Needs UNIQUE(workspace_id, id) on knowledge_items (added above) for its composite foreign key.
    op.create_table(
        "knowledge_item_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.String(length=500), nullable=True),
        sa.Column("changed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["changed_by_user_id"],
            ["users.id"],
            name=op.f("fk_knowledge_item_versions_changed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "item_id"],
            ["knowledge_items.workspace_id", "knowledge_items.id"],
            name="fk_knowledge_item_versions_item_id_knowledge_items",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_knowledge_item_versions_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_item_versions")),
        sa.UniqueConstraint("item_id", "version", name="uq_knowledge_item_versions_item_version"),
    )
    op.create_index(
        "ix_knowledge_item_versions_workspace_item",
        "knowledge_item_versions",
        ["workspace_id", "item_id"],
    )

    # Data first, then the stricter CHECK: "disabled" was a status; it is now a switch.
    op.execute("UPDATE knowledge_items SET status = 'draft', is_enabled = false WHERE status = 'disabled'")
    with op.batch_alter_table("knowledge_items") as batch:
        batch.drop_constraint(op.f("ck_knowledge_items_status"), type_="check")
        batch.create_check_constraint(op.f("ck_knowledge_items_status"), f"status IN ({_NEW})")

    # Existing items get a v1 history snapshot so history is complete from day one.
    bind = op.get_bind()
    versions = sa.table(
        "knowledge_item_versions",
        sa.column("id", sa.Uuid()),
        sa.column("workspace_id", sa.Uuid()),
        sa.column("item_id", sa.Uuid()),
        sa.column("version", sa.Integer()),
        sa.column("kind", sa.String()),
        sa.column("title", sa.String()),
        sa.column("content", sa.Text()),
        sa.column("source_ref", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(UTC)

    def as_uuid(value: object) -> uuid.UUID:  # SQLite returns hex strings from raw SQL
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))

    rows = [
        {
            "id": uuid.uuid4(),
            "workspace_id": as_uuid(r.workspace_id),
            "item_id": as_uuid(r.id),
            "version": r.version,
            "kind": r.kind,
            "title": r.title,
            "content": r.content,
            "source_ref": r.source_ref,
            "created_at": now,
        }
        for r in bind.execute(
            sa.text("SELECT id, workspace_id, version, kind, title, content, source_ref FROM knowledge_items")
        ).fetchall()
    ]
    if rows:
        op.bulk_insert(versions, rows)


def downgrade() -> None:
    # The history table references knowledge_items(workspace_id, id): drop it before that constraint.
    op.drop_index("ix_knowledge_item_versions_workspace_item", table_name="knowledge_item_versions")
    op.drop_table("knowledge_item_versions")

    # Order matters: "rejected" must go while the new CHECK is active, and "disabled" may only be written
    # after the old (wider) CHECK is back, otherwise the rewrite violates whichever constraint is in force.
    op.execute("UPDATE knowledge_items SET status = 'draft' WHERE status = 'rejected'")
    with op.batch_alter_table("knowledge_items") as batch:
        batch.drop_constraint(op.f("ck_knowledge_items_status"), type_="check")
        batch.create_check_constraint(op.f("ck_knowledge_items_status"), f"status IN ({_OLD})")
    op.execute("UPDATE knowledge_items SET status = 'disabled' WHERE is_enabled = false")
    with op.batch_alter_table("knowledge_items") as batch:
        batch.drop_constraint(op.f("fk_knowledge_items_created_by_user_id_users"), type_="foreignkey")
        batch.drop_constraint("uq_knowledge_items_workspace_id_id", type_="unique")
        batch.drop_index("ix_knowledge_items_workspace_updated")
        batch.drop_column("is_enabled")
        batch.drop_column("created_by_user_id")

    with op.batch_alter_table("freelancer_profiles") as batch:
        batch.drop_constraint(op.f("ck_freelancer_profiles_version_positive"), type_="check")
        batch.drop_column("version")
        batch.drop_column("preferred_cta")
        batch.drop_column("pricing_guidance")
        batch.drop_column("differentiators")
        batch.drop_column("excluded_customers")

