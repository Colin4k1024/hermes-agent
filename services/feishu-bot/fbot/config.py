"""Application configuration — all values sourced from environment variables."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Feishu Bot Service configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="forbid",
    )

    # ── Feishu ────────────────────────────────────────────────────────────────
    FEISHU_APP_ID: str = ""
    FEISHU_APP_SECRET: str = ""
    FEISHU_BOT_NAME: str = "Hermes"

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""

    # ── Internal services ─────────────────────────────────────────────────────
    AUTH_SERVICE_URL: str = "http://localhost:8001"
    ROUTER_SERVICE_URL: str = "http://localhost:8002"

    # ── Feishu Bot identity ──────────────────────────────────────────────────
    # Unique instance ID — used as Redis stream suffix so each replica has its own response channel.
    # In K8s, set to the Pod name (downward API: metadata.name).
    FBOT_INSTANCE_ID: str = "fbp-001"

    # ── Server ────────────────────────────────────────────────────────────────
    HOST: str = "0.0.0.0"
    PORT: int = 8005
    LOG_LEVEL: str = "INFO"

    # ── Security / Signature verification ───────────────────────────────────
    # Maximum allowed offset between request timestamp and server time (seconds).
    MAX_TIMESTAMP_OFFSET: int = 300  # 5 minutes

    # ── Redis key TTLs ───────────────────────────────────────────────────────
    DEDUP_TTL_SECONDS: int = 300           # event_id dedup window (covers 5x Feishu retry)
    RESPONSE_STREAM_TTL_SECONDS: int = 86400  # 24 hours — response stream TTL
    NONCE_TTL_SECONDS: int = 300            # binding nonce TTL

    # ── Redis stream names ──────────────────────────────────────────────────
    FEISHU_REQUESTS_STREAM: str = "feishu:requests"
    FEISHU_RESPONSES_PREFIX: str = "feishu:responses"

    # ── Response wait ────────────────────────────────────────────────────────
    # How long the FBot waits for a response from the Router (seconds).
    XREAD_TIMEOUT_SECONDS: int = 55   # slightly below 60 s to avoid edge cases

    # ── Auth internal API ────────────────────────────────────────────────────
    AUTH_BY_FEISHU_ID_PATH: str = "/auth/user/by-feishu-id"
    AUTH_INTERNAL_TIMEOUT_SECONDS: float = 5.0

    @property
    def redis_url(self) -> str:
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def feishu_responses_stream(self) -> str:
        return f"{self.FEISHU_RESPONSES_PREFIX}:{self.FBOT_INSTANCE_ID}"

    @property
    def base_dir(self) -> Path:
        return Path(__file__).parent.parent.parent.parent


@lru_cache
def get_settings() -> Settings:
    return Settings()
