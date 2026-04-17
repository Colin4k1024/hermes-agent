"""Configuration for Skills Registry Service."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="SKILLS_REGISTRY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Service
    host: str = "0.0.0.0"
    port: int = 8004
    debug: bool = False

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "hermes"
    postgres_password: str = "hermes"
    postgres_db: str = "hermes_skills"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # NAS / Local file storage
    # In dev: local filesystem; In prod: NFS mount path
    skills_storage_path: str = "/nas/org-skills"
    skills_local_dev_path: str = "./dev-skills"

    # Use local dev path when debug=true, NAS path otherwise
    @property
    def skills_root(self) -> str:
        return self.skills_local_dev_path if self.debug else self.skills_storage_path

    # Skills hot-update
    skill_update_channel: str = "channel:skill-update"

    # Auth (shared with Auth Service)
    jwt_secret: str = "dev-secret-change-in-prod"
    jwt_algorithm: str = "HS256"

    # Admin API auth
    admin_api_key: str = "dev-admin-key-change-in-prod"

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

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


settings = Settings()
