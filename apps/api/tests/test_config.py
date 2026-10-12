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


# ---- AI provider configuration (MVP Prompt 8) ----------------------------------------------------


def _prod(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_SECRET_KEY", "x" * 48)
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEYS", "v1:" + "A" * 43 + "=")
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "redis")
    monkeypatch.setenv("MAIL_BACKEND", "disabled")
    for k, v in env.items():
        monkeypatch.setenv(k, v)


def test_ai_provider_defaults_to_mock_in_development_and_disabled_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    assert load_settings().effective_ai_provider == "mock"
    _prod(monkeypatch)
    assert load_settings().effective_ai_provider == "disabled"


def test_production_refuses_the_demo_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    _prod(monkeypatch, AI_PROVIDER="mock")
    with pytest.raises(ConfigError, match="AI_PROVIDER=mock"):
        load_settings()


def test_gateway_needs_url_key_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROVIDER", "gateway")
    with pytest.raises(ConfigError) as exc:
        load_settings()
    assert all(name in str(exc.value) for name in ("AI_BASE_URL", "AI_API_KEY", "AI_MODEL"))
    monkeypatch.setenv("AI_BASE_URL", "https://gateway.example/v1")
    monkeypatch.setenv("AI_API_KEY", "k" * 20)
    monkeypatch.setenv("AI_MODEL", "some-model")
    settings = load_settings()
    assert settings.effective_ai_provider == "gateway"
    assert "k" * 20 not in repr(settings) and "k" * 20 not in str(settings.ai_api_key)


def test_gateway_url_must_not_embed_credentials_and_must_be_https_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    good = {"AI_PROVIDER": "gateway", "AI_API_KEY": "k" * 20, "AI_MODEL": "m"}
    for k, v in good.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("AI_BASE_URL", "https://user:pass@gateway.example/v1")
    with pytest.raises(ConfigError, match="credentials"):
        load_settings()
    _prod(monkeypatch, AI_BASE_URL="http://gateway.example/v1")
    with pytest.raises(ConfigError, match="https"):
        load_settings()
    monkeypatch.setenv("AI_BASE_URL", "https://gateway.example/v1")
    assert load_settings().effective_ai_provider == "gateway"


def test_ai_limits_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in [
        ("AI_MAX_ATTEMPTS", "9"),
        ("AI_TIMEOUT_SECONDS", "0"),
        ("AI_RATE_LIMIT_PER_MINUTE", "0"),
    ]:
        monkeypatch.setenv(name, value)
        with pytest.raises(ConfigError, match=name):
            load_settings()
        monkeypatch.delenv(name)
