"""Email accounts: health and rate-limit state; messages: link to the draft that produced them and a failure code.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-12

- email_accounts.last_health_check_at / rate_limited_until: when a real connection test last succeeded or failed, and
  until when the provider asked us to back off.
- messages.draft_id: the approved draft an outbound message was created from (one message per draft, so a retry of the
  same send reuses the same row and can never create a second message).
- email_accounts.sync_cursor is widened to 500 characters (provider page tokens can be long; downgrade narrows it again,
  which fails if a longer cursor is stored).
- messages.delivery_error_code: short machine code for a failed or unknown delivery (never a message or content).

Rollback: ``alembic downgrade 0006`` drops the columns, the unique key and the foreign key (their data is lost).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('email_accounts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('last_health_check_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('rate_limited_until', sa.DateTime(timezone=True), nullable=True))
        batch_op.alter_column('sync_cursor', existing_type=sa.String(length=200), type_=sa.String(length=500), existing_nullable=True)

    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('draft_id', sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column('delivery_error_code', sa.String(length=60), nullable=True))
        batch_op.create_foreign_key(
            'fk_messages_draft_id_drafts', 'drafts', ['workspace_id', 'draft_id'], ['workspace_id', 'id']
        )
        batch_op.create_unique_constraint('uq_messages_workspace_draft', ['workspace_id', 'draft_id'])


def downgrade() -> None:
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_constraint('uq_messages_workspace_draft', type_='unique')
        batch_op.drop_constraint('fk_messages_draft_id_drafts', type_='foreignkey')
        batch_op.drop_column('delivery_error_code')
        batch_op.drop_column('draft_id')

    with op.batch_alter_table('email_accounts', schema=None) as batch_op:
        batch_op.alter_column('sync_cursor', existing_type=sa.String(length=500), type_=sa.String(length=200), existing_nullable=True)
        batch_op.drop_column('rate_limited_until')
        batch_op.drop_column('last_health_check_at')
