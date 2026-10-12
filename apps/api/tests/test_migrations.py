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
def at_revision(revision: str) -> Iterator[None]:
    """Roll the shared test database back to ``revision`` and always restore it to head afterwards."""
    url = get_settings().database_url
    cfg = alembic_config(url)
    get_engine().dispose()
    command.downgrade(cfg, revision)
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
    with at_revision("0002"):
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
    with at_revision("0002"):
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


# ----------------------------------------------------------------------------------------------------
# Revision 0004: profile fields, knowledge lifecycle and history
# ----------------------------------------------------------------------------------------------------
def test_0004_migrates_existing_knowledge_and_profiles_safely_and_rolls_back() -> None:
    import uuid
    from datetime import UTC, datetime

    import sqlalchemy as sa

    cfg = alembic_config(get_settings().database_url)
    now = datetime.now(UTC)
    ws_id, approved_id, disabled_id, profile_id = (uuid.uuid4() for _ in range(4))

    # Table shapes as they were at revision 0003 (no is_enabled / version history / new profile columns).
    knowledge = sa.table(
        "knowledge_items",
        *(
            sa.column(n, t)
            for n, t in [
                ("id", sa.Uuid()),
                ("workspace_id", sa.Uuid()),
                ("kind", sa.String()),
                ("title", sa.String()),
                ("content", sa.Text()),
                ("source_type", sa.String()),
                ("status", sa.String()),
                ("version", sa.Integer()),
                ("created_at", sa.DateTime(timezone=True)),
                ("updated_at", sa.DateTime(timezone=True)),
            ]
        ),
    )
    profiles = sa.table(
        "freelancer_profiles",
        *(
            sa.column(n, t)
            for n, t in [
                ("id", sa.Uuid()),
                ("workspace_id", sa.Uuid()),
                ("services", sa.JSON()),
                ("skills", sa.JSON()),
                ("industries", sa.JSON()),
                ("portfolio_urls", sa.JSON()),
                ("created_at", sa.DateTime(timezone=True)),
                ("updated_at", sa.DateTime(timezone=True)),
            ]
        ),
    )
    with at_revision("0003"):
        with get_sessionmaker()() as db:
            db.add(Workspace(id=ws_id, name="legacy knowledge"))
            db.flush()
            common = {
                "workspace_id": ws_id,
                "kind": "fact",
                "source_type": "manual",
                "created_at": now,
                "updated_at": now,
            }
            db.execute(
                sa.insert(knowledge),
                [
                    {
                        **common,
                        "id": approved_id,
                        "title": "Kept",
                        "content": "approved fact",
                        "status": "approved",
                        "version": 3,
                    },
                    {
                        **common,
                        "id": disabled_id,
                        "title": "Old",
                        "content": "was disabled",
                        "status": "disabled",
                        "version": 1,
                    },
                ],
            )
            db.execute(
                sa.insert(profiles),
                [
                    {
                        "id": profile_id,
                        "workspace_id": ws_id,
                        "services": ["A"],
                        "skills": [],
                        "industries": [],
                        "portfolio_urls": [],
                        "created_at": now,
                        "updated_at": now,
                    }
                ],
            )
            db.commit()

        command.upgrade(cfg, "head")
        get_engine().dispose()
        get_sessionmaker.cache_clear()
        with get_sessionmaker()() as db:
            from app.db.models import FreelancerProfile
            from app.db.models_crm import KnowledgeItem, KnowledgeItemVersion

            kept, old = db.get(KnowledgeItem, approved_id), db.get(KnowledgeItem, disabled_id)
            assert (kept.status, kept.is_enabled, kept.version) == ("approved", True, 3)  # type: ignore[union-attr]
            # The legacy "disabled" status becomes draft + switched off: unusable, and recoverable by the user.
            assert (old.status, old.is_enabled) == ("draft", False)  # type: ignore[union-attr]
            history = {
                (v.item_id, v.version)
                for v in db.scalars(
                    select(KnowledgeItemVersion).where(KnowledgeItemVersion.workspace_id == ws_id)
                )
            }
            assert history == {(approved_id, 3), (disabled_id, 1)}
            profile = db.get(FreelancerProfile, profile_id)
            assert (
                profile.version == 1
                and profile.excluded_customers == []
                and profile.differentiators == []
            )  # type: ignore[union-attr]
            assert profile.pricing_guidance is None and profile.services == ["A"]  # type: ignore[union-attr]
            # The new CHECK is active: "disabled" is no longer a valid status.
            from sqlalchemy.exc import IntegrityError

            kept.status = "disabled"  # type: ignore[union-attr]
            with pytest.raises(IntegrityError):
                db.flush()
            db.rollback()

        command.downgrade(cfg, "0003")  # rollback restores the old status vocabulary
        get_engine().dispose()
        get_sessionmaker.cache_clear()
        with get_engine().connect() as conn:
            rows = dict(
                conn.execute(
                    sa.text(
                        "SELECT title, status FROM knowledge_items WHERE title IN ('Kept', 'Old')"
                    )
                ).all()
            )
            assert rows == {"Kept": "approved", "Old": "disabled"}
        command.upgrade(cfg, "head")  # and forward again
        get_engine().dispose()
        get_sessionmaker.cache_clear()
        with get_sessionmaker()() as db:
            db.delete(db.get(Workspace, ws_id))
            db.commit()
