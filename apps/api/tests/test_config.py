from __future__ import annotations

import pytest

from app.config import ConfigError, Settings, load_settings


def test_missing_database_url_gives_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL")
    monkeypatch.chdir("/")  # avoid picking up a local .env
    with pytest.raises(ConfigError) as exc:
        load_settings()
    assert "DATABASE_URL" in str(exc.value)
    assert ".env.example" in str(exc.value)


def test_invalid_database_scheme_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "mysql://x")
    with pytest.raises(ConfigError, match="postgresql"):
        load_settings()


def test_postgres_url_is_normalised_to_psycopg3(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    assert load_settings().database_url.startswith("postgresql+psycopg://")


def test_production_requires_strong_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_SECRET_KEY", "change-me")
    with pytest.raises(ConfigError, match="APP_SECRET_KEY"):
        load_settings()


def test_production_rejects_wildcard_cors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_SECRET_KEY", "x" * 48)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")
    with pytest.raises(ConfigError, match="CORS"):
        load_settings()


def test_cors_origins_are_split() -> None:
    s = Settings(DATABASE_URL="sqlite://", CORS_ALLOWED_ORIGINS="http://a.test, http://b.test")  # type: ignore[call-arg]
    assert s.cors_origins == ["http://a.test", "http://b.test"]
