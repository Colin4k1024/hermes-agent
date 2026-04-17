"""Pydantic settings — all configuration via environment variables."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QUOTA_", env_file=".env", extra="ignore")

    # Service
    host: str = "0.0.0.0"
    port: int = 8003
    debug: bool = False

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "hermes"
    postgres_password: str = "hermes"
    postgres_db: str = "hermes_quota"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0

    # Admin auth
    admin_api_key: str = "dev-admin-key-change-in-prod"

    # Internal API key for calling other services (e.g., auth-service)
    internal_api_key: str = "dev-internal-key-change-in-prod"

    # Auth Service (for role lookups)
    auth_service_url: str = "http://localhost:8001"

    # Default quotas per role (tokens/day)
    default_quota_user: int = 100_000
    default_quota_power_user: int = 500_000
    default_quota_admin: int = -1  # -1 means unlimited

    # Redis key TTL for daily counters (seconds = 25 hours to cover TZ edge cases)
    daily_counter_ttl: int = 90_000

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sync_database_url(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
