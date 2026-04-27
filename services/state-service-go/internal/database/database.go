package database

import (
	"context"
	"fmt"

	_ "github.com/gogf/gf/contrib/drivers/pgsql/v2"
	"github.com/gogf/gf/v2/database/gdb"
	"github.com/gogf/gf/v2/frame/g"
)

var db gdb.DB

// Init initializes the database connection
func Init() error {
	db = g.DB()

	// Auto-create schema
	ctx := context.Background()
	if err := createSchema(ctx); err != nil {
		g.Log().Warningf(ctx, "schema creation warning: %v", err)
	}

	g.Log().Info(ctx, "database initialized successfully")
	return nil
}

// Close closes the database connection
func Close() {
	if db != nil {
		db.Close(nil)
	}
}

// DB returns the database instance
func DB() gdb.DB {
	return db
}

// createSchema creates the database tables if they don't exist
func createSchema(ctx context.Context) error {
	// Create state_sessions table
	if _, err := db.Exec(ctx, `
		CREATE TABLE IF NOT EXISTS state_sessions (
			id VARCHAR(128) PRIMARY KEY,
			tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
			user_id VARCHAR(128) NOT NULL,
			source VARCHAR(64) NOT NULL,
			model VARCHAR(256),
			model_config JSONB,
			system_prompt_ref VARCHAR(256),
			parent_session_id VARCHAR(128),
			title VARCHAR(200),
			started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
			ended_at TIMESTAMP WITH TIME ZONE,
			end_reason VARCHAR(64),
			message_count INT NOT NULL DEFAULT 0,
			tool_call_count INT NOT NULL DEFAULT 0,
			input_tokens BIGINT NOT NULL DEFAULT 0,
			output_tokens BIGINT NOT NULL DEFAULT 0,
			cache_read_tokens BIGINT NOT NULL DEFAULT 0,
			cache_write_tokens BIGINT NOT NULL DEFAULT 0,
			reasoning_tokens BIGINT NOT NULL DEFAULT 0
		)
	`); err != nil {
		return fmt.Errorf("failed to create state_sessions: %w", err)
	}

	// Create indexes for sessions
	indexes := []string{
		`CREATE INDEX IF NOT EXISTS ix_state_sessions_owner_id ON state_sessions(tenant_id, user_id, id)`,
		`CREATE INDEX IF NOT EXISTS ix_state_sessions_owner_started ON state_sessions(tenant_id, user_id, started_at)`,
		`CREATE INDEX IF NOT EXISTS ix_state_sessions_parent ON state_sessions(parent_session_id)`,
	}
	for _, idx := range indexes {
		if _, err := db.Exec(ctx, idx); err != nil {
			return fmt.Errorf("failed to create index: %w", err)
		}
	}

	// Create state_messages table
	if _, err := db.Exec(ctx, `
		CREATE TABLE IF NOT EXISTS state_messages (
			id BIGSERIAL PRIMARY KEY,
			tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
			user_id VARCHAR(128) NOT NULL,
			session_id VARCHAR(128) NOT NULL,
			role VARCHAR(32) NOT NULL,
			content TEXT,
			tool_call_id VARCHAR(128),
			tool_calls JSONB,
			tool_name VARCHAR(128),
			timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
			token_count INT,
			finish_reason VARCHAR(64),
			reasoning TEXT,
			reasoning_details JSONB,
			codex_reasoning_items JSONB,
			object_uri VARCHAR(512),
			content_size BIGINT,
			oss_version_id VARCHAR(128)
		)
	`); err != nil {
		return fmt.Errorf("failed to create state_messages: %w", err)
	}

	// Create indexes for messages
	msgIndexes := []string{
		`CREATE INDEX IF NOT EXISTS ix_state_messages_session_order ON state_messages(tenant_id, user_id, session_id, timestamp, id)`,
		`CREATE INDEX IF NOT EXISTS ix_state_messages_object_uri ON state_messages(object_uri) WHERE object_uri IS NOT NULL`,
	}
	for _, idx := range msgIndexes {
		if _, err := db.Exec(ctx, idx); err != nil {
			return fmt.Errorf("failed to create message index: %w", err)
		}
	}

	// Create state_memory table
	if _, err := db.Exec(ctx, `
		CREATE TABLE IF NOT EXISTS state_memory (
			id BIGSERIAL PRIMARY KEY,
			tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
			user_id VARCHAR(128) NOT NULL,
			namespace VARCHAR(64) NOT NULL DEFAULT 'memory',
			key VARCHAR(256) NOT NULL,
			value TEXT NOT NULL,
			metadata_json JSONB NOT NULL DEFAULT '{}',
			is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
			created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
			updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
			object_uri VARCHAR(512),
			UNIQUE(tenant_id, user_id, namespace, key)
		)
	`); err != nil {
		return fmt.Errorf("failed to create state_memory: %w", err)
	}

	// Create indexes for memory
	memIndexes := []string{
		`CREATE INDEX IF NOT EXISTS ix_state_memory_owner ON state_memory(tenant_id, user_id, namespace)`,
		`CREATE INDEX IF NOT EXISTS ix_state_memory_object_uri ON state_memory(object_uri) WHERE object_uri IS NOT NULL`,
	}
	for _, idx := range memIndexes {
		if _, err := db.Exec(ctx, idx); err != nil {
			return fmt.Errorf("failed to create memory index: %w", err)
		}
	}

	// Create state_cache_metadata table
	if _, err := db.Exec(ctx, `
		CREATE TABLE IF NOT EXISTS state_cache_metadata (
			id BIGSERIAL PRIMARY KEY,
			tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
			user_id VARCHAR(128) NOT NULL,
			session_id VARCHAR(128),
			cache_key VARCHAR(512) NOT NULL,
			kind VARCHAR(64) NOT NULL,
			object_uri VARCHAR(1024),
			content_sha256 VARCHAR(64),
			size_bytes BIGINT,
			metadata_json JSONB NOT NULL DEFAULT '{}',
			created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
			updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
			UNIQUE(tenant_id, user_id, cache_key)
		)
	`); err != nil {
		return fmt.Errorf("failed to create state_cache_metadata: %w", err)
	}

	// Create state_audit_events table
	if _, err := db.Exec(ctx, `
		CREATE TABLE IF NOT EXISTS state_audit_events (
			id BIGSERIAL PRIMARY KEY,
			tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
			user_id VARCHAR(128),
			session_id VARCHAR(128),
			request_id VARCHAR(128),
			action VARCHAR(64) NOT NULL,
			resource_type VARCHAR(64) NOT NULL,
			resource_id VARCHAR(512),
			metadata_json JSONB NOT NULL DEFAULT '{}',
			created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
		)
	`); err != nil {
		return fmt.Errorf("failed to create state_audit_events: %w", err)
	}

	// Create indexes for audit
	auditIndexes := []string{
		`CREATE INDEX IF NOT EXISTS ix_state_audit_owner_created ON state_audit_events(tenant_id, user_id, created_at)`,
		`CREATE INDEX IF NOT EXISTS ix_state_audit_resource ON state_audit_events(tenant_id, resource_type, resource_id)`,
	}
	for _, idx := range auditIndexes {
		if _, err := db.Exec(ctx, idx); err != nil {
			return fmt.Errorf("failed to create audit index: %w", err)
		}
	}

	// Create state_user_configs table
	if _, err := db.Exec(ctx, `
		CREATE TABLE IF NOT EXISTS state_user_configs (
			id BIGSERIAL PRIMARY KEY,
			tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
			user_id VARCHAR(128) NOT NULL,
			scope VARCHAR(32) NOT NULL DEFAULT 'user',
			key VARCHAR(256) NOT NULL,
			value JSONB NOT NULL DEFAULT '{}',
			created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
			updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
			UNIQUE(tenant_id, user_id, scope, key)
		)
	`); err != nil {
		return fmt.Errorf("failed to create state_user_configs: %w", err)
	}

	if _, err := db.Exec(ctx, `CREATE INDEX IF NOT EXISTS ix_state_user_configs_owner ON state_user_configs(tenant_id, user_id)`); err != nil {
		return fmt.Errorf("failed to create user_configs index: %w", err)
	}

	return nil
}
