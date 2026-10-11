from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import inspect, select

from app.cli import SEED_MARKER_KEY, main
from app.config import get_settings
from app.db.models import AppMetadata
from app.db.session import get_engine, get_sessionmaker


def test_migration_creates_expected_table() -> None:
    assert "app_metadata" in inspect(get_engine()).get_table_names()


def test_seed_is_idempotent(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["seed"]) == 0
    assert main(["seed"]) == 0
    assert "already applied" in capsys.readouterr().out
    with get_sessionmaker()() as session:
        rows = session.scalars(select(AppMetadata).where(AppMetadata.key == SEED_MARKER_KEY)).all()
    assert len(rows) == 1


def test_seed_refuses_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "app_env", "production")
    assert main(["seed"]) == 1


def test_export_openapi(tmp_path: Path) -> None:
    target = tmp_path / "openapi.json"
    assert main(["export-openapi", str(target)]) == 0
    assert "/health" in json.loads(target.read_text())["paths"]
