---
artifact: api-contract
task: hermes-enterprise-saas
date: 2026-04-16
role: backend-engineer
status: active（Skills Registry / Feishu Bot / Quota Service / Agent Router）
---

# API Contract — Skills Registry Service

**版本**: v0.1.0
**日期**: 2026-04-16
**服务**: Skills Registry (`services/skills-registry/`)
**端口**: 8004 (开发环境)
**主责角色**: backend-engineer

---

## 概述

Skills Registry Service 管理组织级 Skills 的 CRUD、版本控制、NAS 文件存储和热更新通知。
核心职责：
- Skill 元数据管理（PostgreSQL `org_skills` 表）
- Skill 文件存储（NAS `/nas/org-skills/` 或本地 `./dev-skills/`）
- SKILL.md YAML frontmatter 解析与验证
- Redis PubSub 热更新广播（channel: `channel:skill-update`）

---

## 基础信息

| 项目 | 值 |
|------|-----|
| Base URL | `http://{host}:8004` |
| Content-Type | `application/json` |
| 认证 | Admin API: `X-Admin-Key` header |
| 数据库 | PostgreSQL (`hermes_skills` DB) |
| 文件存储 | NAS `/nas/org-skills/` 或本地 `./dev-skills/` |

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SKILLS_REGISTRY_PORT` | `8004` | 服务端口 |
| `SKILLS_REGISTRY_DEBUG` | `false` | 调试模式（使用本地存储）|
| `SKILLS_REGISTRY_POSTGRES_HOST` | `localhost` | PostgreSQL 主机 |
| `SKILLS_REGISTRY_REDIS_HOST` | `localhost` | Redis 主机 |
| `SKILLS_REGISTRY_SKILLS_STORAGE_PATH` | `/nas/org-skills` | NAS 存储路径 |
| `SKILLS_REGISTRY_SKILLS_LOCAL_DEV_PATH` | `./dev-skills` | 本地开发路径 |
| `SKILLS_REGISTRY_ADMIN_API_KEY` | `dev-admin-key-change-in-prod` | Admin API 密钥 |

---

## 接口清单

### Health

#### `GET /health`

全量健康检查（DB + 存储 + Redis）。

**认证**: 无

**响应** `200 OK`:
```json
{
  "db_ok": true,
  "storage_ok": true,
  "redis_ok": true,
  "version": "0.1.0"
}
```

---

### Skills — 公开端点（用户 / Agent Pod）

#### `GET /skills`

列出所有活跃的 org-level skills。

**认证**: 无

**查询参数**:

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `status` | string | `active` | 过滤状态（`active` / `archived`）|
| `tags` | string | — | 逗号分隔的标签（交集过滤）|
| `search` | string | — | 按 name 或 description 模糊搜索 |
| `page` | int | `1` | 页码（从 1 开始）|
| `page_size` | int | `20` | 每页条数（最大 100）|

**响应** `200 OK`:
```json
[
  {
    "name": "code-review-guide",
    "description": "Org-wide code review best practices",
    "version": "1",
    "status": "active",
    "tags": ["code-review", "quality"],
    "author": "Platform Team",
    "update_time": "2026-04-16T10:00:00Z"
  }
]
```

---

#### `GET /skills/{skill_name}`

获取指定 skill 的完整元数据。

**认证**: 无

**路径参数**:

| 参数 | 类型 | 说明 |
|------|------|------|
| `skill_name` | string | Skill 名称（URL-safe）|

**响应** `200 OK`:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "code-review-guide",
  "description": "Org-wide code review best practices",
  "version": "1",
  "status": "active",
  "nas_path": "/nas/org-skills/code-review-guide/SKILL.md",
  "published_by": "user-uuid",
  "tags": ["code-review", "quality"],
  "related_skills": ["test-driven-development"],
  "author": "Platform Team",
  "license": "MIT",
  "create_time": "2026-04-16T09:00:00Z",
  "update_time": "2026-04-16T10:00:00Z"
}
```

**错误**:

| 状态码 | 说明 |
|--------|------|
| `404 Not Found` | Skill 不存在或已归档 |

---

#### `GET /skills/{skill_name}/content`

获取 SKILL.md 的 markdown 正文（不含 YAML frontmatter）。

**认证**: 无

**响应** `200 OK`:
```json
{
  "name": "code-review-guide",
  "version": "1",
  "nas_path": "/nas/org-skills/code-review-guide/SKILL.md",
  "content": "# Code Review Guide\n\nUse this skill when..."
}
```

---

### Admin — 技能管理端点

#### `GET /admin/skills`

管理员列表所有 skills（含已归档）。

**认证**: `X-Admin-Key` header

**请求头**:

| Header | 说明 |
|--------|------|
| `X-Admin-Key` | Admin API 密钥 |

**响应** `200 OK`: 同 `GET /skills`，但返回所有状态。

**错误**:

| 状态码 | 说明 |
|--------|------|
| `401 Unauthorized` | 无效或缺失 `X-Admin-Key` |

---

#### `POST /admin/skills`

创建新 skill。

**认证**: `X-Admin-Key` header

