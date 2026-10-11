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
        return self

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
