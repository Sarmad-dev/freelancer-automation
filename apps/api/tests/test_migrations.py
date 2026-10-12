"""Migration behaviour on the real database: backfill of existing data and the documented rollback."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session as DbSession

from alembic import command
from app.config import get_settings
from app.db.models import Membership, User, Workspace
from app.db.models_crm import PipelineStage
from app.db.session import get_engine, get_sessionmaker
from tests.conftest import alembic_config

NEW_TABLES = {
    "companies",
    "contacts",
    "leads",
    "tags",
    "lead_tags",
    "activities",
    "tasks",
    "opportunities",
    "pipeline_stages",
    "knowledge_items",
    "email_accounts",
    "conversations",
    "messages",
    "drafts",
    "suppression_entries",
    "integration_connections",
    "credential_secrets",
    "workflows",
    "workflow_versions",
    "workflow_nodes",
    "workflow_edges",
    "workflow_runs",
    "workflow_step_runs",
    "approval_requests",
    "usage_records",
    "notifications",
}


@contextlib.contextmanager
def at_revision_0002() -> Iterator[None]:
    """Roll the shared test database back to 0002 and always restore it to head afterwards."""
    url = get_settings().database_url
    cfg = alembic_config(url)
    get_engine().dispose()
    command.downgrade(cfg, "0002")
    try:
        yield
    finally:
        command.upgrade(cfg, "head")
        get_engine().dispose()
        get_sessionmaker.cache_clear()


def _tables() -> set[str]:
    return set(inspect(get_engine()).get_table_names())


def test_upgrade_backfills_default_stages_for_existing_workspaces() -> None:
    cfg = alembic_config(get_settings().database_url)
    with at_revision_0002():
        assert not (NEW_TABLES & _tables())  # genuinely the old schema
        with get_sessionmaker()() as db:
            user = User(
                email="old@legacy.example",
                email_normalized="old@legacy.example",
                password_hash="x",
                display_name="Old",
            )
            ws = Workspace(name="Created before the domain model")
            db.add_all([user, ws])
            db.flush()
            db.add(Membership(workspace_id=ws.id, user_id=user.id, role="owner"))
            db.commit()
            ws_id = ws.id
        command.upgrade(cfg, "head")
        get_engine().dispose()
        get_sessionmaker.cache_clear()
        with get_sessionmaker()() as db:
            stages = db.scalars(
                select(PipelineStage)
                .where(PipelineStage.workspace_id == ws_id)
                .order_by(PipelineStage.position)
            ).all()
            assert [s.key for s in stages] == [
                "new",
                "contacted",
                "replied",
                "qualified",
                "meeting",
                "proposal",
                "won",
                "lost",
            ]
            assert [s.position for s in stages] == list(range(8))
            assert [(s.key, s.is_won, s.is_lost) for s in stages if s.is_won or s.is_lost] == [
                ("won", True, False),
                ("lost", False, True),
            ]
            _cleanup(db, ws_id)


def _cleanup(db: DbSession, ws_id: object) -> None:
    db.delete(db.get(Workspace, ws_id))
    user = db.scalar(select(User).where(User.email_normalized == "old@legacy.example"))
    if user is not None:
        db.delete(user)
    db.commit()


def test_membership_role_check_is_added_by_the_migration() -> None:
    from sqlalchemy.exc import IntegrityError

    with get_sessionmaker()() as db:
        user = User(
            email="role@legacy.example",
            email_normalized="role@legacy.example",
            password_hash="x",
            display_name="R",
        )
        ws = Workspace(name="role check")
        db.add_all([user, ws])
        db.flush()
        db.add(Membership(workspace_id=ws.id, user_id=user.id, role="god"))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_documented_rollback_drops_exactly_the_domain_tables_and_is_repeatable() -> None:
    cfg = alembic_config(get_settings().database_url)
    assert _tables() >= NEW_TABLES
    with at_revision_0002():
        remaining = _tables()
        assert not (NEW_TABLES & remaining)
        # Identity/auth tables from earlier revisions are untouched by the rollback.
        assert {
            "users",
            "workspaces",
            "memberships",
            "sessions",
            "audit_events",
            "freelancer_profiles",
        } <= remaining
        command.upgrade(cfg, "head")  # forward again...
        assert _tables() >= NEW_TABLES
        command.downgrade(cfg, "0002")  # ...and back: repeatable, no leftovers
        assert not (NEW_TABLES & _tables())
    assert _tables() >= NEW_TABLES