**请求体**:
```json
{
  "name": "code-review-guide",
  "description": "Optional description override",
  "skill_md": "---\nname: code-review-guide\ndescription: ...\nversion: 1.0.0\nauthor: Platform Team\nmetadata:\n  hermes:\n    tags: [code-review, quality]\n    related_skills: [test-driven-development]\n---\n\n# Code Review Guide\n\n...",
  "tags": ["code-review", "quality"],
  "published_by": "user-uuid"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | 1-64 字符，只允许 `[a-zA-Z0-9_-]` |
| `skill_md` | string | 是 | 完整 SKILL.md 内容（含 YAML frontmatter）|
| `description` | string | 否 | 覆盖 frontmatter 中的 description |
| `tags` | string[] | 否 | 覆盖 frontmatter 中的 tags |
| `published_by` | string (UUID) | 否 | 发布者用户 ID |

**响应** `201 Created`:
```json
{
  "success": true,
  "skill": { ... },
  "message": "Skill 'code-review-guide' created successfully"
}
```

**副作用**:

1. SKILL.md 写入 NAS `/nas/org-skills/{name}/SKILL.md`
2. 元数据插入 PostgreSQL `org_skills` 表（version = 1）
3. Redis PUBLISH `channel:skill-update` 通知 Router

**错误**:

| 状态码 | 说明 |
|--------|------|
| `401 Unauthorized` | 无效 `X-Admin-Key` |
| `409 Conflict` | Skill 名称已存在 |
| `422 Unprocessable Entity` | SKILL.md 格式无效 |

---

#### `PUT /admin/skills/{skill_name}`

更新已有 skill。

**认证**: `X-Admin-Key` header

**请求体**:
```json
{
  "description": "Updated description",
  "skill_md": "---\nname: code-review-guide\nversion: 1.1.0\n...\n---",
  "tags": ["code-review", "quality", "new-tag"],
  "status": "active"
}
```

| 字段 | 效果 |
|------|------|
| `skill_md` | 重写文件 + version +1 + 发布通知 |
| `description` | 仅更新 DB |
| `tags` | 仅更新 DB |
| `status` | 仅更新 DB（`active` / `archived`）|

**响应** `200 OK`:
```json
{
  "success": true,
  "skill": { "name": "...", "version": "2", ... },
  "message": "Skill 'code-review-guide' updated to version 2"
}
```

---

#### `DELETE /admin/skills/{skill_name}`

归档 skill（软删除，不删除 NAS 文件）。

**认证**: `X-Admin-Key` header

**响应** `204 No Content`

**副作用**:
- `org_skills.status = 'archived'`
- Redis PUBLISH `channel:skill-update`（action = `archived`）

---

### Internal — 内部端点（Router / Sidecar）

#### `POST /internal/skills/notify-update`

手动触发热更新通知。

**认证**: 无（K8s 内部网络）

**请求体**:
```json
{
  "skill_name": "code-review-guide",
  "version": "2",
  "action": "updated"
}
```

| action | 值 |
|--------|---|
| 创建 | `created` |
| 更新 | `updated` |
| 归档 | `archived` |

**响应** `200 OK`:
```json
{
  "published": true,
  "channel": "channel:skill-update",
  "skill_name": "code-review-guide"
}
```

---

#### `GET /internal/skills/reload`

Router 调用此端点报告 skill 重载状态。

**认证**: 无（K8s 内部网络）

**查询参数**:

| 参数 | 类型 | 说明 |
|------|------|------|
| `skill_name` | string | 可选，只返回指定 skill |

**响应** `200 OK`:
```json
[
  {
    "pod_id": "skills-registry",
    "skill_name": "code-review-guide",
    "reloaded": true,
    "version": "2",
    "error": null
  }
]
```

> **注**：Skills Registry 本身不运行 Hermes Pod，此端点返回 skill 元数据。
> 实际 Pod 级重载由 Hermes Pod Sidecar 读取 Redis 通知后触发
> entrypoint.sh 重新初始化。

---

#### `GET /internal/health`

轻量级内部健康检查（无 DB/Redis 调用）。

**响应** `200 OK`:
```json
{
  "ok": true,
  "service": "skills-registry"
}
```

---

## 数据模型

### PostgreSQL: `org_skills`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | 主键 |
| `name` | VARCHAR(64) | 唯一标识 |
| `description` | VARCHAR(1024) | 描述 |
| `version` | INT | 版本号（每次更新 +1）|
| `status` | VARCHAR(32) | `active` / `archived` |
| `nas_path` | VARCHAR(512) | SKILL.md 文件路径 |
| `published_by` | UUID | 发布者用户 ID |
| `tags` | TEXT | 逗号分隔的标签 |
| `create_time` | TIMESTAMPTZ | 创建时间 |
| `update_time` | TIMESTAMPTZ | 更新时间 |

**索引**:
- `UNIQUE` on `name`
- `INDEX` on `status`

---

## Redis 数据结构

| Key | Type | 说明 |
|-----|------|------|
| `channel:skill-update` | PUBSUB | 热更新通知频道 |

**通知消息格式**:
```json
{
  "skill_name": "code-review-guide",
  "version": "2",
  "action": "updated"
}
```

---

## 热更新流程（来自 arch-design §3.3）

```
管理员发布/更新 Skill
    ↓
Skills Registry: POST /admin/skills 或 PUT /admin/skills/{name}
    ↓
  1. 写入/更新 SKILL.md 到 NAS
  2. 更新 PostgreSQL org_skills（version +1）
  3. Redis PUBLISH channel:skill-update
    ↓
Router: SUBSCRIBE channel:skill-update
    ↓
Router: SMEMBERS active-pods
    ↓
Router: 分批调用各 Pod /internal/skills/reload
  (batch_size=20, 间隔 5s，避免 Pod Pool 瞬时耗尽)
    ↓
各 Pod Sidecar: 重新扫描 /nas/org-skills/ 目录
    ↓
下次用户请求即使用新版 Skill
```

---

## SKILL.md 格式规范

Skills 使用 Hermes 原生 SKILL.md 格式：

```yaml
---
name: <skill-name>          # 必填，唯一标识
description: <描述>          # 选填
version: <semver>           # 选填，默认 1.0.0
author: <作者>              # 选填
license: <许可证>            # 选填
metadata:
  hermes:
    tags: [<tag1>, <tag2>]   # 标签列表
    related_skills: [<skill>] # 关联的 skill 名称
---

# <Skill 标题>

