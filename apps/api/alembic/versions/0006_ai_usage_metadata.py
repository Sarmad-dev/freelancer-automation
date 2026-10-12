"""AI usage records: failure reason and prompt version.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-12

- usage_records.error_code: short machine code for a failed call ("timeout", "invalid_output", ...). Never a message,
  never content.
- usage_records.prompt_version: which versioned prompt template produced the call, so quality can be compared over time.

Rollback: ``alembic downgrade 0005`` drops the two columns (their data is lost).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('usage_records') as batch:
        batch.add_column(sa.Column('error_code', sa.String(length=40), nullable=True))
        batch.add_column(sa.Column('prompt_version', sa.String(length=20), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('usage_records') as batch:
        batch.drop_column('prompt_version')
        batch.drop_column('error_code')
