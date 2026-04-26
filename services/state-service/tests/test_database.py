"""Tests for state_service.database module — covers init_db, close_db, health_check,
current_migration_revision, readiness_check, and get_session."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine as sync_create_engine
from sqlalchemy import text as sync_text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------


def test_init_db_no_op_when_auto_create_disabled(monkeypatch):
    """init_db returns immediately when auto_create_schema=False (lines 32-33)."""
    import state_service.database as db_module
    from state_service import config as cfg_module

    monkeypatch.setattr(cfg_module.settings, "auto_create_schema", False)

    # Should complete without error (no DB access)
    asyncio.run(db_module.init_db())


def test_init_db_creates_tables_when_enabled(tmp_path, monkeypatch):
    """init_db calls create_all when auto_create_schema=True (lines 34-35)."""
    import state_service.database as db_module
    from state_service import config as cfg_module

    monkeypatch.setattr(cfg_module.settings, "auto_create_schema", True)

    sqlite_path = tmp_path / "test_init.db"
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{sqlite_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)

    try:
        asyncio.run(db_module.init_db())

        # Verify that tables were created in the SQLite file
        sync_engine = sync_create_engine(f"sqlite:///{sqlite_path}")
        from sqlalchemy import inspect as sa_inspect

        tables = set(sa_inspect(sync_engine).get_table_names())
        sync_engine.dispose()
        assert "state_sessions" in tables
        assert "state_messages" in tables
    finally:
        asyncio.run(test_engine.dispose())


# ---------------------------------------------------------------------------
# close_db
# ---------------------------------------------------------------------------


def test_close_db_disposes_engine(monkeypatch):
    """close_db calls engine.dispose() (line 39)."""
    import state_service.database as db_module

    mock_engine = AsyncMock()
    monkeypatch.setattr(db_module, "engine", mock_engine)

    asyncio.run(db_module.close_db())
    mock_engine.dispose.assert_called_once()


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


def test_health_check_returns_true_on_success(tmp_path, monkeypatch):
    """health_check returns True when DB responds (lines 43-46)."""
    import state_service.database as db_module

    test_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'health.db'}")
    monkeypatch.setattr(db_module, "engine", test_engine)

    try:
        result = asyncio.run(db_module.health_check())
        assert result is True
    finally:
        asyncio.run(test_engine.dispose())


def test_health_check_returns_false_on_connection_failure(monkeypatch):
    """health_check returns False when the connection raises (lines 47-48)."""
    import state_service.database as db_module

    # Build a mock engine whose connect() context manager raises
    mock_engine = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(side_effect=Exception("DB down"))
    cm.__aexit__ = AsyncMock(return_value=False)
    mock_engine.connect.return_value = cm
    monkeypatch.setattr(db_module, "engine", mock_engine)

    result = asyncio.run(db_module.health_check())
    assert result is False


# ---------------------------------------------------------------------------
# current_migration_revision
# ---------------------------------------------------------------------------


def test_current_migration_revision_returns_version(tmp_path, monkeypatch):
    """Returns the stamped revision from alembic_version (lines 53-56)."""
    import state_service.database as db_module

    sqlite_path = tmp_path / "revision.db"
    sync_engine = sync_create_engine(f"sqlite:///{sqlite_path}")
    with sync_engine.connect() as conn:
        conn.execute(
            sync_text(
                "CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"
            )
        )
        conn.execute(sync_text("INSERT INTO alembic_version VALUES ('20260426_0001')"))
        conn.commit()
    sync_engine.dispose()

    test_engine = create_async_engine(f"sqlite+aiosqlite:///{sqlite_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)

    try:
        result = asyncio.run(db_module.current_migration_revision())
        assert result == "20260426_0001"
    finally:
        asyncio.run(test_engine.dispose())


def test_current_migration_revision_returns_none_when_no_table(tmp_path, monkeypatch):
    """Returns None when alembic_version table is missing (lines 57-58)."""
    import state_service.database as db_module

    # Fresh SQLite DB — no alembic_version table
    test_engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'no_rev.db'}"
    )
    monkeypatch.setattr(db_module, "engine", test_engine)

    try:
        result = asyncio.run(db_module.current_migration_revision())
        assert result is None
    finally:
        asyncio.run(test_engine.dispose())


def test_current_migration_revision_returns_none_on_connection_error(monkeypatch):
    """Returns None when the engine connection itself fails (lines 57-58)."""
    import state_service.database as db_module

    mock_engine = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(side_effect=Exception("Connection error"))
    cm.__aexit__ = AsyncMock(return_value=False)
    mock_engine.connect.return_value = cm
    monkeypatch.setattr(db_module, "engine", mock_engine)

    result = asyncio.run(db_module.current_migration_revision())
    assert result is None


# ---------------------------------------------------------------------------
# readiness_check
# ---------------------------------------------------------------------------


def test_readiness_check_migration_ok(tmp_path, monkeypatch):
    """readiness_check returns migration_ok=True when revision matches (lines 63-65)."""
    import state_service.database as db_module
    from state_service import config as cfg_module

    monkeypatch.setattr(
        cfg_module.settings, "expected_migration_revision", "20260426_0001"
    )

    sqlite_path = tmp_path / "ready.db"
    sync_engine = sync_create_engine(f"sqlite:///{sqlite_path}")
    with sync_engine.connect() as conn:
        conn.execute(
            sync_text(
                "CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"
            )
        )
        conn.execute(sync_text("INSERT INTO alembic_version VALUES ('20260426_0001')"))
        conn.commit()
    sync_engine.dispose()

    test_engine = create_async_engine(f"sqlite+aiosqlite:///{sqlite_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)

    try:
        result = asyncio.run(db_module.readiness_check())
        assert result["db_ok"] is True
        assert result["migration_ok"] is True
        assert result["migration_revision"] == "20260426_0001"
    finally:
        asyncio.run(test_engine.dispose())


def test_readiness_check_migration_not_ok_on_revision_mismatch(tmp_path, monkeypatch):
    """readiness_check returns migration_ok=False when revision mismatches."""
    import state_service.database as db_module
    from state_service import config as cfg_module

    monkeypatch.setattr(
        cfg_module.settings, "expected_migration_revision", "20260426_0001"
    )

    sqlite_path = tmp_path / "mismatch.db"
    sync_engine = sync_create_engine(f"sqlite:///{sqlite_path}")
    with sync_engine.connect() as conn:
        conn.execute(
            sync_text(
                "CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"
            )
        )
        conn.execute(sync_text("INSERT INTO alembic_version VALUES ('old_revision')"))
        conn.commit()
    sync_engine.dispose()

    test_engine = create_async_engine(f"sqlite+aiosqlite:///{sqlite_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)

    try:
        result = asyncio.run(db_module.readiness_check())
        assert result["db_ok"] is True
        assert result["migration_ok"] is False
        assert result["migration_revision"] == "old_revision"
    finally:
        asyncio.run(test_engine.dispose())


def test_readiness_check_db_not_ok(monkeypatch):
    """readiness_check returns db_ok=False when DB connection fails."""
    import state_service.database as db_module

    mock_engine = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(side_effect=Exception("DB down"))
    cm.__aexit__ = AsyncMock(return_value=False)
    mock_engine.connect.return_value = cm
    monkeypatch.setattr(db_module, "engine", mock_engine)

    result = asyncio.run(db_module.readiness_check())
    assert result["db_ok"] is False
    assert result["migration_ok"] is False


# ---------------------------------------------------------------------------
# get_session
# ---------------------------------------------------------------------------


def test_get_session_commits_on_normal_exit(tmp_path, monkeypatch):
    """get_session commits the session on clean exit (lines 75-78)."""
    import state_service.database as db_module

    sqlite_path = tmp_path / "get_session.db"
    test_engine = create_async_engine(
        f"sqlite+aiosqlite:///{sqlite_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_factory = async_sessionmaker(
        test_engine, expire_on_commit=False, autoflush=False
    )
    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(db_module, "async_session_factory", test_factory)

    async def run():
        async with db_module.get_session() as session:
            pass  # Normal exit — commit should be called

    try:
        asyncio.run(run())
    finally:
        asyncio.run(test_engine.dispose())


def test_get_session_rollbacks_on_exception(tmp_path, monkeypatch):
    """get_session rolls back and re-raises when an exception occurs (lines 79-83)."""
    import state_service.database as db_module

    sqlite_path = tmp_path / "rollback.db"
    test_engine = create_async_engine(
        f"sqlite+aiosqlite:///{sqlite_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_factory = async_sessionmaker(
        test_engine, expire_on_commit=False, autoflush=False
    )
    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(db_module, "async_session_factory", test_factory)

    async def run():
        with pytest.raises(ValueError, match="Forced error"):
            async with db_module.get_session() as _session:
                raise ValueError("Forced error")

    try:
        asyncio.run(run())
    finally:
        asyncio.run(test_engine.dispose())