<markdown 正文>
```

Skills Registry 服务端通过 `skill_parser.py` 解析 frontmatter 验证格式。

---

## 错误响应格式

所有错误响应遵循统一格式：

```json
{
  "detail": "错误描述信息"
}
```

| HTTP 状态码 | 含义 |
|-----------|------|
| `400 Bad Request` | 请求格式错误 |
| `401 Unauthorized` | 认证失败 |
| `404 Not Found` | 资源不存在 |
| `409 Conflict` | 资源冲突（如重复创建）|
| `422 Unprocessable Entity` | 语义错误（如 SKILL.md 格式无效）|
| `500 Internal Server Error` | 服务端错误 |

---

## 技术实现

| 项目 | 实现 |
|------|------|
| 框架 | FastAPI 0.115+ |
| 数据库 | SQLAlchemy 2.0 + asyncpg |
| ORM | PostgreSQL UUID primary key |
| 文件存储 | `FileStorage` 类（NAS / 本地可切换）|
| SKILL.md 解析 | `skill_parser.py`（YAML frontmatter）|
| Redis | `redis.asyncio`（PUBSUB 发布）|
| 配置 | `pydantic-settings` + 环境变量 |
| 测试 | pytest + pytest-asyncio |

### 目录结构

```
services/skills-registry/
├── pyproject.toml
├── skills_registry/
│   ├── __init__.py
│   ├── main.py          # FastAPI app
│   ├── config.py        # Settings
│   ├── schemas.py       # Pydantic models
│   ├── models.py        # SQLAlchemy models
│   ├── database.py      # DB connection
│   ├── file_storage.py  # NAS/local file ops
│   ├── skill_parser.py  # SKILL.md parser
│   ├── redis_publisher.py  # Redis PubSub
│   └── routers/
│       ├── skills.py    # GET /skills, GET /skills/{name}
│       ├── admin.py     # POST/PUT/DELETE /admin/skills
│       └── internal.py  # POST /internal/skills/notify-update
└── tests/
    └── test_skills_registry.py
```

---

## Feishu Bot Service

**版本**: v0.1.0
**日期**: 2026-04-16
**服务**: Feishu Bot (`services/feishu-bot/`)
**端口**: 8005 (开发环境)
**主责角色**: backend-engineer
**状态**: 已完成

### 概述

Feishu Bot Service 是飞书企业自建应用的唯一 Webhook 接收端点，负责：
- 飞书签名验证（HMAC-SHA256 + 时序攻击防护 + 重放防护）
- Event ID 去重（Redis SETNX，TTL 300s）
- 身份绑定流程（未绑定用户 → 发送绑定卡片）
- 消息入队 Redis Streams（`feishu:requests` + `feishu:responses:{instance_id}`）
- 响应等待与回复发送（XREADBLOCK + 消息卡片）

架构要点（BE-3 确认方案）：
- FBot 写 `feishu:requests`（Router 消费）+ `feishu:responses:{fbot_instance_id}`（自己等待）
- Router 接口增加 `reply_channel` 字段
- XREADBLOCK timeout 30-60s
- Response stream TTL 24h

### 基础信息

| 项目 | 值 |
|------|-----|
| Base URL | `http://{host}:8005` |
| Content-Type | `application/json` |
| 依赖 | Redis Streams, Auth Service, Router Service, lark-oapi |
| 服务发现 | K8s: 2 副本，Pod name 作为 FBOT_INSTANCE_ID |

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FEISHU_APP_ID` | — | 飞书应用 ID（必填）|
| `FEISHU_APP_SECRET` | — | 飞书应用密钥（必填）|
| `REDIS_HOST` | `localhost` | Redis 主机 |
| `REDIS_PORT` | `6379` | Redis 端口 |
| `REDIS_PASSWORD` | — | Redis 密码 |
| `AUTH_SERVICE_URL` | `http://localhost:8001` | Auth Service 地址 |
| `ROUTER_SERVICE_URL` | `http://localhost:8002` | Router Service 地址 |
| `FBOT_INSTANCE_ID` | `fbp-001` | FBot 实例唯一 ID（K8s: downward API `metadata.name`）|
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `MAX_TIMESTAMP_OFFSET` | `300` | 签名时间戳校验窗口（秒）|

### 接口清单

#### `GET /health`

Liveness probe — 服务是否在运行。

**认证**: 无

**响应** `200 OK`:
```json
{
  "status": "ok",
  "service": "feishu-bot"
}
```

#### `GET /health/ready`

Readiness probe — 包含 Redis 连通性检查。

**认证**: 无

**响应** `200 OK`:
```json
{
  "status": "ok",
  "version": "0.1.0",
  "fbot_instance_id": "fbp-001",
  "redis_connected": true
}
```

#### `POST /feishu/event`

飞书 URL 验证回调。飞书在配置 Webhook URL 时发送 GET 请求以验证 URL 可达。

**认证**: 无（Feishu 平台侧验证）

**响应**:
```json
{"challenge": "<challenge_value>"}
```

#### `POST /feishu/webhook`

主 Webhook 端点 — 接收飞书事件，处理后立即返回 200。

**认证**: 飞书 HMAC-SHA256 签名（`X-Lark-Request-Timestamp` + `X-Lark-Signature` headers）

**请求 Headers**:

| Header | 说明 |
|--------|------|
| `X-Lark-Request-Timestamp` | Unix 时间戳（秒）|
| `X-Lark-Signature` | HMAC-SHA256 十六进制摘要 |

**处理流程**:
1. 签名验证（失败返回 200）
2. Event ID 去重（Redis SETNX，TTL 300s，重复则返回 200）
3. 提取 `union_id` → 调用 Auth Service 查询 `platform_user_id`
4. 未绑定：发送绑定卡片，返回 200
5. 已绑定：XADD `feishu:requests` + XADD `feishu:responses:{instance_id}`，返回 200

**飞书事件类型**（本版本支持）:

