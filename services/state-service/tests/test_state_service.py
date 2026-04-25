import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from state_service.models import Base
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

            await db.commit()

        await engine.dispose()

    asyncio.run(scenario())
