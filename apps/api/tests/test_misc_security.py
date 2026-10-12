from __future__ import annotations

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from cryptography.fernet import Fernet

from app.audit import ALLOWED_DETAIL_KEYS, record
from app.config import ConfigError, load_settings
from app.db.base import Base
from app.db.session import get_engine
from app.schemas.text import clean_public_url
from app.security.passwords import WeakPasswordError, validate_password


def test_models_and_migrations_have_no_drift() -> None:
    with get_engine().connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_audit_record_drops_non_allow_listed_details() -> None:
    class FakeDb:
        def __init__(self) -> None:
            self.added: list[object] = []

        def add(self, obj: object) -> None:
            self.added.append(obj)

    db = FakeDb()
    record(
        db,
        "x.test",
        details={"reason": "ok", "password": "hunter2", "token": "abc", "step": "role"},
    )  # type: ignore[arg-type]
    details = db.added[0].details  # type: ignore[attr-defined]
    assert details == {"reason": "ok", "step": "role"}
    assert not {"password", "token"} & ALLOWED_DETAIL_KEYS


@pytest.mark.parametrize(
    "bad", ["short", "a" * 129, "password1234", "aaaaaaaaaaaaaa", "contains-bobsmith-inside"]
)
def test_weak_passwords(bad: str) -> None:
    with pytest.raises(WeakPasswordError):
        validate_password(bad, email="bobsmith@example.com")


def test_passphrases_are_accepted() -> None:
    validate_password("correct horse battery staple", email="a@example.com")


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://example.com", True),
        ("http://example.com:8080/x?y=1#z", True),
        ("https://8.8.8.8/", True),
        ("https://sub.example.co.uk/path", True),
        ("http://192.168.1.1/", False),
        ("http://100.64.0.1/", False),
        ("https://[fe80::1]/", False),
        ("https://example.com:99999/", False),
        ("//example.com", False),
        ("", False),
    ],
)
def test_public_url_validation(url: str, ok: bool) -> None:
    if ok:
        assert clean_public_url(url)
    else:
        with pytest.raises(ValueError):
            clean_public_url(url)


@pytest.mark.parametrize(
    ("env", "needle"),
    [
        ({"COOKIE_SECURE": "false"}, "COOKIE_SECURE"),
        ({"MAIL_BACKEND": "console"}, "MAIL_BACKEND"),
        ({"RATE_LIMIT_BACKEND": "memory"}, "RATE_LIMIT_BACKEND"),
        ({"CREDENTIAL_ENCRYPTION_KEYS": ""}, "CREDENTIAL_ENCRYPTION_KEYS"),
    ],
)
def test_production_refuses_insecure_auth_settings(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], needle: str
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_SECRET_KEY", "x" * 48)
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEYS", f"v1:{Fernet.generate_key().decode()}")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(ConfigError, match=needle):
        load_settings()


def test_production_defaults_are_secure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_SECRET_KEY", "x" * 48)
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEYS", f"v1:{Fernet.generate_key().decode()}")
    s = load_settings()
    assert (
        s.secure_cookies
        and s.effective_rate_limit_backend == "redis"
        and s.effective_mail_backend == "disabled"
    )
