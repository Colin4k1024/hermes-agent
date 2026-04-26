import asyncio

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from state_service.models import Base


def test_state_service_http_flow_and_user_isolation(tmp_path):
    async def scenario():
        from state_service.main import app, db_dep

        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'http.db'}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

        async def override_db():
            async with factory() as db:
                try:
                    yield db
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise

        app.dependency_overrides[db_dep] = override_db
        transport = httpx.ASGITransport(app=app)
        headers = {
            "Authorization": "Bearer dev-state-key-change-in-prod",
            "X-Tenant-ID": "corp",
            "X-User-ID": "u-1",
            "X-Session-ID": "s-1",
            "X-Request-ID": "r-1",
        }
        async with httpx.AsyncClient(transport=transport, base_url="http://state-service") as client:
            cfg = await client.put(
                "/state/config",
                headers=headers,
                json={"scope": "user", "key": "model", "value": {"default": "test-model"}},
            )
            assert cfg.status_code == 200

            effective = await client.get("/state/config/effective", headers=headers)
            assert effective.status_code == 200
            assert effective.json()["config"]["model"]["default"] == "test-model"

            created = await client.post(
                "/state/sessions",
                headers=headers,
                json={"session_id": "s-1", "source": "api", "model": "test-model"},
            )
            assert created.status_code == 200

            metadata = await client.get("/state/sessions/s-1/metadata", headers=headers)
            assert metadata.status_code == 200
            metadata_body = metadata.json()
            assert metadata_body["id"] == "s-1"
            assert metadata_body["tenant_id"] == "corp"
            assert metadata_body["user_id"] == "u-1"
            assert metadata_body["source"] == "api"
            assert metadata_body["model"] == "test-model"

            appended = await client.post(
                "/state/sessions/s-1/messages",
                headers=headers,
                json={"role": "user", "content": "hello over http"},
            )
            assert appended.status_code == 200

            messages = await client.get("/state/sessions/s-1/messages", headers=headers)
            assert messages.status_code == 200
            assert messages.json()["messages"] == [{"role": "user", "content": "hello over http"}]

            attacker_headers = {**headers, "X-User-ID": "u-2"}
            denied = await client.get("/state/sessions/s-1", headers=attacker_headers)
            assert denied.status_code == 404
            denied_metadata = await client.get("/state/sessions/s-1/metadata", headers=attacker_headers)
            assert denied_metadata.status_code == 404

            other_tenant_headers = {**headers, "X-Tenant-ID": "other-corp"}
            owner_metadata = await client.get("/state/sessions/s-1/metadata", headers=other_tenant_headers)
            assert owner_metadata.status_code == 200
            assert owner_metadata.json()["tenant_id"] == "corp"

            unauthenticated = await client.get("/state/config/effective", headers={"X-User-ID": "u-1"})
            assert unauthenticated.status_code == 401

        app.dependency_overrides.clear()
        await engine.dispose()

    asyncio.run(scenario())