| event_type | 说明 |
|------------|------|
| `im.message.receive_v1` | 用户发送消息事件（仅处理 text 类型）|

**响应** `200 OK`:
```json
{"code": 0, "message": "ok"}
```

**签名验证失败响应** `200 OK`:
```json
{"code": "INVALID_SIGNATURE", "message": "..."}
```

### Redis Streams 数据结构

#### `feishu:requests` Stream（Router 消费）

```python
XADD feishu:requests "*" \
  user_id={platform_user_id} \
  union_id={feishu_union_id} \
  feishu_msg_id={feishu_msg_id} \
  feishu_chat_id={feishu_chat_id} \
  message={text_content} \
  reply_channel=feishu:responses:{fbot_instance_id} \
  fbot_instance_id={fbot_instance_id}
```

#### `feishu:responses:{fbot_instance_id}` Stream（FBot 自产自销）

Router 向此 stream 写入响应 chunks：
```python
XADD feishu:responses:{fbot_instance_id} "*" \
  request_id={feishu:requests_stream_id} \
  chunk={text_chunk} \
  done={true|false}
```

FBot XREADBLOCK 此 stream，超时 55s。

### 内部接口（Auth Service）

#### `GET /auth/user/by-feishu-id`

Feishu Bot 查询飞书 union_id → platform_user_id 映射。

**认证**: 内部 mTLS（由 K8s Service 网络隔离）

**查询参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `union_id` | string | 飞书 union_id |

**响应** `200 OK`:
```json
{
  "user_id": "u-12345",
  "username": "alice"
}
```

**响应** `404 Not Found`:
```json
{"detail": "union_id not found"}
```

### 项目结构

```
services/feishu-bot/
├── fbot/
│   ├── __init__.py
│   ├── main.py              # FastAPI app + webhook handler + consumer loop
│   ├── config.py             # Pydantic Settings
│   ├── models/
│   │   ├── __init__.py
│   │   └── events.py        # Pydantic models
│   ├── signature.py         # HMAC-SHA256 签名验证
│   ├── redis_client.py       # Redis Streams operations
│   ├── auth_client.py        # Auth Service HTTP client
│   ├── feishu_client.py      # lark_oapi 消息发送
│   └── utils/
│       └── __init__.py
├── tests/
│   ├── conftest.py
│   └── test_feishu_bot.py   # 29 tests: 签名/去重/Auth/卡片/Streams/端到端
├── requirements.txt
├── Dockerfile
├── docker-compose.yaml
└── .env.example
```

### 关键设计决策

| 决策 | 说明 |
|------|------|
| 全部验证失败返回 200 | 防止飞书重发风暴（ADR-005 B.6）|
| 签名使用 `hmac.compare_digest` | 常数时间比较，防时序攻击（ADR-005 B.4）|
| Event ID 去重 SETNX | 原子操作，TTL 覆盖飞书 5 次重发窗口（ADR-005 B.5）|
| FBot 自产自销响应 stream | Router 不知道 FBot 拓扑，各自写入独立 stream（BE-3 确认方案）|
| XREADBLOCK timeout 55s | 略低于 60s 避免边缘情况 |

---

*创建日期: 2026-04-16*
*更新日期: 2026-04-16（新增 Feishu Bot Service 接口契约）*
*backend-engineer: AI Lab User1-1*

---

## Agent Router Service

**版本**: v0.1.0
**日期**: 2026-04-16
**服务**: Agent Router (`services/router/`)
**端口**: 8002 (开发环境)
**主责角色**: backend-engineer
**状态**: ✅ 已完成

### 概述

Agent Router 是用户请求到 Agent Pod 的路由调度中心，核心职责：
- 用户请求 → Agent Pod 路由调度（热路由 + 冷启动）
- Redis 路由表管理（`route:{user_id}`, `pod:idle`, `pod:health`, `session:lock`）
- Pod 健康状态管理（TTL 心跳检测）
- 热冷分离策略（30 分钟 TTL，ZSET idle pool）
- Feishu 消息路由（含 `reply_channel` 回调）
- Skills 热更新 PubSub 订阅 + 分批 Pod 重启

### 基础信息

| 项目 | 值 |
|------|-----|
| Base URL | `http://{host}:8002` |
| Content-Type | `application/json` |
| Redis 连接池 | 50 连接，socket_timeout=2s，graceful degradation |
| Pod 端口 | Agent Pod :8642，Sidecar :8643 |
| 热路由 TTL | 1800s（30 分钟，与 idle timeout 一致）|
| Session Lock TTL | 30s（SET NX EX，原子操作）|
| Pod Health TTL | 60s |

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ROUTER_PORT` | `8002` | 服务端口 |
| `ROUTER_DEBUG` | `false` | 调试模式 |
| `ROUTER_REDIS_HOST` | `localhost` | Redis 主机 |
| `ROUTER_REDIS_PORT` | `6379` | Redis 端口 |
| `ROUTER_REDIS_DB` | `0` | Redis 数据库 |
| `ROUTER_REDIS_PASSWORD` | `` | Redis 密码（可选）|
| `ROUTER_INTERNAL_API_KEY` | `dev-internal-key-change-in-prod` | Admin/Debug 端点密钥 |
| `ROUTER_AUTH_SERVICE_URL` | `http://localhost:8001` | Auth Service 地址 |
| `ROUTER_QUOTA_SERVICE_URL` | `http://localhost:8003` | Quota Service 地址 |
| `ROUTER_ROUTE_TTL` | `1800` | 热路由 TTL（秒）|
| `ROUTER_SESSION_LOCK_TTL` | `30` | Session 锁 TTL（秒）|
| `ROUTER_PREPARE_TIMEOUT` | `5` | Pod prepare HTTP 超时（秒）|
| `ROUTER_SCHEDULER_INTERVAL` | `60` | 回收任务轮询间隔（秒）|

### Redis 数据结构

