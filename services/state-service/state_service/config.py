"""Configuration for Hermes State Service."""

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    redis_url: str = "redis://localhost:6379/0"

    internal_api_key: str = "dev-state-key-change-in-prod"
    default_tenant_id: str = "default"


settings = Settings()
