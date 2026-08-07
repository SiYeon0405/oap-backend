from functools import lru_cache
import logging
import os
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"
logger = logging.getLogger(__name__)
APP_ENV_VALUES = {"local", "test", "production"}
DEFAULT_CORS_ALLOWED_ORIGINS = (
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:5173",
)


class DatabaseConfigurationError(ValueError):
    pass


def get_app_env() -> str:
    value = os.getenv("APP_ENV")
    if value is None:
        value = dotenv_values(ENV_FILE).get("APP_ENV", "production")
    if value not in APP_ENV_VALUES:
        raise ValueError("APP_ENV must be local, test, or production")
    return value


def get_cors_allowed_origins() -> list[str]:
    configured = os.getenv("CORS_ALLOWED_ORIGINS")
    if configured is None:
        configured = dotenv_values(ENV_FILE).get("CORS_ALLOWED_ORIGINS")
    values = (
        configured.split(",")
        if configured is not None
        else DEFAULT_CORS_ALLOWED_ORIGINS
    )
    origins = list(dict.fromkeys(value.strip().rstrip("/") for value in values if value.strip()))
    if "*" in origins:
        raise ValueError("CORS_ALLOWED_ORIGINS must not contain a wildcard")
    return origins


class Settings(BaseSettings):
    app_env: Literal["local", "test", "production"] = "production"
    database_url: str | None = None
    test_database_url: str | None = None
    openai_api_key: str | None = None

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_database_configuration(self):
        if self.app_env == "test" and self.test_database_url:
            self.database_url = self.test_database_url

        validate_database_url(self.app_env, self.database_url)
        if self.app_env == "local":
            env_file_key = dotenv_values(ENV_FILE).get("OPENAI_API_KEY")
            os_key = os.getenv("OPENAI_API_KEY")
            if os_key and env_file_key and os_key.strip() != env_file_key.strip():
                logger.warning(
                    "Local OPENAI_API_KEY conflict detected; using project .env"
                )
            self.openai_api_key = env_file_key
        elif self.app_env == "production":
            self.openai_api_key = os.getenv("OPENAI_API_KEY")
        return self


def validate_database_url(app_env: str, database_url: str | None) -> None:
    if not database_url:
        raise DatabaseConfigurationError(
            "DATABASE_URL is required; no database fallback is configured"
        )

    from sqlalchemy.engine import make_url

    try:
        parsed = make_url(database_url)
    except Exception as exc:
        raise DatabaseConfigurationError("DATABASE_URL is invalid") from exc

    if app_env != "production":
        return

    driver = parsed.drivername.lower()
    host = (parsed.host or "").lower().rstrip(".")
    if not driver.startswith("postgresql"):
        raise DatabaseConfigurationError(
            "Production DATABASE_URL must use PostgreSQL"
        )
    if not host or host in {"localhost", "127.0.0.1", "::1"}:
        raise DatabaseConfigurationError(
            "Production DATABASE_URL must target Supabase PostgreSQL"
        )
    if not (
        host.endswith(".supabase.co")
        or host.endswith(".pooler.supabase.com")
    ):
        raise DatabaseConfigurationError(
            "Production DATABASE_URL must target a Supabase host"
        )


def get_database_url(settings: Settings | None = None) -> str:
    configured_url = (settings or get_settings()).database_url
    if not configured_url:
        raise DatabaseConfigurationError("DATABASE_URL is required")
    return configured_url


def get_openai_api_key(settings: Settings | None = None) -> str:
    current_settings = settings or get_settings()
    selected_key = current_settings.openai_api_key

    if not selected_key or not selected_key.strip():
        raise ValueError(
            f"OPENAI_API_KEY is not configured for {current_settings.app_env}"
        )
    return selected_key.strip()


@lru_cache
def get_settings() -> Settings:
    return Settings()