| Key Pattern | Type | TTL | 说明 |
|-------------|------|-----|------|
| `route:{user_id}` | STRING | 1800s | 用户→Pod 热路由映射 |
| `pod:active:{pod_id}` | STRING | 1800s | Pod→用户反向索引 |
| `pod:idle` | ZSET | — | 空闲 Pod，score = idle_since_ts |
| `pod:health:{pod_id}` | STRING | 60s | Pod 心跳时间戳 |
| `session:lock:{user_id}` | STRING | 30s | 用户分布式锁（SET NX EX）|
| `active-pods` | SET | — | 当前活跃 Pod ID 集合 |
| `feishu:requests` | STREAM | — | 飞书消息入站队列 |
| `feishu:responses:{fbot_id}` | STREAM | 86400s | 飞书响应流（Router 写入）|
| `channel:skill-update` | PUBSUB | — | Skills 热更新通知频道 |

### 接口清单

#### `GET /health`

基础 liveness probe。

**认证**: 无

**响应** `200 OK`:
```json
{
  "status": "ok",
  "service": "agent-router",
  "version": "0.1.0"
}
```

#### `GET /health/ready`

Readiness probe — 含 Redis 连通性检查。

**响应** `200 OK`（Redis 正常）:
```json
{
  "status": "ok",
  "service": "agent-router",
  "version": "0.1.0",
  "redis_connected": true,
  "idle_pods": 80,
  "active_pods": 20
}
```

**响应** `200 OK`（Redis 不可用，graceful degradation）:
```json
{
  "status": "degraded",
  "service": "agent-router",
  "version": "0.1.0",
  "redis_connected": false,
  "idle_pods": 0,
  "active_pods": 0
}
```

---

#### `GET /internal/health`

Pod Pool 健康检查（内部/运维使用）。

**响应** `200 OK`:
```json
{
  "ok": true,
  "pool_size": 100,
  "idle_pods": 80,
  "active_pods": 20,
  "preparing_pods": 0,
  "unhealthy_pods": 0,
  "pod_details": [
    {
      "pod_id": "agent-pod-1",
      "status": "idle",
      "last_heartbeat": "2026-04-16T10:00:00Z"
    }
  ],
  "redis_ok": true,
  "version": "0.1.0"
}
```

---

#### `POST /internal/route`

**主路由接口** — Feishu Bot / 其他内部调用方将用户消息路由到 Agent Pod。

**认证**: 无（K8s 内部网络）

**请求体**:
```json
{
  "user_id": "user-123",
  "message": "Hello Hermes",
  "feishu_msg_id": "msg-abc",
  "feishu_chat_id": "chat-xyz",
  "reply_channel": "feishu:responses:fbp-001",
  "estimated_tokens": 500
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `user_id` | string | 是 | 平台用户 ID |
| `message` | string | 是 | 用户消息内容 |
| `feishu_msg_id` | string | 否 | 飞书消息 ID（去重）|
| `feishu_chat_id` | string | 否 | 飞书会话 ID |
| `reply_channel` | string | 否 | Redis response stream key（BE-3 确认方案）|
| `estimated_tokens` | int | 否 | 估算 token 数（Quota 检查用）|

**路由流程**:
```
1. Acquire session lock (SET NX EX 30s)
   → 冲突：返回 409 "Session already active"
2. Quota check (Quota Service)
   → 超额：返回 quota_allowed=false
3. Hot route: GET route:{user_id}
   → 命中：验证 pod:health:{pod_id} → 返回 pod_url
   → 未命中或不健康：触发步骤 4
4. Cold start:
   a. ZPOPMIN pod:idle → 选取最老空闲 Pod
   b. POST Pod Sidecar /internal/prepare {user_id, hermes_home_path}
   c. 重试最多 6 次（间隔 0.5s，约 3s 内完成）
   d. SET route:{user_id} {pod_id} EX 1800
5. Release session lock
```

**热路由命中 — 响应** `200 OK`:
```json
{
  "success": true,
  "pod_id": "agent-pod-42",
  "pod_url": "http://agent-pod-42.default.svc.cluster.local:8642",
  "source": "hot",
  "quota_allowed": true,
  "cold_start_ms": null,
  "prepare_retries": null
}
```

**冷启动成功 — 响应** `200 OK`:
```json
{
  "success": true,
  "pod_id": "agent-pod-99",
  "pod_url": "http://agent-pod-99.default.svc.cluster.local:8642",
  "source": "cold",
  "quota_allowed": true,
  "cold_start_ms": 2500,
  "prepare_retries": 3
}
```

**无可用 Pod — 响应** `503 Service Unavailable`:
```json
{
  "detail": "No available pods (pool exhausted)"
}
```

**Session 锁冲突 — 响应** `409 Conflict`:
```json
{
  "detail": "Session already active for this user (held by pod-42)"
}
```

**配额超限 — 响应** `200 OK`:
```json
{
  "success": false,
  "quota_allowed": false,
  "quota_message": "daily_token_limit_exceeded",
  "message": "Quota exceeded"
}
```

> **reply_channel 设计**（BE-3 确认方案）：
> 若请求包含 `reply_channel`，Router 在转发请求后，将 LLM 流式响应分 chunk 写入 `feishu:responses:{fbot_instance_id}` stream。
> FBot 实例通过 XREADBLOCK 消费此 stream 并组装完整回复。

---

#### `POST /v1/chat/completions`

OpenAI `/v1/chat/completions` 代理 — 将请求透传给分配的 Agent Pod。

**认证**: `X-User-ID` header 或 JWT Bearer token

**请求头**:

| Header | 说明 |
|--------|------|
| `Authorization` | Bearer JWT（由 Auth Service 签发）|
| `X-User-ID` | 内部调用时使用（绕过 JWT 验证）|

**请求体**: OpenAI `chat/completions` 标准格式（透传）

**流式响应**: `text/event-stream`（直接从 Pod 透传）

**非流式响应**: JSON（直接从 Pod 透传）

**代理流程**:
```
1. JWT 验证（通过 Auth Service）获取 user_id
2. GET route:{user_id} → pod_id
   → 未命中：POST /internal/route 触发冷启动
