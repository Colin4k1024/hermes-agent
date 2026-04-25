"""Configuration for Agent Router Service."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="ROUTER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Service
    host: str = "0.0.0.0"
    port: int = 8002
    debug: bool = False

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""

    # Route TTL (seconds) — matches 30-minute idle timeout
    route_ttl: int = 1800
    # Stateless runtime mode routes by session/request context instead of
    # treating the pod as a long-lived user home.
    stateless_runtime: bool = True
    # Session lock TTL (seconds) — prevents concurrent routing for same user
    session_lock_ttl: int = 30
    # Pod health TTL (seconds)
    pod_health_ttl: int = 60
    # Response stream TTL (seconds) — for Feishu callback
    response_stream_ttl: int = 86400  # 24h

    # Redis key prefixes
    key_route: str = "route"           # route:{user_id} → pod_id
    key_pod_active: str = "pod:active"   # pod:active:{pod_id} → user_id
    key_pod_idle: str = "pod:idle"      # ZSET: idle pods, score=idle_since_ts
    key_pod_health: str = "pod:health"  # pod:health:{pod_id} → timestamp
    key_session_lock: str = "session:lock"  # session:lock:{user_id}
    key_active_pods: str = "active-pods"  # SET of pod_ids currently serving users
    key_feishu_requests: str = "feishu:requests"  # STREAM
    key_feishu_responses: str = "feishu:responses"  # prefix for feishu:responses:{id}
    key_skill_update: str = "channel:skill-update"  # PUBSUB

    # Agent Pod defaults
    agent_pod_base_url: str = "http://agent-pod.default.svc.cluster.local:8642"
    sidecar_base_url_suffix: str = ":8643"  # append to pod name for sidecar port
    prepare_timeout: int = 5  # seconds to wait for Pod /internal/prepare
    prepare_retry_interval: float = 0.5  # seconds between retries
    prepare_max_retries: int = 6  # ~3s total

    # Auth Service (for JWT verification)
    auth_service_url: str = "http://auth-service.hermes-control.svc.cluster.local:8001"
    auth_verify_endpoint: str = "/auth/token/verify"

    # State Service (remote user/session/config/memory/cache state)
    state_service_url: str = "http://state-service.hermes-control.svc.cluster.local:8006"
    state_service_token: str = "dev-state-key-change-in-prod"

    # Quota Service
    quota_service_url: str = "http://quota-service.hermes-control.svc.cluster.local:8003"
    quota_check_endpoint: str = "/quota/check"

    # Skills hot-update
    skill_update_channel: str = "channel:skill-update"
    skill_reload_batch_size: int = 20
    skill_reload_batch_interval: float = 5.0  # seconds between batches

    # Scheduler background task interval
    scheduler_interval: int = 60  # seconds

    # Health check
    health_check_timeout: int = 3  # seconds to ping a Pod

    # Auth (shared secret for internal calls)
    internal_api_key: str = "dev-internal-key-change-in-prod"

    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"


settings = Settings()
