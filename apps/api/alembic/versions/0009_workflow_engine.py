"""Workflow engine: runnable runs (cursor, context, lease, cancel flag), validated versions, one approval per step.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-13

- workflows.trigger_event: trigger of the active version, so an event can find the workflows that listen to it.
- workflow_versions: valid / issues / trigger_event (result of validation when the version was saved).
- workflow_runs: subject, current node, context, steps_taken, attempt_floor, lease (locked_until, lock_token),
  cancel_requested_at, started_by_user_id; indexes for the queue and for "is this subject already in a run".
- workflow_step_runs.port: the output port a step left through.
- approval_requests: unique (workspace, step_run) so a retry cannot ask a person twice.

Rollback: ``alembic downgrade 0008`` drops the new columns, indexes and constraint (run progress state is lost; runs and
versions remain but versions lose their validation result).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('workflows', schema=None) as batch_op:
        batch_op.add_column(sa.Column('trigger_event', sa.String(length=30), nullable=True))

    with op.batch_alter_table('workflow_versions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('valid', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('issues', sa.JSON(), nullable=False, server_default='[]'))
        batch_op.add_column(sa.Column('trigger_event', sa.String(length=30), nullable=True))

    with op.batch_alter_table('workflow_runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('subject_type', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('subject_id', sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column('current_node_key', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('context', sa.JSON(), nullable=False, server_default='{}'))
        batch_op.add_column(sa.Column('steps_taken', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('attempt_floor', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('lock_token', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('cancel_requested_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('started_by_user_id', sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(batch_op.f('fk_workflow_runs_started_by_user_id_users'), 'users', ['started_by_user_id'], ['id'], ondelete='SET NULL')
        batch_op.create_check_constraint('subject_type_valid', "subject_type IS NULL OR subject_type IN ('lead', 'conversation')")
        batch_op.create_index('ix_workflow_runs_status_wake', ['status', 'wake_at'], unique=False)
        batch_op.create_index('ix_workflow_runs_subject', ['workspace_id', 'workflow_id', 'subject_id'], unique=False)

    with op.batch_alter_table('workflow_step_runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('port', sa.String(length=60), nullable=True))

    with op.batch_alter_table('approval_requests', schema=None) as batch_op:
        batch_op.create_unique_constraint('uq_approval_requests_step', ['workspace_id', 'step_run_id'])


def downgrade() -> None:
    with op.batch_alter_table('approval_requests', schema=None) as batch_op:
        batch_op.drop_constraint('uq_approval_requests_step', type_='unique')

    with op.batch_alter_table('workflow_step_runs', schema=None) as batch_op:
        batch_op.drop_column('port')

    with op.batch_alter_table('workflow_runs', schema=None) as batch_op:
        batch_op.drop_index('ix_workflow_runs_subject')
        batch_op.drop_index('ix_workflow_runs_status_wake')
        batch_op.drop_constraint(op.f('ck_workflow_runs_subject_type_valid'), type_='check')
        batch_op.drop_constraint(op.f('fk_workflow_runs_started_by_user_id_users'), type_='foreignkey')
        for column in ('started_by_user_id', 'cancel_requested_at', 'lock_token', 'locked_until', 'attempt_floor',
                       'steps_taken', 'context', 'current_node_key', 'subject_id', 'subject_type'):
            batch_op.drop_column(column)

    with op.batch_alter_table('workflow_versions', schema=None) as batch_op:
        batch_op.drop_column('trigger_event')
        batch_op.drop_column('issues')
        batch_op.drop_column('valid')

    with op.batch_alter_table('workflows', schema=None) as batch_op:
        batch_op.drop_column('trigger_event')