3. POST {pod_url}/v1/chat/completions（透传 body）
4. 返回 Pod 响应（流式或 JSON）
```

**代理失败**: 返回 `502 Bad Gateway` 或 `504 Gateway Timeout`

---

#### `GET /v1/models`

返回 Agent Pod 支持的模型列表。

**响应** `200 OK`:
```json
{
  "object": "list",
  "data": [
    {
      "id": "hermes-default",
      "object": "model",
      "created": 1700000000,
      "owned_by": "hermes"
    }
  ]
}
```

---

#### `POST /v1/responses`

OpenAI `/v1/responses` 代理（Responses API 格式）。同 `/v1/chat/completions` 流程。

---

#### `POST /admin/pools/idle`

手动注册空闲 Pod（K8s init container 或 Pod startup probe 调用）。

**认证**: `X-Api-Key` header

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `pod_id` | string | 是 | Pod 唯一标识 |

**响应** `200 OK`:
```json
{
  "pod_id": "agent-pod-1",
  "status": "idle"
}
```

**副作用**:
- ZADD `pod:idle` score=now
- SADD `active-pods` pod_id（预注册，避免冷启动竞争）

---

#### `DELETE /admin/routes/{user_id}`

强制删除用户路由并释放 Pod（管理员操作）。

**认证**: `X-Api-Key` header

**响应** `200 OK`:
```json
{
  "user_id": "user-123",
  "released_pod": "agent-pod-42"
}
```

---

#### `GET /debug/routes`

调试接口 — 列出所有活跃路由和空闲 Pod。

**认证**: `X-Api-Key` header

**响应** `200 OK`:
```json
{
  "active_routes": {
    "user-123": "agent-pod-42",
    "user-456": "agent-pod-99"
  },
  "idle_pods": ["agent-pod-1", "agent-pod-2"],
  "pool_stats": {
    "total_active": 2,
    "total_idle": 2
  }
}
```

---

## 项目结构

```
services/router/
├── pyproject.toml
├── requirements.txt
├── Dockerfile
├── .env.example
├── router_service/
│   ├── __init__.py
│   ├── main.py           # FastAPI app + 所有路由
│   ├── config.py         # Pydantic Settings（30+ 配置项）
│   ├── schemas.py        # 所有请求/响应 Pydantic 模型
│   ├── redis_client.py   # Redis 连接池 + 所有路由表操作
│   ├── scheduler.py      # 热冷调度逻辑 + 背景任务
│   ├── routers/
│   │   └── __init__.py
│   └── tests/
│       ├── __init__.py
│       └── test_agent_router.py  # 26 tests
└── .dockerignore
```

### 关键设计决策

| 决策 | 说明 |
|------|------|
| SET NX EX 原子锁 | BE-1 确认：避免 GET+SET 并发竞争（替代原非原子方案）|
| ZPOPMIN idle pool | 从 ZSET 中原子弹出最老空闲 Pod |
| socket_timeout=2s | Redis 连接 2s 超时，避免挂起；所有操作 graceful degradation |
| reply_channel | BE-3 确认：Router 写 response stream，FBot 读自己专属 stream |
| 冷启动重试 6 次 | 间隔 0.5s，约 3s 内完成prepare（满足 <3s SLA）|
| 背景 idle recycler | 每 60s 检测过期路由，调用 Pod /internal/release 后归还 idle pool |
| Skills 热更新分批 | batch_size=20，间隔 5s，避免 Pod Pool 瞬时耗尽 |

---



**版本**: v0.1.0
**日期**: 2026-04-16
**服务**: Quota Service (`services/quota-service/`)
**端口**: 8003 (开发环境)
**主责角色**: backend-engineer
**状态**: ✅ 已完成

### 概述

Quota Service 管理 token 用量计量和基于角色的配额检查/扣减。核心职责：
- Per-user 每日 token/request 配额检查（Redis 热计数 + PostgreSQL 持久化）
- LiteLLM callback 接收 token 统计
- 角色级配额配置（user / power_user / admin）
- Admin 用量查询和管理

### 基础信息

| 项目 | 值 |
|------|-----|
| Base URL | `http://{host}:8003` |
| Content-Type | `application/json` |
| 认证 | Admin API: `X-Admin-Key` header |
| 数据库 | PostgreSQL (`hermes_quota` DB) |
| 热计数 | Redis（`quota:daily:{user_id}:{date}` HASH）|

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `QUOTA_PORT` | `8003` | 服务端口 |
| `QUOTA_DEBUG` | `false` | 调试模式 |
| `QUOTA_POSTGRES_HOST` | `localhost` | PostgreSQL 主机 |
| `QUOTA_POSTGRES_PORT` | `5432` | PostgreSQL 端口 |
| `QUOTA_POSTGRES_USER` | `hermes` | PostgreSQL 用户 |
| `QUOTA_POSTGRES_PASSWORD` | `hermes` | PostgreSQL 密码 |
| `QUOTA_POSTGRES_DB` | `hermes_quota` | 数据库名 |
| `QUOTA_REDIS_HOST` | `localhost` | Redis 主机 |
| `QUOTA_REDIS_PORT` | `6379` | Redis 端口 |
| `QUOTA_ADMIN_API_KEY` | `dev-admin-key-change-in-prod` | Admin API 密钥 |
| `QUOTA_AUTH_SERVICE_URL` | `http://localhost:8001` | Auth Service 地址 |
| `QUOTA_DEFAULT_QUOTA_USER` | `100000` | user 角色每日 token 限额 |
| `QUOTA_DEFAULT_QUOTA_POWER_USER` | `500000` | power_user 角色每日 token 限额 |
| `QUOTA_DEFAULT_QUOTA_ADMIN` | `-1` | admin 角色（-1 = 无限制）|

