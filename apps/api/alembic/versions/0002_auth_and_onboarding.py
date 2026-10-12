"""Authentication, workspaces, audit events and onboarding.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-12

Rollback: `alembic downgrade 0001` drops all tables created here (destroys user data).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _ts(name: str) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("email_normalized", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_sign_in_at", sa.DateTime(timezone=True)),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email_normalized", name="uq_users_email_normalized"),
    )
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("demo_mode", sa.Boolean(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_workspaces"),
    )
    op.create_table(
        "memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_memberships"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="fk_memberships_workspace_id_workspaces", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_memberships_user_id_users", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_memberships_workspace_user"),
    )
    op.create_index("ix_memberships_workspace_id", "memberships", ["workspace_id"])
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        _ts("created_at"),
        _ts("last_seen_at"),
        _ts("expires_at"),
        sa.Column("user_agent", sa.String(200)),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_sessions_user_id_users", ondelete="CASCADE"),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        _ts("created_at"),
        _ts("expires_at"),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id", name="pk_password_reset_tokens"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_password_reset_tokens_user_id_users", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
    )
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid()),
        sa.Column("actor_user_id", sa.Uuid()),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("target_type", sa.String(60)),
        sa.Column("target_id", sa.String(64)),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("user_agent", sa.String(200)),
        sa.Column("details", sa.JSON(), nullable=False),
        _ts("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="fk_audit_events_workspace_id_workspaces", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], name="fk_audit_events_actor_user_id_users", ondelete="SET NULL"
        ),
    )
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"])
    op.create_index("ix_audit_events_workspace_created", "audit_events", ["workspace_id", "created_at"])
    op.create_table(
        "freelancer_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("role_title", sa.String(120)),
        sa.Column("summary", sa.String(500)),
        sa.Column("services", sa.JSON(), nullable=False),
        sa.Column("skills", sa.JSON(), nullable=False),
        sa.Column("target_clients", sa.Text()),
        sa.Column("industries", sa.JSON(), nullable=False),
        sa.Column("portfolio_urls", sa.JSON(), nullable=False),
        sa.Column("years_experience", sa.Integer()),
        sa.Column("experience_summary", sa.String(1000)),
        sa.Column("tone", sa.String(30)),
        sa.Column("tone_notes", sa.String(300)),
        sa.Column("business_goal", sa.String(40)),
        sa.Column("business_goal_notes", sa.String(300)),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_freelancer_profiles"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="fk_freelancer_profiles_workspace_id_workspaces", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("workspace_id", name="uq_freelancer_profiles_workspace_id"),
    )
    op.create_table(
        "onboarding_progress",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("current_step", sa.String(30), nullable=False),
        sa.Column("completed_steps", sa.JSON(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_onboarding_progress"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="fk_onboarding_progress_workspace_id_workspaces", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("workspace_id", name="uq_onboarding_progress_workspace_id"),
    )


def downgrade() -> None:
    for table in (
        "onboarding_progress",
        "freelancer_profiles",
        "audit_events",
        "password_reset_tokens",
        "sessions",
        "memberships",
        "workspaces",
        "users",
    ):
        op.drop_table(table)
