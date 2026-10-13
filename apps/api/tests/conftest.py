from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

# Configure the environment before the app modules are imported.
os.environ.setdefault("APP_ENV", "test")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite:///./test.sqlite3")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

import uuid  # noqa: E402

from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session as DbSession  # noqa: E402

from alembic import command  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db.session import get_engine, get_sessionmaker  # noqa: E402
from app.mailer import InMemoryMailer  # noqa: E402
from app.main import create_app  # noqa: E402

API_ROOT = Path(__file__).resolve().parents[1]


def alembic_config(url: str) -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture(scope="session", autouse=True)
def migrated_db() -> Iterator[None]:
    url = get_settings().database_url
    cfg = alembic_config(url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield
    get_engine().dispose()
    get_sessionmaker.cache_clear()
    if url.startswith("sqlite"):
        (API_ROOT / "test.sqlite3").unlink(missing_ok=True)


@pytest.fixture
def mailer() -> InMemoryMailer:
    return InMemoryMailer()


@pytest.fixture
def client(mailer: InMemoryMailer) -> Iterator[TestClient]:
    """Fresh app per test (own rate limiter) acting like the web proxy: same-origin + CSRF header."""
    app = create_app()
    app.state.mailer = mailer
    with TestClient(
        app,
        headers={"Origin": "http://localhost:3000"},
        base_url="http://localhost:3000",
    ) as c:
        yield c


@pytest.fixture
def db() -> Iterator[DbSession]:
    with get_sessionmaker()() as session:
        yield session


PASSWORD = "correct horse battery"


def make_user(client: TestClient, *, name: str = "Ada Lovelace", password: str = PASSWORD) -> dict:  # type: ignore[type-arg]
    """Sign up a fresh user through the API; the client keeps the session cookie."""
    email = f"user-{uuid.uuid4().hex[:10]}@example.com"
    res = client.post(
        "/api/v1/auth/sign-up", json={"email": email, "password": password, "display_name": name}
    )
    assert res.status_code == 201, res.text
    body = res.json()
    return {
        "email": email,
        "password": password,
        "me": body,
        "workspace_id": body["workspaces"][0]["id"],
    }


def reset_demo(db: DbSession) -> None:
    """Remove the seeded demo account/workspace so a test can seed from scratch (tests share one database)."""
    from sqlalchemy import select

    from app.db.models import Membership, User, Workspace
    from app.seed import DEMO_EMAIL

    user = db.scalar(select(User).where(User.email_normalized == DEMO_EMAIL))
    if user is None:
        return
    for ws_id in db.scalars(
        select(Membership.workspace_id).where(Membership.user_id == user.id)
    ).all():
        db.delete(db.get(Workspace, ws_id))
    db.delete(user)
    db.commit()


def second_client(client: TestClient) -> TestClient:
    """A second browser (own cookie jar) against the same app."""
    return TestClient(client.app, headers=dict(client.headers), base_url="http://localhost:3000")


def add_member(db: DbSession, workspace_id: str, user_id: str, role: str = "member") -> None:
    """Grant an existing user a non-owner role in a workspace (teams are post-MVP, but roles are enforced)."""
    from app.db.models import Membership

    db.add(Membership(workspace_id=uuid.UUID(workspace_id), user_id=uuid.UUID(user_id), role=role))
    db.commit()