### 配额设计（来自 context.md）

| 角色 | 每日 token 限额 | 每日 request 限额 |
|------|-----------------|-------------------|
| `user` | 100,000 | 500 |
| `power_user` | 500,000 | — |
| `admin` | 无限制（-1）| 无限制（-1）|

**配额耗尽时**：Router 层返回 HTTP 429，响应体包含当前使用量。

### 接口清单

#### `GET /health`

全量健康检查（DB + Redis）。

**认证**: 无

**响应** `200 OK`:
```json
{
  "db_ok": true,
  "redis_ok": true,
  "version": "0.1.0"
}
```

#### `GET /internal/health`

轻量级内部健康检查（无 DB/Redis 调用）。

**响应** `200 OK`:
```json
{
  "ok": true,
  "service": "quota-service"
}
```

---

### Quota — 配额端点

#### `GET /quota/check`

Pre-request 配额检查。在 Agent Router 转发 LLM 请求前调用。

**认证**: 无（内部网络）

**查询参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `user_id` | UUID | 是 | 用户 ID |
| `estimated_tokens` | int | 否 | 估算 token 消耗（默认 0）|
| `model` | string | 否 | 目标 LLM 模型 |

**响应** `200 OK`:
```json
{
  "allowed": true,
  "result": "allowed",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "role": "user",
  "quota_group": "user",
  "daily_limit": 100000,
  "used_tokens": 30000,
  "remaining_tokens": 70000,
  "daily_request_limit": 500,
  "used_requests": 15,
  "remaining_requests": 485,
  "reset_at": "2026-04-16T23:59:59+00:00"
}
```

**`result` 枚举值**:

| 值 | 说明 |
|----|------|
| `allowed` | 配额充足，可以继续 |
| `denied` | 配额不足，应返回 429 |
| `unlimited` | admin 角色，无限制 |

---

#### `POST /quota/consume`

记录 token 消耗。在 LLM 调用完成后由 Agent Router 调用。

**认证**: 无（内部网络）

**请求体**:
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "input_tokens": 500,
  "output_tokens": 300,
  "model": "gpt-4",
  "metadata": {"call_type": "chat.completion"}
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `user_id` | UUID | 是 | 用户 ID |
| `input_tokens` | int | 是 | 输入 token 数 |
| `output_tokens` | int | 是 | 输出 token 数 |
| `model` | string | 否 | LLM 模型名 |
| `metadata` | object | 否 | 任意 key-value 元数据 |

**响应** `200 OK`:
```json
{
  "success": true,
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "tokens_consumed": 800,
  "input_tokens": 500,
  "output_tokens": 300,
  "total_daily_tokens": 30800,
  "request_count": 16,
  "daily_limit": 100000,
  "remaining_tokens": 69200
}
```

**副作用**:
1. Redis HINCRBY `quota:daily:{user_id}:{date}` tokens + requests
2. PostgreSQL `usage_records` 表 upsert 当日记录

---

#### `POST /quota/llm-callback`

LiteLLM proxy 用量回调端点。LiteLLM 可配置在每次 LLM 调用后 POST 用量数据。

**认证**: 无（内部网络）

**LiteLLM 配置示例**:
```yaml
litellm_settings:
  json_logs: true
  success_callback: ["lite_debugger"]
  failure_callback: []

general_settings:
  max_parallel_requests: 1000

router_settings:
  num_retries: 2
  retry_after: 2
```

**请求体**（LiteLLM 格式）:
```json
{
  "user": "550e8400-e29b-41d4-a716-446655440000",
  "model": "gpt-4",
  "total_cost": 0.02,
  "usage": {
    "prompt_tokens": 100,
    "completion_tokens": 50,
    "total_tokens": 150
  },
  "call_type": "chat.completion",
  "start_time": "2026-04-16T10:00:00Z",
  "end_time": "2026-04-16T10:00:02Z",
  "metadata": {}
}
```

| 字段 | 来源 | 说明 |
|------|------|------|
| `user` | LiteLLM call `user` 参数 | 平台 user_id（UUID）|
| `model` | 调用模型 | 模型名 |
| `usage.prompt_tokens` | 模型返回 | 输入 token |
| `usage.completion_tokens` | 模型返回 | 输出 token |
| `usage.total_tokens` | 模型返回 | 总 token |
| `call_type` | LiteLLM | 调用类型 |

**响应** `200 OK`:
```json
{
  "status": "recorded",
  "tokens": 150
}
```

> **幂等设计**：user_id 解析失败时返回 `{"status": "ignored"}`（不阻断 LiteLLM 重试链路）

---

#### `GET /quota/status`

查询用户当前配额状态。

**认证**: 无（内部网络）

**查询参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `user_id` | UUID | 是 | 用户 ID |

