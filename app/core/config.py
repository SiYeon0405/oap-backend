from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"


class DatabaseConfigurationError(ValueError):
    pass


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


@lru_cache
def get_settings() -> Settings:
    return Settings()
