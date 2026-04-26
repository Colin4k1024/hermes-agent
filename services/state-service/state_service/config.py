"""Configuration for Hermes State Service."""

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


LOCAL_DEV_INTERNAL_API_KEY = "dev-state-key-change-in-prod"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="STATE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 8006
    debug: bool = False

    database_url: str = "postgresql+asyncpg://hermes:hermes@localhost:5432/hermes_platform"
    db_pool_size: int = 10
    auto_create_schema: bool = False
    expected_migration_revision: str = "20260425_0001"

    redis_url: str = "redis://localhost:6379/0"
    object_storage_endpoint: str | None = None
    object_storage_bucket: str = "hermes-state-cache"

    internal_api_key: str | None = None
    default_tenant_id: str = "default"

    @model_validator(mode="after")
    def require_production_internal_api_key(self) -> "Settings":
        """Allow the well-known token only when debug/local mode is explicit."""
        if self.debug:
            if not self.internal_api_key:
                self.internal_api_key = LOCAL_DEV_INTERNAL_API_KEY
            return self

        if not self.internal_api_key:
            raise ValueError("STATE_INTERNAL_API_KEY must be set unless STATE_DEBUG=true")
        if self.internal_api_key == LOCAL_DEV_INTERNAL_API_KEY:
            raise ValueError("STATE_INTERNAL_API_KEY must not use the local development token")
        return self


settings = Settings()