**响应** `200 OK`:
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "role": "user",
  "quota_group": "user",
  "daily_limit": 100000,
  "is_unlimited": false,
  "used_tokens": 30800,
  "remaining_tokens": 69200,
  "used_requests": 16,
  "remaining_requests": 484,
  "daily_request_limit": 500,
  "record_date": "2026-04-16",
  "reset_at": "2026-04-16T23:59:59+00:00",
  "model_allowlist": null
}
```

---

### Admin — 配额管理端点

#### `GET /admin/quota/configs`

列出所有配额配置。

**认证**: `X-Admin-Key` header

**响应** `200 OK`:
```json
[
  {
    "id": "uuid",
    "quota_group": "user",
    "daily_token_limit": 100000,
    "daily_request_limit": 500,
    "model_allowlist": null,
    "create_time": "2026-04-16T09:00:00Z",
    "update_time": "2026-04-16T10:00:00Z"
  }
]
```

---

#### `PUT /admin/quota/configs/{quota_group}`

更新指定角色的配额配置。

**认证**: `X-Admin-Key` header

**请求体**:
```json
{
  "daily_token_limit": 200000,
  "daily_request_limit": 1000,
  "model_allowlist": ["gpt-4", "gpt-4o"]
}
```

**响应** `200 OK`: 返回更新后的 `QuotaConfigResponse`

**错误**:

| 状态码 | 说明 |
|--------|------|
| `401 Unauthorized` | 无效或缺失 `X-Admin-Key` |
| `404 Not Found` | 配额组不存在 |

---

#### `GET /admin/quota/usage`

查询用量记录（支持按用户/时间范围过滤）。

**认证**: `X-Admin-Key` header

**查询参数**:

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `user_id` | UUID | — | 按用户过滤 |
| `from_date` | date | 今天 | 开始日期（YYYY-MM-DD）|
| `to_date` | date | 今天 | 结束日期（YYYY-MM-DD）|
| `limit` | int | 100 | 返回条数（最大 1000）|

**响应** `200 OK`:
```json
[
  {
    "user_id": "uuid",
    "username": null,
    "role": "user",
    "quota_group": "user",
    "record_date": "2026-04-16",
    "used_tokens": 30800,
    "used_requests": 16,
    "daily_limit": 100000,
    "usage_percentage": 30.8
  }
]
```

---

#### `GET /admin/quota/dashboard`

聚合用量仪表板。

**认证**: `X-Admin-Key` header

**响应** `200 OK`:
```json
{
  "total_users": 42,
  "total_tokens_today": 1540000,
  "total_requests_today": 820,
  "users_at_limit": 2,
  "top_users": []
}
```

---

## 数据模型

### PostgreSQL: `quota_configs`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | 主键 |
| `quota_group` | VARCHAR(64) | 配额组名（`user` / `power_user` / `admin`）|
| `daily_token_limit` | BIGINT | 每日 token 限额（-1 = 无限制）|
| `daily_request_limit` | INT | 每日 request 限额 |
| `model_allowlist` | TEXT[] | 允许使用的模型列表 |
| `create_time` | TIMESTAMPTZ | 创建时间 |
| `update_time` | TIMESTAMPTZ | 更新时间 |

**索引**: `UNIQUE` on `quota_group`

### PostgreSQL: `usage_records`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BIGSERIAL | 主键 |
| `user_id` | UUID | 用户 ID（索引）|
| `record_date` | DATE | 记录日期 |
| `model` | VARCHAR(128) | LLM 模型 |
| `input_tokens` | BIGINT | 输入 token 累计 |
| `output_tokens` | BIGINT | 输出 token 累计 |
| `total_tokens` | BIGINT | 总 token |
| `request_count` | INT | 请求次数 |
| `create_time` | TIMESTAMPTZ | 创建时间 |

**索引**: `INDEX` on `(user_id, record_date)`, `INDEX` on `record_date`

### Redis 数据结构

| Key | Type | TTL | 说明 |
|-----|------|-----|------|
| `quota:daily:{user_id}:{YYYY-MM-DD}` | HASH | 90000s (~25h) | 当日用量 `{tokens: N, requests: N}` |

---

## 错误响应格式

所有错误响应遵循统一格式：

```json
{
  "detail": "错误描述信息"
}
```

| HTTP 状态码 | 含义 |
|-----------|------|
| `400 Bad Request` | 请求格式错误 |
| `401 Unauthorized` | 认证失败（Admin API）|
| `404 Not Found` | 资源不存在 |
| `429 Too Many Requests` | 配额耗尽（由 Router 层返回）|
| `500 Internal Server Error` | 服务端错误 |

---

## 技术实现

| 项目 | 实现 |
|------|------|
| 框架 | FastAPI 0.115+ |
| 数据库 | SQLAlchemy 2.0 + asyncpg（异步）|
| ORM | PostgreSQL UUID primary key |
| Redis | `redis.asyncio`（热计数器）|
| 配置 | `pydantic-settings` + 环境变量 |
| 测试 | pytest + pytest-asyncio（27 个测试，全部通过）|

### 目录结构

```
services/quota-service/
├── pyproject.toml
├── requirements.txt
├── Dockerfile
├── docker-compose.yaml
├── .env.example
├── quota_service/
│   ├── __init__.py
│   ├── main.py              # FastAPI app + lifespan
│   ├── config.py           # Pydantic Settings
│   ├── schemas.py          # Pydantic request/response models
│   ├── models.py           # SQLAlchemy ORM models
│   ├── database.py         # Async session management
│   ├── redis_client.py     # Redis hot counter operations
│   ├── service.py          # Business logic layer
│   ├── auth_client.py      # Auth Service HTTP client
│   └── routers/
│       ├── __init__.py
│       ├── quota.py         # GET /quota/*, POST /quota/*
│       └── admin.py        # GET/PUT /admin/quota/*
└── tests/
    ├── __init__.py
    └── test_quota_service.py  # 27 tests
```

---

## 关键设计决策

| 决策 | 说明 |
|------|------|
| Redis + PostgreSQL 双写 | Redis 热计数（亚毫秒），PG 持久化（每日归档）|
| -1 = unlimited | 配额 limit 为负数时视为无限制 |
| 配额检查不返回 429 | 检查接口只返回状态，Router 层决定返回 429 |
| LiteLLM callback 幂等 | user_id 解析失败返回 `ignored`，不阻断 LiteLLM 重试 |
| Redis key TTL 90000s | 覆盖时区和 UTC 边界（25 小时略超 1 天）|

---

---

*backend-engineer: AI Lab User1-1*
*状态: ✅ 完成*
*2026-04-16（Skills Registry / Feishu Bot / Quota Service / Agent Router）*
