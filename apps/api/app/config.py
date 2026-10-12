"""Application settings with startup validation.

All configuration comes from environment variables (see ``.env.example``).
Invalid configuration fails fast with an actionable message instead of
surfacing later as an obscure runtime error.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_SECRETS = {"", "change-me", "changeme", "secret", "replace-me"}


class ConfigError(RuntimeError):
    """Raised when environment configuration is missing or invalid."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"), env_file_encoding="utf-8", extra="ignore", env_prefix=""
    )

    app_env: Literal["development", "test", "production"] = Field(
        default="development", alias="APP_ENV"
    )
    database_url: str = Field(alias="DATABASE_URL")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    cors_allowed_origins: str = Field(default="http://localhost:3000", alias="CORS_ALLOWED_ORIGINS")
    app_secret_key: str = Field(default="", alias="APP_SECRET_KEY")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # --- Authentication / sessions ---
    # Public URL of the web app (used in password-reset links).
    web_base_url: str = Field(default="http://localhost:3000", alias="WEB_BASE_URL")
    # None = Secure cookies in production only (browsers reject Secure cookies on plain http).
    cookie_secure: bool | None = Field(default=None, alias="COOKIE_SECURE")
    session_idle_timeout_minutes: int = Field(
        default=60 * 24 * 7, ge=5, alias="SESSION_IDLE_TIMEOUT_MINUTES"
    )
    session_absolute_timeout_days: int = Field(
        default=30, ge=1, alias="SESSION_ABSOLUTE_TIMEOUT_DAYS"
    )
    password_reset_ttl_minutes: int = Field(
        default=60, ge=5, le=1440, alias="PASSWORD_RESET_TTL_MINUTES"
    )
    # Number of trusted reverse proxies in front of the API (0 = use the direct peer address).
    trusted_proxy_count: int = Field(default=0, ge=0, le=5, alias="TRUSTED_PROXY_COUNT")
    # None = redis in production, in-memory otherwise.
    rate_limit_backend: Literal["memory", "redis"] | None = Field(
        default=None, alias="RATE_LIMIT_BACKEND"
    )
    # "console" prints reset links (development only). "disabled" turns password reset off.
    mail_backend: Literal["console", "disabled"] | None = Field(default=None, alias="MAIL_BACKEND")

    @field_validator("database_url")
    @classmethod
    def _check_database_url(cls, value: str) -> str:
        if not value.startswith(("postgresql://", "postgresql+psycopg://", "sqlite://")):
            raise ValueError(
                "must start with postgresql+psycopg:// (or postgresql://). "
                "Example: postgresql+psycopg://freelancer:freelancer@localhost:5432/freelancer_os"
            )
        # Normalise to the psycopg 3 driver for PostgreSQL.
        if value.startswith("postgresql://"):
            value = value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    @field_validator("redis_url")
    @classmethod
    def _check_redis_url(cls, value: str) -> str:
        if not value.startswith(("redis://", "rediss://")):
            raise ValueError("must start with redis:// or rediss://")
        return value

    @model_validator(mode="after")
    def _check_production_secrets(self) -> Settings:
        if self.app_env == "production":
            if self.app_secret_key in _INSECURE_SECRETS or len(self.app_secret_key) < 32:
                raise ValueError(
                    "APP_SECRET_KEY must be set to a random value of at least 32 characters "
                    'in production (generate one with: python -c "import secrets; '
                    'print(secrets.token_urlsafe(48))")'
                )
            if "*" in self.cors_origins:
                raise ValueError("CORS_ALLOWED_ORIGINS must not contain '*' in production")
            if self.cookie_secure is False:
                raise ValueError("COOKIE_SECURE must not be false in production")
            if self.effective_mail_backend == "console":
                raise ValueError("MAIL_BACKEND=console is for development only")
            if self.effective_rate_limit_backend == "memory":
                raise ValueError(
                    "RATE_LIMIT_BACKEND=memory is not allowed in production (use redis)"
                )
        return self

    @property
    def secure_cookies(self) -> bool:
        return self.app_env == "production" if self.cookie_secure is None else self.cookie_secure

    @property
    def effective_rate_limit_backend(self) -> str:
        return self.rate_limit_backend or ("redis" if self.app_env == "production" else "memory")

    @property
    def effective_mail_backend(self) -> str:
        return self.mail_backend or ("disabled" if self.app_env == "production" else "console")

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]


def _format_validation_error(exc: ValidationError) -> str:
    lines = ["Invalid configuration. Fix the following environment variables (see .env.example):"]
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "settings"
        lines.append(f"  - {loc}: {err['msg']}")
    return "\n".join(lines)


def load_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(exc)) from exc


@lru_cache
def get_settings() -> Settings:
    return load_settings()
