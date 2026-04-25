# Hermes State Service

Remote user state service for stateless Hermes Agent runtimes.

## Runtime Configuration

Environment variables use the `STATE_` prefix.

| Variable | Default | Purpose |
|----------|---------|---------|
| `STATE_HOST` | `0.0.0.0` | HTTP bind host |
| `STATE_PORT` | `8006` | HTTP bind port |
| `STATE_DEBUG` | `false` | SQLAlchemy echo/debug mode |
| `STATE_DATABASE_URL` | `postgresql+asyncpg://hermes:hermes@localhost:5432/hermes_platform` | Authoritative Postgres state database |
| `STATE_DB_POOL_SIZE` | `10` | SQLAlchemy async pool size |
| `STATE_AUTO_CREATE_SCHEMA` | `true` | Compatibility mode for local tests; production should run Alembic and set this to `false` |
| `STATE_EXPECTED_MIGRATION_REVISION` | `20260425_0001` | Revision required by `/ready` |
| `STATE_REDIS_URL` | `redis://localhost:6379/0` | Hot cache/session coordination backend |
| `STATE_OBJECT_STORAGE_ENDPOINT` | unset | Object storage endpoint for large cache/blob payloads |
| `STATE_OBJECT_STORAGE_BUCKET` | `hermes-state-cache` | Object storage bucket for cache/blob payloads |
| `STATE_INTERNAL_API_KEY` | `dev-state-key-change-in-prod` | Bearer token required for internal API calls |
| `STATE_DEFAULT_TENANT_ID` | `default` | Tenant fallback for single-enterprise deployments |

## Database Migration

Run migrations from `services/state-service`:

```bash
alembic upgrade head
```

The container entrypoint runs this before starting Uvicorn.

## Health Probes

- `/health`: database connectivity only.
- `/ready`: database connectivity plus Alembic revision check.

Production readiness should use `/ready`.

## Isolation Rules

- Every state request requires `Authorization: Bearer <STATE_INTERNAL_API_KEY>`.
- Every state request requires `X-User-ID`.
- Tenant defaults to `STATE_DEFAULT_TENANT_ID` when `X-Tenant-ID` is absent.
- State reads and writes are scoped by `tenant_id + user_id`.
- Session, memory, config, cache metadata, and audit records all carry tenant/user context.
