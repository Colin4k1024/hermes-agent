import asyncio

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy import create_engine

from state_service.models import AuditEvent, Base
from state_service.schemas import (
    CacheMetadataRequest,
    ConfigUpsertRequest,
    EndSessionRequest,
    MemoryUpsertRequest,
    MessageCreateRequest,
    RequestContext,
    SessionCreateRequest,
    UsageUpdateRequest,
)


def test_alembic_initial_migration_creates_schema(tmp_path, monkeypatch):
    import state_service.config as state_config

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("STATE_DATABASE_URL", db_url)
    state_config.settings.database_url = db_url

    cfg = Config("services/state-service/alembic.ini")
    cfg.set_main_option("script_location", "services/state-service/alembic")

    command.upgrade(cfg, "head")
    sync_engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    try:
        tables = set(inspect(sync_engine).get_table_names())
        assert {
            "alembic_version",
            "state_user_configs",
            "state_sessions",
            "state_messages",
            "state_memory",
            "state_cache_metadata",
            "state_audit_events",
        }.issubset(tables)
    finally:
        sync_engine.dispose()


def test_state_service_session_memory_cache_flow(tmp_path):
    async def scenario():
        from state_service.main import (
            append_message,
            create_session,
            get_cache_metadata,
            get_effective_config,
            get_messages,
            list_memory,
            list_sessions,
            put_cache_metadata,
            search_messages,
            upsert_config,
            upsert_memory,
            update_usage,
            end_session,
        )

        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        ctx = RequestContext(tenant_id="corp", user_id="u-1", session_id="s-1")

        async with factory() as db:
            await upsert_config(
                ConfigUpsertRequest(scope="user", key="model", value={"default": "test-model"}),
                ctx,
                db,
            )
            cfg = await get_effective_config(ctx, db)
            assert cfg.config["model"]["default"] == "test-model"

            created = await create_session(
                SessionCreateRequest(session_id="s-1", source="api", model="test-model"),
                ctx,
                db,
            )
            assert created.id == "s-1"

            msg = await append_message(
                "s-1",
                MessageCreateRequest(role="user", content="hello remote state"),
                ctx,
                db,
            )
            assert msg["id"] == 1

            messages = await get_messages("s-1", ctx, db)
            assert messages.messages == [{"role": "user", "content": "hello remote state"}]

            recent = await list_sessions(ctx=ctx, db=db)
            assert recent.sessions[0]["id"] == "s-1"
            assert recent.sessions[0]["preview"] == "hello remote state"

            found = await search_messages(query="remote", ctx=ctx, db=db)
            assert found.results[0]["session_id"] == "s-1"

            await update_usage(
                "s-1",
                UsageUpdateRequest(input_tokens=10, output_tokens=5),
                ctx,
                db,
            )
            ended = await end_session("s-1", EndSessionRequest(end_reason="done"), ctx, db)
            assert ended["ok"] is True

            mem = await upsert_memory(
                "memory",
                "k1",
                MemoryUpsertRequest(value="prefers concise answers"),
                ctx,
                db,
            )
            assert mem.value == "prefers concise answers"
            listed = await list_memory(namespace="memory", ctx=ctx, db=db)
            assert listed.items[0].key == "k1"

            cache = await put_cache_metadata(
                "doc/1",
                CacheMetadataRequest(kind="document", object_uri="s3://bucket/doc/1"),
                ctx,
                db,
            )
            assert cache.object_uri == "s3://bucket/doc/1"
            loaded_cache = await get_cache_metadata("doc/1", ctx, db)
            assert loaded_cache.kind == "document"

            audit_rows = (await db.execute(
                select(AuditEvent).where(AuditEvent.tenant_id == "corp")
            )).scalars().all()
            audit_actions = {row.action for row in audit_rows}
            assert {"read", "write", "search"}.issubset(audit_actions)

            await db.commit()

        await engine.dispose()

    asyncio.run(scenario())


def test_state_service_rejects_cross_user_session_access(tmp_path):
    async def scenario():
        from state_service.main import create_session, get_session_by_id

        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'isolation.db'}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with factory() as db:
            owner = RequestContext(tenant_id="corp", user_id="u-1", session_id="s-1")
            attacker = RequestContext(tenant_id="corp", user_id="u-2", session_id="s-1")
            await create_session(SessionCreateRequest(session_id="s-1", source="api"), owner, db)

            with pytest.raises(HTTPException) as exc:
                await get_session_by_id("s-1", attacker, db)
            assert exc.value.status_code == 404

            await db.commit()
        await engine.dispose()

    asyncio.run(scenario())
