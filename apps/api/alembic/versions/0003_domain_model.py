"""Domain model: CRM, email metadata, workflows, approvals, usage, notifications.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-12

Adds 26 tenant-scoped tables (see docs/DATA_MODEL.md), a role CHECK on memberships, and backfills the
default pipeline stages for workspaces created before this revision.

Rollback: ``alembic downgrade 0002`` drops every table created here, including any CRM, email-metadata and
workflow data entered since. Export first if that data matters. Downgrade is not lossless by design.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

# Frozen copy: migrations must not import application code that may change later.
_DEFAULT_STAGES = (
    ("new", "New", False, False),
    ("contacted", "Contacted", False, False),
    ("replied", "Replied", False, False),
    ("qualified", "Qualified", False, False),
    ("meeting", "Meeting", False, False),
    ("proposal", "Proposal", False, False),
    ("won", "Won", True, False),
    ("lost", "Lost", False, True),
)


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('companies',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('domain', sa.String(length=253), nullable=True),
    sa.Column('domain_normalized', sa.String(length=253), nullable=True),
    sa.Column('website', sa.String(length=500), nullable=True),
    sa.Column('industry', sa.String(length=100), nullable=True),
    sa.Column('size_label', sa.String(length=40), nullable=True),
    sa.Column('location', sa.String(length=200), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('source', sa.String(length=100), nullable=True),
    sa.Column('source_retrieved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_sample', sa.Boolean(), nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_companies_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_companies')),
    sa.UniqueConstraint('workspace_id', 'domain_normalized', name='uq_companies_workspace_domain'),
    sa.UniqueConstraint('workspace_id', 'id', name='uq_companies_workspace_id_id')
    )
    op.create_index('ix_companies_workspace_name', 'companies', ['workspace_id', 'name'], unique=False)
    op.create_table('credential_secrets',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('purpose', sa.String(length=60), nullable=False),
    sa.Column('ciphertext', sa.LargeBinary(), nullable=False),
    sa.Column('key_id', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('rotated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_credential_secrets_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_credential_secrets')),
    sa.UniqueConstraint('workspace_id', 'id', name='uq_credential_secrets_workspace_id_id')
    )
    op.create_table('knowledge_items',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('source_type', sa.String(length=20), nullable=False),
    sa.Column('source_ref', sa.String(length=500), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('approved_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("kind IN ('fact', 'service', 'case_study', 'portfolio', 'pricing', 'other')", name=op.f('ck_knowledge_items_kind')),
    sa.CheckConstraint("source_type IN ('manual', 'upload', 'extracted')", name=op.f('ck_knowledge_items_source_type')),
    sa.CheckConstraint("status IN ('draft', 'pending_review', 'approved', 'disabled')", name=op.f('ck_knowledge_items_status')),
    sa.CheckConstraint('version >= 1', name=op.f('ck_knowledge_items_version_positive')),
    sa.ForeignKeyConstraint(['approved_by_user_id'], ['users.id'], name=op.f('fk_knowledge_items_approved_by_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_knowledge_items_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_knowledge_items'))
    )
    op.create_index('ix_knowledge_items_workspace_status', 'knowledge_items', ['workspace_id', 'status'], unique=False)
    op.create_table('notifications',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=40), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('body', sa.String(length=500), nullable=True),
    sa.Column('link', sa.String(length=300), nullable=True),
    sa.Column('dedupe_key', sa.String(length=120), nullable=True),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_notifications_user_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_notifications_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notifications')),
    sa.UniqueConstraint('user_id', 'dedupe_key', name='uq_notifications_user_dedupe')
    )
    op.create_index('ix_notifications_workspace_user_read', 'notifications', ['workspace_id', 'user_id', 'read_at'], unique=False)
    op.create_table('pipeline_stages',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('key', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=60), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('is_won', sa.Boolean(), nullable=False),
    sa.Column('is_lost', sa.Boolean(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('position >= 0', name=op.f('ck_pipeline_stages_position_non_negative')),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_pipeline_stages_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pipeline_stages')),
    sa.UniqueConstraint('workspace_id', 'id', name='uq_pipeline_stages_workspace_id_id'),
    sa.UniqueConstraint('workspace_id', 'key', name='uq_pipeline_stages_workspace_key')
    )
    op.create_table('suppression_entries',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('email_normalized', sa.String(length=254), nullable=False),
    sa.Column('reason', sa.String(length=20), nullable=False),
    sa.Column('source', sa.String(length=100), nullable=True),
    sa.Column('note', sa.String(length=300), nullable=True),
    sa.Column('created_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("reason IN ('unsubscribe', 'bounce', 'complaint', 'manual', 'replied_stop')", name=op.f('ck_suppression_entries_reason')),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], name=op.f('fk_suppression_entries_created_by_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_suppression_entries_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_suppression_entries')),
    sa.UniqueConstraint('workspace_id', 'email_normalized', name='uq_suppression_workspace_email')
    )
    op.create_table('tags',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('name_normalized', sa.String(length=50), nullable=False),
    sa.Column('color', sa.String(length=7), nullable=True),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('color IS NULL OR length(color) = 7', name=op.f('ck_tags_color_hex_length')),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_tags_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tags')),
    sa.UniqueConstraint('workspace_id', 'id', name='uq_tags_workspace_id_id'),
    sa.UniqueConstraint('workspace_id', 'name_normalized', name='uq_tags_workspace_name')
    )
    op.create_table('usage_records',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=40), nullable=False),
    sa.Column('provider', sa.String(length=40), nullable=True),
    sa.Column('model', sa.String(length=80), nullable=True),
    sa.Column('task_type', sa.String(length=40), nullable=True),
    sa.Column('input_tokens', sa.Integer(), nullable=True),
    sa.Column('output_tokens', sa.Integer(), nullable=True),
    sa.Column('estimated_cost_micros', sa.Integer(), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('success', sa.Boolean(), nullable=False),
    sa.Column('is_mock', sa.Boolean(), nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=True),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('input_tokens IS NULL OR input_tokens >= 0', name=op.f('ck_usage_records_input_tokens_non_negative')),
    sa.CheckConstraint('output_tokens IS NULL OR output_tokens >= 0', name=op.f('ck_usage_records_output_tokens_non_negative')),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_usage_records_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_usage_records'))
    )
    op.create_index('ix_usage_records_workspace_kind_time', 'usage_records', ['workspace_id', 'kind', 'occurred_at'], unique=False)
    op.create_index('ix_usage_records_workspace_time', 'usage_records', ['workspace_id', 'occurred_at'], unique=False)
    op.create_table('workflows',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.String(length=1000), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('mode', sa.String(length=10), nullable=False),
    sa.Column('active_version', sa.Integer(), nullable=True),
    sa.Column('created_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("mode IN ('test', 'live')", name=op.f('ck_workflows_mode')),
    sa.CheckConstraint("status IN ('draft', 'active', 'paused', 'archived')", name=op.f('ck_workflows_status')),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], name=op.f('fk_workflows_created_by_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_workflows_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workflows')),
    sa.UniqueConstraint('workspace_id', 'id', name='uq_workflows_workspace_id_id')
    )
    op.create_index('ix_workflows_workspace_status', 'workflows', ['workspace_id', 'status'], unique=False)
    op.create_table('contacts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=True),
    sa.Column('full_name', sa.String(length=200), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=True),
    sa.Column('email_normalized', sa.String(length=254), nullable=True),
    sa.Column('role_title', sa.String(length=120), nullable=True),
    sa.Column('phone', sa.String(length=40), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('source', sa.String(length=100), nullable=True),
    sa.Column('source_retrieved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_sample', sa.Boolean(), nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id', 'company_id'], ['companies.workspace_id', 'companies.id'], name='fk_contacts_company_id_companies'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_contacts_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_contacts')),
    sa.UniqueConstraint('workspace_id', 'email_normalized', name='uq_contacts_workspace_email'),
    sa.UniqueConstraint('workspace_id', 'id', name='uq_contacts_workspace_id_id')
    )
    op.create_index('ix_contacts_workspace_company', 'contacts', ['workspace_id', 'company_id'], unique=False)
    op.create_index('ix_contacts_workspace_name', 'contacts', ['workspace_id', 'full_name'], unique=False)
    op.create_table('email_accounts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('provider_account_id', sa.String(length=200), nullable=False),
    sa.Column('email_address', sa.String(length=254), nullable=False),
    sa.Column('display_name', sa.String(length=120), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('is_demo', sa.Boolean(), nullable=False),
    sa.Column('credential_id', sa.Uuid(), nullable=True),
    sa.Column('granted_scopes', sa.JSON(), nullable=False),
    sa.Column('sync_cursor', sa.String(length=200), nullable=True),
    sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error_code', sa.String(length=60), nullable=True),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("provider IN ('gmail', 'outlook', 'demo')", name=op.f('ck_email_accounts_provider')),
    sa.CheckConstraint("status IN ('connected', 'demo', 'needs_reauth', 'disconnected', 'error')", name=op.f('ck_email_accounts_status')),
    sa.ForeignKeyConstraint(['workspace_id', 'credential_id'], ['credential_secrets.workspace_id', 'credential_secrets.id'], name='fk_email_accounts_credential_id_credential_secrets'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_email_accounts_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_email_accounts')),
    sa.UniqueConstraint('workspace_id', 'id', name='uq_email_accounts_workspace_id_id'),
    sa.UniqueConstraint('workspace_id', 'provider', 'provider_account_id', name='uq_email_accounts_provider_account')
    )
    op.create_table('integration_connections',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('connector', sa.String(length=40), nullable=False),
    sa.Column('external_account_id', sa.String(length=200), nullable=False),
    sa.Column('display_name', sa.String(length=120), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('credential_id', sa.Uuid(), nullable=True),
    sa.Column('granted_scopes', sa.JSON(), nullable=False),
    sa.Column('capabilities', sa.JSON(), nullable=False),
    sa.Column('config', sa.JSON(), nullable=False),
    sa.Column('last_health_check_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error_code', sa.String(length=60), nullable=True),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('connected', 'demo', 'needs_reauth', 'disconnected', 'error')", name=op.f('ck_integration_connections_status')),
    sa.ForeignKeyConstraint(['workspace_id', 'credential_id'], ['credential_secrets.workspace_id', 'credential_secrets.id'], name='fk_integration_connections_credential_id_credential_secrets'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_integration_connections_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_integration_connections')),
    sa.UniqueConstraint('workspace_id', 'connector', 'external_account_id', name='uq_integration_connections_account'),
    sa.UniqueConstraint('workspace_id', 'id', name='uq_integration_connections_workspace_id_id')
    )
    op.create_index('ix_integration_connections_workspace_connector', 'integration_connections', ['workspace_id', 'connector'], unique=False)
    op.create_table('workflow_versions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workflow_id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('schema_version', sa.Integer(), nullable=False),
    sa.Column('checksum', sa.String(length=64), nullable=False),
    sa.Column('note', sa.String(length=300), nullable=True),
    sa.Column('created_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('version >= 1', name=op.f('ck_workflow_versions_version_positive')),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], name=op.f('fk_workflow_versions_created_by_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id', 'workflow_id'], ['workflows.workspace_id', 'workflows.id'], name='fk_workflow_versions_workflow_id_workflows', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_workflow_versions_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workflow_versions')),
    sa.UniqueConstraint('workflow_id', 'id', name='uq_workflow_versions_workflow_id_id'),
    sa.UniqueConstraint('workflow_id', 'version', name='uq_workflow_versions_workflow_version'),
    sa.UniqueConstraint('workspace_id', 'id', name='uq_workflow_versions_workspace_id_id')
    )
    op.create_table('leads',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=True),
    sa.Column('contact_id', sa.Uuid(), nullable=True),
    sa.Column('stage_id', sa.Uuid(), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('source', sa.String(length=100), nullable=True),
    sa.Column('source_retrieved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('industry', sa.String(length=100), nullable=True),
    sa.Column('location', sa.String(length=200), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('fit_score', sa.Integer(), nullable=True),
    sa.Column('fit_explanation', sa.JSON(), nullable=True),
    sa.Column('next_action', sa.String(length=300), nullable=True),
    sa.Column('next_action_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_activity_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('owner_user_id', sa.Uuid(), nullable=True),
    sa.Column('is_sample', sa.Boolean(), nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('new', 'contacted', 'replied', 'qualified', 'nurturing', 'won', 'lost')", name=op.f('ck_leads_status')),
    sa.CheckConstraint('fit_score IS NULL OR (fit_score >= 0 AND fit_score <= 100)', name=op.f('ck_leads_fit_score_range')),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], name=op.f('fk_leads_owner_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id', 'company_id'], ['companies.workspace_id', 'companies.id'], name='fk_leads_company_id_companies'),
    sa.ForeignKeyConstraint(['workspace_id', 'contact_id'], ['contacts.workspace_id', 'contacts.id'], name='fk_leads_contact_id_contacts'),
    sa.ForeignKeyConstraint(['workspace_id', 'stage_id'], ['pipeline_stages.workspace_id', 'pipeline_stages.id'], name='fk_leads_stage_id_pipeline_stages'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_leads_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_leads')),
    sa.UniqueConstraint('workspace_id', 'id', name='uq_leads_workspace_id_id')
    )
    op.create_index('ix_leads_workspace_company', 'leads', ['workspace_id', 'company_id'], unique=False)
    op.create_index('ix_leads_workspace_contact', 'leads', ['workspace_id', 'contact_id'], unique=False)
    op.create_index('ix_leads_workspace_fit', 'leads', ['workspace_id', 'fit_score'], unique=False)
    op.create_index('ix_leads_workspace_last_activity', 'leads', ['workspace_id', 'last_activity_at'], unique=False)
    op.create_index('ix_leads_workspace_status', 'leads', ['workspace_id', 'status'], unique=False)
    op.create_table('workflow_nodes',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('version_id', sa.Uuid(), nullable=False),
    sa.Column('node_key', sa.String(length=80), nullable=False),
    sa.Column('type', sa.String(length=40), nullable=False),
    sa.Column('label', sa.String(length=120), nullable=True),
    sa.Column('config', sa.JSON(), nullable=False),
    sa.Column('position_x', sa.Float(), nullable=False),
    sa.Column('position_y', sa.Float(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id', 'version_id'], ['workflow_versions.workspace_id', 'workflow_versions.id'], name='fk_workflow_nodes_version_id_workflow_versions', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_workflow_nodes_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workflow_nodes')),
    sa.UniqueConstraint('version_id', 'node_key', name='uq_workflow_nodes_version_key')
    )
    op.create_index('ix_workflow_nodes_workspace_type', 'workflow_nodes', ['workspace_id', 'type'], unique=False)
    op.create_table('workflow_runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workflow_id', sa.Uuid(), nullable=False),
    sa.Column('version_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('mode', sa.String(length=10), nullable=False),
    sa.Column('trigger_type', sa.String(length=40), nullable=False),
    sa.Column('trigger_payload', sa.JSON(), nullable=False),
    sa.Column('idempotency_key', sa.String(length=200), nullable=True),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('wake_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_category', sa.String(length=40), nullable=True),
    sa.Column('error_summary', sa.String(length=500), nullable=True),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("mode IN ('test', 'live')", name=op.f('ck_workflow_runs_mode')),
    sa.CheckConstraint("status IN ('queued', 'running', 'waiting_approval', 'waiting_delay', 'succeeded', 'failed', 'cancelled')", name=op.f('ck_workflow_runs_status')),
    sa.ForeignKeyConstraint(['workflow_id', 'version_id'], ['workflow_versions.workflow_id', 'workflow_versions.id'], name='fk_workflow_runs_version_belongs_to_workflow'),
    sa.ForeignKeyConstraint(['workspace_id', 'version_id'], ['workflow_versions.workspace_id', 'workflow_versions.id'], name='fk_workflow_runs_version_id_workflow_versions'),
    sa.ForeignKeyConstraint(['workspace_id', 'workflow_id'], ['workflows.workspace_id', 'workflows.id'], name='fk_workflow_runs_workflow_id_workflows', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_workflow_runs_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workflow_runs')),
    sa.UniqueConstraint('workspace_id', 'id', name='uq_workflow_runs_workspace_id_id'),
    sa.UniqueConstraint('workspace_id', 'workflow_id', 'idempotency_key', name='uq_workflow_runs_event')
    )
    op.create_index('ix_workflow_runs_correlation', 'workflow_runs', ['correlation_id'], unique=False)
    op.create_index('ix_workflow_runs_workspace_status', 'workflow_runs', ['workspace_id', 'status'], unique=False)
    op.create_index('ix_workflow_runs_workspace_workflow_started', 'workflow_runs', ['workspace_id', 'workflow_id', 'started_at'], unique=False)
    op.create_table('conversations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('email_account_id', sa.Uuid(), nullable=False),
    sa.Column('provider_thread_id', sa.String(length=200), nullable=False),
    sa.Column('subject', sa.String(length=500), nullable=True),
    sa.Column('lead_id', sa.Uuid(), nullable=True),
    sa.Column('contact_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('unread', sa.Boolean(), nullable=False),
    sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('classification', sa.String(length=20), nullable=True),
    sa.Column('classification_confidence', sa.Float(), nullable=True),
    sa.Column('classification_explanation', sa.String(length=1000), nullable=True),
    sa.Column('is_sample', sa.Boolean(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("classification IS NULL OR classification IN ('interested', 'question', 'objection', 'not_now', 'referral', 'out_of_office', 'unsubscribe', 'irrelevant')", name=op.f('ck_conversations_classification_valid')),
    sa.CheckConstraint("status IN ('open', 'archived')", name=op.f('ck_conversations_status')),
    sa.CheckConstraint('classification_confidence IS NULL OR (classification_confidence >= 0 AND classification_confidence <= 1)', name=op.f('ck_conversations_confidence_range')),
    sa.ForeignKeyConstraint(['workspace_id', 'contact_id'], ['contacts.workspace_id', 'contacts.id'], name='fk_conversations_contact_id_contacts'),
    sa.ForeignKeyConstraint(['workspace_id', 'email_account_id'], ['email_accounts.workspace_id', 'email_accounts.id'], name='fk_conversations_email_account_id_email_accounts', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id', 'lead_id'], ['leads.workspace_id', 'leads.id'], name='fk_conversations_lead_id_leads'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_conversations_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_conversations')),
    sa.UniqueConstraint('email_account_id', 'provider_thread_id', name='uq_conversations_account_thread'),
    sa.UniqueConstraint('workspace_id', 'id', name='uq_conversations_workspace_id_id')
    )
    op.create_index('ix_conversations_workspace_last_message', 'conversations', ['workspace_id', 'last_message_at'], unique=False)
    op.create_index('ix_conversations_workspace_lead', 'conversations', ['workspace_id', 'lead_id'], unique=False)
    op.create_table('lead_tags',
    sa.Column('lead_id', sa.Uuid(), nullable=False),
    sa.Column('tag_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id', 'lead_id'], ['leads.workspace_id', 'leads.id'], name='fk_lead_tags_lead_id_leads', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id', 'tag_id'], ['tags.workspace_id', 'tags.id'], name='fk_lead_tags_tag_id_tags', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_lead_tags_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('lead_id', 'tag_id', name='pk_lead_tags')
    )
    op.create_index('ix_lead_tags_workspace_tag', 'lead_tags', ['workspace_id', 'tag_id'], unique=False)
    op.create_table('opportunities',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('lead_id', sa.Uuid(), nullable=False),
    sa.Column('stage_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('value_amount', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('probability', sa.Integer(), nullable=True),
    sa.Column('expected_close_date', sa.Date(), nullable=True),
    sa.Column('next_action', sa.String(length=300), nullable=True),
    sa.Column('loss_reason', sa.String(length=300), nullable=True),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('owner_user_id', sa.Uuid(), nullable=True),
    sa.Column('is_sample', sa.Boolean(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('open', 'won', 'lost')", name=op.f('ck_opportunities_status')),
    sa.CheckConstraint('length(currency) = 3', name=op.f('ck_opportunities_currency_iso_length')),
    sa.CheckConstraint('probability IS NULL OR (probability >= 0 AND probability <= 100)', name=op.f('ck_opportunities_probability_range')),
    sa.CheckConstraint('value_amount IS NULL OR value_amount >= 0', name=op.f('ck_opportunities_value_non_negative')),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], name=op.f('fk_opportunities_owner_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id', 'lead_id'], ['leads.workspace_id', 'leads.id'], name='fk_opportunities_lead_id_leads', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id', 'stage_id'], ['pipeline_stages.workspace_id', 'pipeline_stages.id'], name='fk_opportunities_stage_id_pipeline_stages'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_opportunities_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_opportunities')),
    sa.UniqueConstraint('workspace_id', 'id', name='uq_opportunities_workspace_id_id')
    )
    op.create_index('ix_opportunities_workspace_lead', 'opportunities', ['workspace_id', 'lead_id'], unique=False)
    op.create_index('ix_opportunities_workspace_stage', 'opportunities', ['workspace_id', 'stage_id'], unique=False)
    op.create_index('ix_opportunities_workspace_status', 'opportunities', ['workspace_id', 'status'], unique=False)
    op.create_table('workflow_edges',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('version_id', sa.Uuid(), nullable=False),
    sa.Column('edge_key', sa.String(length=80), nullable=False),
    sa.Column('source_key', sa.String(length=80), nullable=False),
    sa.Column('target_key', sa.String(length=80), nullable=False),
    sa.Column('branch', sa.String(length=60), nullable=True),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['version_id', 'source_key'], ['workflow_nodes.version_id', 'workflow_nodes.node_key'], name='fk_workflow_edges_source_workflow_nodes', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['version_id', 'target_key'], ['workflow_nodes.version_id', 'workflow_nodes.node_key'], name='fk_workflow_edges_target_workflow_nodes', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id', 'version_id'], ['workflow_versions.workspace_id', 'workflow_versions.id'], name='fk_workflow_edges_version_id_workflow_versions', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_workflow_edges_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workflow_edges')),
    sa.UniqueConstraint('version_id', 'edge_key', name='uq_workflow_edges_version_key')
    )
    op.create_table('workflow_step_runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('node_key', sa.String(length=80), nullable=False),
    sa.Column('attempt', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('idempotency_key', sa.String(length=200), nullable=True),
    sa.Column('input_summary', sa.JSON(), nullable=False),
    sa.Column('output_summary', sa.JSON(), nullable=False),
    sa.Column('error_category', sa.String(length=40), nullable=True),
    sa.Column('error_summary', sa.String(length=500), nullable=True),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('pending', 'running', 'succeeded', 'failed', 'skipped', 'waiting', 'cancelled')", name=op.f('ck_workflow_step_runs_status')),
    sa.CheckConstraint('attempt >= 1', name=op.f('ck_workflow_step_runs_attempt_positive')),
    sa.ForeignKeyConstraint(['workspace_id', 'run_id'], ['workflow_runs.workspace_id', 'workflow_runs.id'], name='fk_workflow_step_runs_run_id_workflow_runs', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_workflow_step_runs_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workflow_step_runs')),
    sa.UniqueConstraint('run_id', 'node_key', 'attempt', name='uq_workflow_step_runs_attempt'),
    sa.UniqueConstraint('workspace_id', 'id', name='uq_workflow_step_runs_workspace_id_id'),
    sa.UniqueConstraint('workspace_id', 'idempotency_key', name='uq_workflow_step_runs_idempotency')
    )
    op.create_index('ix_workflow_step_runs_workspace_status', 'workflow_step_runs', ['workspace_id', 'status'], unique=False)
    op.create_table('activities',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('lead_id', sa.Uuid(), nullable=True),
    sa.Column('opportunity_id', sa.Uuid(), nullable=True),
    sa.Column('actor_user_id', sa.Uuid(), nullable=True),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('summary', sa.String(length=500), nullable=False),
    sa.Column('body', sa.Text(), nullable=True),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("kind IN ('note', 'email', 'call', 'meeting', 'stage_change', 'task', 'system')", name=op.f('ck_activities_kind')),
    sa.CheckConstraint('lead_id IS NOT NULL OR opportunity_id IS NOT NULL', name=op.f('ck_activities_has_subject')),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], name=op.f('fk_activities_actor_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id', 'lead_id'], ['leads.workspace_id', 'leads.id'], name='fk_activities_lead_id_leads', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id', 'opportunity_id'], ['opportunities.workspace_id', 'opportunities.id'], name='fk_activities_opportunity_id_opportunities', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_activities_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_activities'))
    )
    op.create_index('ix_activities_workspace_lead_time', 'activities', ['workspace_id', 'lead_id', 'occurred_at'], unique=False)
    op.create_index('ix_activities_workspace_opp_time', 'activities', ['workspace_id', 'opportunity_id', 'occurred_at'], unique=False)
    op.create_table('drafts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('lead_id', sa.Uuid(), nullable=True),
    sa.Column('conversation_id', sa.Uuid(), nullable=True),
    sa.Column('email_account_id', sa.Uuid(), nullable=True),
    sa.Column('to_address', sa.String(length=254), nullable=True),
    sa.Column('subject', sa.String(length=500), nullable=False),
    sa.Column('body_text', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('author', sa.String(length=10), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=True),
    sa.Column('approved_content_hash', sa.String(length=64), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('approved_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('facts_used', sa.JSON(), nullable=False),
    sa.Column('send_idempotency_key', sa.String(length=100), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_sample', sa.Boolean(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("author IN ('user', 'ai')", name=op.f('ck_drafts_author')),
    sa.CheckConstraint("status IN ('draft', 'pending_approval', 'approved', 'rejected', 'sent', 'discarded')", name=op.f('ck_drafts_status')),
    sa.CheckConstraint('version >= 1', name=op.f('ck_drafts_version_positive')),
    sa.ForeignKeyConstraint(['approved_by_user_id'], ['users.id'], name=op.f('fk_drafts_approved_by_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id', 'conversation_id'], ['conversations.workspace_id', 'conversations.id'], name='fk_drafts_conversation_id_conversations', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id', 'email_account_id'], ['email_accounts.workspace_id', 'email_accounts.id'], name='fk_drafts_email_account_id_email_accounts'),
    sa.ForeignKeyConstraint(['workspace_id', 'lead_id'], ['leads.workspace_id', 'leads.id'], name='fk_drafts_lead_id_leads', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_drafts_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_drafts')),
    sa.UniqueConstraint('workspace_id', 'id', name='uq_drafts_workspace_id_id'),
    sa.UniqueConstraint('workspace_id', 'send_idempotency_key', name='uq_drafts_workspace_send_key')
    )
    op.create_index('ix_drafts_workspace_lead', 'drafts', ['workspace_id', 'lead_id'], unique=False)
    op.create_index('ix_drafts_workspace_status', 'drafts', ['workspace_id', 'status'], unique=False)
    op.create_table('messages',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('email_account_id', sa.Uuid(), nullable=False),
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('provider_message_id', sa.String(length=200), nullable=False),
    sa.Column('direction', sa.String(length=10), nullable=False),
    sa.Column('delivery_state', sa.String(length=10), nullable=False),
    sa.Column('from_address', sa.String(length=254), nullable=False),
    sa.Column('to_addresses', sa.JSON(), nullable=False),
    sa.Column('subject', sa.String(length=500), nullable=True),
    sa.Column('snippet', sa.String(length=500), nullable=True),
    sa.Column('attachments', sa.JSON(), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('is_sample', sa.Boolean(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("delivery_state IN ('demo', 'queued', 'sent', 'failed', 'unknown')", name=op.f('ck_messages_delivery_state')),
    sa.CheckConstraint("direction IN ('inbound', 'outbound')", name=op.f('ck_messages_direction')),
    sa.ForeignKeyConstraint(['workspace_id', 'conversation_id'], ['conversations.workspace_id', 'conversations.id'], name='fk_messages_conversation_id_conversations', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id', 'email_account_id'], ['email_accounts.workspace_id', 'email_accounts.id'], name='fk_messages_email_account_id_email_accounts', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_messages_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_messages')),
    sa.UniqueConstraint('email_account_id', 'provider_message_id', name='uq_messages_account_provider_message'),
    sa.UniqueConstraint('workspace_id', 'id', name='uq_messages_workspace_id_id')
    )
    op.create_index('ix_messages_workspace_conversation_sent', 'messages', ['workspace_id', 'conversation_id', 'sent_at'], unique=False)
    op.create_table('tasks',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('priority', sa.String(length=10), nullable=False),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('due_timezone', sa.String(length=64), nullable=True),
    sa.Column('remind_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('assignee_user_id', sa.Uuid(), nullable=True),
    sa.Column('lead_id', sa.Uuid(), nullable=True),
    sa.Column('opportunity_id', sa.Uuid(), nullable=True),
    sa.Column('conversation_id', sa.Uuid(), nullable=True),
    sa.Column('created_by', sa.String(length=20), nullable=False),
    sa.Column('idempotency_key', sa.String(length=100), nullable=True),
    sa.Column('is_sample', sa.Boolean(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("priority IN ('low', 'normal', 'high')", name=op.f('ck_tasks_priority')),
    sa.CheckConstraint("status IN ('open', 'done', 'dismissed')", name=op.f('ck_tasks_status')),
    sa.ForeignKeyConstraint(['assignee_user_id'], ['users.id'], name=op.f('fk_tasks_assignee_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id', 'conversation_id'], ['conversations.workspace_id', 'conversations.id'], name='fk_tasks_conversation_id_conversations', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id', 'lead_id'], ['leads.workspace_id', 'leads.id'], name='fk_tasks_lead_id_leads', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id', 'opportunity_id'], ['opportunities.workspace_id', 'opportunities.id'], name='fk_tasks_opportunity_id_opportunities', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_tasks_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tasks')),
    sa.UniqueConstraint('workspace_id', 'idempotency_key', name='uq_tasks_workspace_idempotency')
    )
    op.create_index('ix_tasks_workspace_assignee', 'tasks', ['workspace_id', 'assignee_user_id'], unique=False)
    op.create_index('ix_tasks_workspace_lead', 'tasks', ['workspace_id', 'lead_id'], unique=False)
    op.create_index('ix_tasks_workspace_status_due', 'tasks', ['workspace_id', 'status', 'due_at'], unique=False)
    op.create_table('approval_requests',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=True),
    sa.Column('step_run_id', sa.Uuid(), nullable=True),
    sa.Column('draft_id', sa.Uuid(), nullable=True),
    sa.Column('kind', sa.String(length=40), nullable=False),
    sa.Column('target_type', sa.String(length=40), nullable=True),
    sa.Column('target_id', sa.String(length=64), nullable=True),
    sa.Column('payload_hash', sa.String(length=64), nullable=False),
    sa.Column('proposed_payload', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=15), nullable=False),
    sa.Column('requested_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('decided_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decision_note', sa.String(length=500), nullable=True),
    sa.Column('invalidated_reason', sa.String(length=200), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('pending', 'approved', 'rejected', 'expired', 'cancelled', 'invalidated')", name=op.f('ck_approval_requests_status')),
    sa.ForeignKeyConstraint(['decided_by_user_id'], ['users.id'], name=op.f('fk_approval_requests_decided_by_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['requested_by_user_id'], ['users.id'], name=op.f('fk_approval_requests_requested_by_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id', 'draft_id'], ['drafts.workspace_id', 'drafts.id'], name='fk_approval_requests_draft_id_drafts', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id', 'run_id'], ['workflow_runs.workspace_id', 'workflow_runs.id'], name='fk_approval_requests_run_id_workflow_runs', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id', 'step_run_id'], ['workflow_step_runs.workspace_id', 'workflow_step_runs.id'], name='fk_approval_requests_step_run_id_workflow_step_runs', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_approval_requests_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_approval_requests')),
    sa.UniqueConstraint('workspace_id', 'id', name='uq_approval_requests_workspace_id_id')
    )
    op.create_index('ix_approval_requests_workspace_status_expires', 'approval_requests', ['workspace_id', 'status', 'expires_at'], unique=False)

    # --- Hand-written follow-up steps -------------------------------------------------------------
    with op.batch_alter_table("memberships") as batch:
        batch.create_check_constraint(
            op.f("ck_memberships_role"), "role IN ('owner', 'admin', 'member')"
        )

    # Every existing workspace gets the default pipeline stages (idempotent: table is brand new).
    bind = op.get_bind()
    stages = sa.table(
        "pipeline_stages",
        sa.column("id", sa.Uuid()),
        sa.column("workspace_id", sa.Uuid()),
        sa.column("key", sa.String()),
        sa.column("name", sa.String()),
        sa.column("position", sa.Integer()),
        sa.column("is_won", sa.Boolean()),
        sa.column("is_lost", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(UTC)
    rows = [
        {
            "id": uuid.uuid4(),
            # SQLite returns ids from raw SQL as hex strings; PostgreSQL returns UUID objects.
            "workspace_id": workspace_id
            if isinstance(workspace_id, uuid.UUID)
            else uuid.UUID(str(workspace_id)),
            "key": key,
            "name": name,
            "position": position,
            "is_won": is_won,
            "is_lost": is_lost,
            "created_at": now,
            "updated_at": now,
        }
        for (workspace_id,) in bind.execute(sa.text("SELECT id FROM workspaces")).fetchall()
        for position, (key, name, is_won, is_lost) in enumerate(_DEFAULT_STAGES)
    ]
    if rows:
        op.bulk_insert(stages, rows)


def downgrade() -> None:
    with op.batch_alter_table("memberships") as batch:
        batch.drop_constraint(op.f("ck_memberships_role"), type_="check")
    op.drop_index('ix_approval_requests_workspace_status_expires', table_name='approval_requests')
    op.drop_table('approval_requests')
    op.drop_index('ix_tasks_workspace_status_due', table_name='tasks')
    op.drop_index('ix_tasks_workspace_lead', table_name='tasks')
    op.drop_index('ix_tasks_workspace_assignee', table_name='tasks')
    op.drop_table('tasks')
    op.drop_index('ix_messages_workspace_conversation_sent', table_name='messages')
    op.drop_table('messages')
    op.drop_index('ix_drafts_workspace_status', table_name='drafts')
    op.drop_index('ix_drafts_workspace_lead', table_name='drafts')
    op.drop_table('drafts')
    op.drop_index('ix_activities_workspace_opp_time', table_name='activities')
    op.drop_index('ix_activities_workspace_lead_time', table_name='activities')
    op.drop_table('activities')
    op.drop_index('ix_workflow_step_runs_workspace_status', table_name='workflow_step_runs')
    op.drop_table('workflow_step_runs')
    op.drop_table('workflow_edges')
    op.drop_index('ix_opportunities_workspace_status', table_name='opportunities')
    op.drop_index('ix_opportunities_workspace_stage', table_name='opportunities')
    op.drop_index('ix_opportunities_workspace_lead', table_name='opportunities')
    op.drop_table('opportunities')
    op.drop_index('ix_lead_tags_workspace_tag', table_name='lead_tags')
    op.drop_table('lead_tags')
    op.drop_index('ix_conversations_workspace_lead', table_name='conversations')
    op.drop_index('ix_conversations_workspace_last_message', table_name='conversations')
    op.drop_table('conversations')
    op.drop_index('ix_workflow_runs_workspace_workflow_started', table_name='workflow_runs')
    op.drop_index('ix_workflow_runs_workspace_status', table_name='workflow_runs')
    op.drop_index('ix_workflow_runs_correlation', table_name='workflow_runs')
    op.drop_table('workflow_runs')
    op.drop_index('ix_workflow_nodes_workspace_type', table_name='workflow_nodes')
    op.drop_table('workflow_nodes')
    op.drop_index('ix_leads_workspace_status', table_name='leads')
    op.drop_index('ix_leads_workspace_last_activity', table_name='leads')
    op.drop_index('ix_leads_workspace_fit', table_name='leads')
    op.drop_index('ix_leads_workspace_contact', table_name='leads')
    op.drop_index('ix_leads_workspace_company', table_name='leads')
    op.drop_table('leads')
    op.drop_table('workflow_versions')
    op.drop_index('ix_integration_connections_workspace_connector', table_name='integration_connections')
    op.drop_table('integration_connections')
    op.drop_table('email_accounts')
    op.drop_index('ix_contacts_workspace_name', table_name='contacts')
    op.drop_index('ix_contacts_workspace_company', table_name='contacts')
    op.drop_table('contacts')
    op.drop_index('ix_workflows_workspace_status', table_name='workflows')
    op.drop_table('workflows')
    op.drop_index('ix_usage_records_workspace_time', table_name='usage_records')
    op.drop_index('ix_usage_records_workspace_kind_time', table_name='usage_records')
    op.drop_table('usage_records')
    op.drop_table('tags')
    op.drop_table('suppression_entries')
    op.drop_table('pipeline_stages')
    op.drop_index('ix_notifications_workspace_user_read', table_name='notifications')
    op.drop_table('notifications')
    op.drop_index('ix_knowledge_items_workspace_status', table_name='knowledge_items')
    op.drop_table('knowledge_items')
    op.drop_table('credential_secrets')
    op.drop_index('ix_companies_workspace_name', table_name='companies')
    op.drop_table('companies')
