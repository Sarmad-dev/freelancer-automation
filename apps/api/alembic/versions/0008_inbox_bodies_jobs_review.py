"""Inbox: stored message bodies, background email jobs, classification review state.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-13

- message_bodies: the text (and sanitised HTML) of a message, one row per message, deleted with it.
- email_jobs: background classification work, one row per (message, kind); a lease (locked_until) recovers crashed workers.
- conversations: classification_source / evidence / classified_message_id / classified_at, needs_review + review_reason.
- messages.is_bounce: delivery-failure notices from the mail system.

Rollback: ``alembic downgrade 0007`` drops the two tables and the new columns (stored bodies, jobs and review state are lost).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None

REVIEW_REASONS = ("low_confidence", "fallback", "injection_suspected", "classification_failed", "unsubscribe_unconfirmed")
SOURCES = ("model", "demo_ai", "rules_fallback", "manual")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.create_table('message_bodies',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('message_id', sa.Uuid(), nullable=False),
    sa.Column('body_text', sa.Text(), nullable=False),
    sa.Column('body_html', sa.Text(), nullable=True),
    sa.Column('text_truncated', sa.Boolean(), nullable=False),
    sa.Column('images_blocked', sa.Boolean(), nullable=False),
    sa.Column('sanitizer_version', sa.String(length=10), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id', 'message_id'], ['messages.workspace_id', 'messages.id'], name='fk_message_bodies_message_id_messages', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_message_bodies_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_message_bodies')),
    sa.UniqueConstraint('message_id', name='uq_message_bodies_message'),
    )

    op.create_table('email_jobs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('message_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('run_after', sa.DateTime(timezone=True), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error_code', sa.String(length=40), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("kind IN ('classify')", name=op.f('ck_email_jobs_kind')),
    sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed', 'skipped')", name=op.f('ck_email_jobs_status')),
    sa.CheckConstraint('attempts >= 0 AND max_attempts >= 1', name=op.f('ck_email_jobs_attempts_valid')),
    sa.ForeignKeyConstraint(['workspace_id', 'conversation_id'], ['conversations.workspace_id', 'conversations.id'], name='fk_email_jobs_conversation_id_conversations', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id', 'message_id'], ['messages.workspace_id', 'messages.id'], name='fk_email_jobs_message_id_messages', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_email_jobs_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_email_jobs')),
    sa.UniqueConstraint('message_id', 'kind', name='uq_email_jobs_message_kind'),
    )
    with op.batch_alter_table('email_jobs', schema=None) as batch_op:
        batch_op.create_index('ix_email_jobs_status_run_after', ['status', 'run_after'], unique=False)

    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('classification_source', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('classification_evidence', sa.JSON(), nullable=False, server_default='[]'))
        batch_op.add_column(sa.Column('classified_message_id', sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column('classified_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('needs_review', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('review_reason', sa.String(length=30), nullable=True))
        batch_op.create_check_constraint('review_reason_valid', f"review_reason IS NULL OR review_reason IN ({_in(REVIEW_REASONS)})")
        batch_op.create_check_constraint('classification_source_valid', f"classification_source IS NULL OR classification_source IN ({_in(SOURCES)})")

    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_bounce', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_column('is_bounce')

    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.drop_constraint(op.f('ck_conversations_classification_source_valid'), type_='check')
        batch_op.drop_constraint(op.f('ck_conversations_review_reason_valid'), type_='check')
        batch_op.drop_column('review_reason')
        batch_op.drop_column('needs_review')
        batch_op.drop_column('classified_at')
        batch_op.drop_column('classified_message_id')
        batch_op.drop_column('classification_evidence')
        batch_op.drop_column('classification_source')

    with op.batch_alter_table('email_jobs', schema=None) as batch_op:
        batch_op.drop_index('ix_email_jobs_status_run_after')
    op.drop_table('email_jobs')
    op.drop_table('message_bodies')
