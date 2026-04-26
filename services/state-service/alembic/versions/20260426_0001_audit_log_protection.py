"""Restrict hermes_app role: revoke DELETE on state_audit_events.

Revision ID: 20260426_0001
Revises: 20260425_0001
Create Date: 2026-04-26

NOTE: This migration creates a least-privilege ``hermes_app`` database role for
application use.  In production, set STATE_DATABASE_URL to connect as
``hermes_app`` rather than the owner role (``hermes``).  Only migrations should
run as the owner so that the application process cannot hard-delete audit rows.

The migration is a no-op on SQLite (used for unit tests); it only applies
GRANT/REVOKE on PostgreSQL.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "20260426_0001"
down_revision = "20260425_0001"
branch_labels = None
depends_on = None

# All tables managed by the state service
_STATE_TABLES = [
    "state_user_configs",
    "state_sessions",
    "state_messages",
    "state_memory",
    "state_cache_metadata",
    "state_audit_events",
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # GRANT/REVOKE not applicable to SQLite used in unit tests

    # Create the application role idempotently
    op.execute(
        text(
            "DO $$ BEGIN "
            "  IF NOT EXISTS ("
            "    SELECT FROM pg_catalog.pg_roles WHERE rolname = 'hermes_app'"
            "  ) THEN "
            "    CREATE ROLE hermes_app LOGIN; "
            "  END IF; "
            "END $$;"
        )
    )

    # Grant full DML privileges on all state tables
    for table in _STATE_TABLES:
        op.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO hermes_app;"))

    # Revoke DELETE on the audit log — it must be append-only for the app role
    op.execute(text("REVOKE DELETE ON state_audit_events FROM hermes_app;"))

    # Allow sequence USAGE so the app role can INSERT rows with SERIAL/BIGSERIAL PKs
    op.execute(text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hermes_app;"))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for table in _STATE_TABLES:
        op.execute(text(f"REVOKE ALL ON {table} FROM hermes_app;"))
    op.execute(text("REVOKE USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public FROM hermes_app;"))
