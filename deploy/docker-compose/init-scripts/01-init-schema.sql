-- Hermes Platform — PostgreSQL init script
-- Creates extension and seed data for local development

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Seed quota config
INSERT INTO quota_configs (quota_group, daily_token_limit, daily_request_limit, model_allowlist)
VALUES
    ('default', 1000000, 500, NULL),
    ('power_user', 5000000, 2000, NULL),
    ('admin', 999999999, 999999, NULL)
ON CONFLICT (quota_group) DO NOTHING;

-- Seed a dev admin user (password: admin123, SHA-256 of 'admin123')
-- In dev only — never in production
INSERT INTO users (
    id, username, email, display_name, role, status,
    sso_subject, feishu_union_id, quota_group, nas_shard,
    create_time, update_time
) VALUES (
    '00000000-0000-0000-0000-000000000001',
    'admin',
    'admin@hermes-dev.local',
    'Local Admin',
    'admin',
    'active',
    'dev-admin-subject',
    NULL,
    'admin',
    '00',
    now(), now()
) ON CONFLICT (username) DO NOTHING;
