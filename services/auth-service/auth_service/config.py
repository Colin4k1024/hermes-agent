"""
Auth Service — Pydantic Settings
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Service
    SERVICE_NAME: str = "auth-service"
    SERVICE_PORT: int = 8001

    # JWT
    JWT_SECRET_KEY: str = "dev-secret-change-in-prod"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # OIDC (Keycloak)
    OIDC_ISSUER: str = "http://localhost:8880/realms/hermes"
    OIDC_CLIENT_ID: str = "hermes-auth"
    OIDC_CLIENT_SECRET: str = "hermes-secret"
    OIDC_REDIRECT_URI: str = "http://localhost:8001/auth/oidc/callback"
    OIDC_MOCK_ENABLED: bool = True  # Dev fallback only
    OIDC_MOCK_USER_EMAIL: str = "dev@hermes.local"
    OIDC_MOCK_USER_PASSWORD: str = "devpassword"
    OIDC_MOCK_USER_ID: str = "dev-user-001"
    OIDC_MOCK_USER_ROLE: str = "admin"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://hermes:hermes@localhost:5432/hermes_auth"
    DB_POOL_SIZE: int = 10

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_TOKEN_PREFIX: str = "auth:token:"
    REDIS_REVOKED_PREFIX: str = "auth:revoked:"

    # Admin
    ADMIN_API_KEY: Optional[str] = None  # For admin endpoints

    # Internal API key for inter-service communication
    INTERNAL_API_KEY: str = "dev-internal-key-change-in-prod"

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]


settings = Settings()
