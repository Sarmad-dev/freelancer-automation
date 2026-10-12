"""Leads: fit scoring configuration, budget signal and CSV import jobs.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-12

- fit_scoring_configs: one versioned row of user-defined criteria per workspace
- import_jobs: CSV import history with counts and a capped per-row error list (no file contents)
- leads: budget_signal (user-supplied), fit_scored_at, index on archived_at
- Scores that pre-date explanations (hard-coded demo values, never computed) are cleared so no lead shows
  a number that cannot be explained; they are recomputed from real criteria.

Rollback: ``alembic downgrade 0004`` drops the two tables and the new lead columns (their data is lost).
Cleared legacy scores are not restored.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('fit_scoring_configs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('criteria', sa.JSON(), nullable=False),
    sa.Column('updated_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('version >= 1', name=op.f('ck_fit_scoring_configs_version_positive')),
    sa.ForeignKeyConstraint(['updated_by_user_id'], ['users.id'], name=op.f('fk_fit_scoring_configs_updated_by_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_fit_scoring_configs_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_fit_scoring_configs')),
    sa.UniqueConstraint('workspace_id', 'id', name='uq_fit_scoring_configs_workspace_id_id'),
    sa.UniqueConstraint('workspace_id', name='uq_fit_scoring_configs_workspace')
    )
    op.create_table('import_jobs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('filename', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('duplicate_strategy', sa.String(length=10), nullable=False),
    sa.Column('mapping', sa.JSON(), nullable=False),
    sa.Column('total_rows', sa.Integer(), nullable=False),
    sa.Column('created_count', sa.Integer(), nullable=False),
    sa.Column('updated_count', sa.Integer(), nullable=False),
    sa.Column('skipped_count', sa.Integer(), nullable=False),
    sa.Column('error_count', sa.Integer(), nullable=False),
    sa.Column('errors', sa.JSON(), nullable=False),
    sa.Column('errors_truncated', sa.Boolean(), nullable=False),
    sa.Column('created_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("duplicate_strategy IN ('skip', 'update')", name=op.f('ck_import_jobs_duplicate_strategy')),
    sa.CheckConstraint("status IN ('completed', 'failed')", name=op.f('ck_import_jobs_status')),
    sa.CheckConstraint('total_rows >= 0 AND created_count >= 0 AND updated_count >= 0 AND skipped_count >= 0 AND error_count >= 0', name=op.f('ck_import_jobs_counts_non_negative')),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], name=op.f('fk_import_jobs_created_by_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_import_jobs_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_import_jobs')),
    sa.UniqueConstraint('workspace_id', 'id', name='uq_import_jobs_workspace_id_id')
    )
    with op.batch_alter_table('import_jobs', schema=None) as batch_op:
        batch_op.create_index('ix_import_jobs_workspace_created', ['workspace_id', 'created_at'], unique=False)

    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.add_column(sa.Column('fit_scored_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('budget_signal', sa.String(length=10), nullable=True))
        batch_op.create_index('ix_leads_workspace_archived', ['workspace_id', 'archived_at'], unique=False)
        batch_op.create_check_constraint(
            op.f('ck_leads_budget_signal_values'),
            "budget_signal IS NULL OR budget_signal IN ('low', 'medium', 'high')",
        )

    # Clear scores that were never computed from criteria (no versioned explanation).
    bind = op.get_bind()
    leads = sa.table(
        "leads",
        sa.column("id", sa.Uuid()),
        sa.column("fit_score", sa.Integer()),
        sa.column("fit_explanation", sa.JSON()),
    )
    for row in bind.execute(sa.select(leads.c.id, leads.c.fit_explanation).where(leads.c.fit_score.is_not(None))):
        explanation = row.fit_explanation
        if not (isinstance(explanation, dict) and explanation.get("version") == 1):
            bind.execute(
                sa.update(leads).where(leads.c.id == row.id).values(fit_score=None, fit_explanation=None)
            )



def downgrade() -> None:
    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.drop_constraint(op.f('ck_leads_budget_signal_values'), type_='check')
        batch_op.drop_index('ix_leads_workspace_archived')
        batch_op.drop_column('budget_signal')
        batch_op.drop_column('fit_scored_at')

    with op.batch_alter_table('import_jobs', schema=None) as batch_op:
        batch_op.drop_index('ix_import_jobs_workspace_created')

    op.drop_table('import_jobs')
    op.drop_table('fit_scoring_configs')
