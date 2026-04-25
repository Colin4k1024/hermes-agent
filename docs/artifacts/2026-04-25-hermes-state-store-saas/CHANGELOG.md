# Hermes Agent StateStore SaaS 改造记录

日期: 2026-04-25

## 背景

本轮目标是把 Hermes Agent 从依赖本地 `~/.hermes` 的个人实例，推进到企业内部可共享的无状态 Agent Runtime 形态。Agent Pod 不再绑定单个用户，用户配置、记忆、会话、缓存元数据等个人状态通过远程 State Service 访问，并按 `tenant_id + user_id + session_id` 隔离。

## 已完成能力

### 1. StateStore 抽象层

新增 `agent/state_store.py`：

- `RuntimeContext`: 承载 `tenant_id`、`user_id`、`session_id`、`request_id`、角色、配额组、允许工具、状态服务地址和 token。
- `StateStore`: 聚合配置、会话、记忆、缓存四类状态接口。
- `SessionStore`、`ConfigStore`、`MemoryStoreBackend`、`CacheStore`: 远程化状态的协议接口。
- `LocalStateStore`: 包装现有本地 `SessionDB`，保证 CLI 本地模式不破。
- `RemoteStateStore`: 同步 HTTP client，用于 Agent Runtime 访问 State Service。

### 2. AIAgent 接入远程状态

修改 `run_agent.py`：

- `AIAgent.__init__` 新增 `runtime_context` 和 `state_store` 参数。
- 支持通过 `HERMES_STATE_MODE=remote` 自动构造 `RemoteStateStore`。
- 支持通过 `RuntimeContext` 注入 `tenant_id/user_id/session_id/request_id`。
- session persistence 优先使用 `state_store.sessions`。
- config 加载优先使用 `state_store.config.get_effective_config()`。
- memory 加载在远程模式下使用 `RemoteMemoryStore`。
- 传递相同 `runtime_context/state_store` 给 background review agent。
- 当传入远程 `state_store` 时，会话日志目录使用临时目录，不再默认写入 `HERMES_HOME/sessions`。

### 3. Memory Tool 远程适配

修改 `tools/memory_tool.py`：

- 新增 `RemoteMemoryStore`，兼容现有 `MemoryStore` 调用方式。
- 支持 `list_memory`、`upsert_memory`、`delete_memory` 远程读写。
- 保留现有 memory 威胁检测、长度限制、替换和删除语义。
- 使用 SHA256 生成稳定 memory key，避免依赖本地文件行号。

### 4. 新增 State Service

新增 `services/state-service/`：

- FastAPI 服务入口: `state_service/main.py`
- 配置: `state_service/config.py`
- 数据库生命周期: `state_service/database.py`
- SQLAlchemy models: `state_service/models.py`
- Pydantic schemas: `state_service/schemas.py`
- 内部认证和上下文提取: `state_service/security.py`
- 容器定义: `Dockerfile`
- Python 包定义: `pyproject.toml`

提供 API：

- `GET /health`
- `GET /state/config/effective`
- `PUT /state/config`
- `POST /state/sessions`
- `GET /state/sessions`
- `GET /state/sessions/{session_id}`
- `PATCH /state/sessions/{session_id}`
- `POST /state/sessions/{session_id}/messages`
- `GET /state/sessions/{session_id}/messages`
- `GET /state/messages/search`
- `POST /state/sessions/{session_id}/usage`
- `POST /state/sessions/{session_id}/end`
- `POST /state/sessions/{session_id}/reopen`
- `GET /state/memory`
- `PUT /state/memory/{namespace}/{key}`
- `DELETE /state/memory/{namespace}/{key}`
- `PUT /state/cache/{cache_key:path}`
- `GET /state/cache/{cache_key:path}`

安全边界：

- 所有状态 API 要求 `Authorization: Bearer <STATE_INTERNAL_API_KEY>`。
- 每次请求必须携带 `X-User-ID`，可携带 `X-Tenant-ID`、`X-Session-ID`、`X-Request-ID`。
- 所有会话、记忆、缓存、配置访问都按 `tenant_id + user_id` 过滤。
- 禁止用户创建或读取其他用户 session。

### 5. Router 无状态调度接入

修改 `services/router/router_service/`：

- `config.py`
  - 新增 `stateless_runtime`
  - 新增 `state_service_url`
  - 新增 `state_service_token`
- `schemas.py`
  - 新增 `RuntimeContext`
  - `InternalRouteRequest` 增加 `tenant_id/session_id/request_id/runtime_context`
  - `InternalPrepareRequest` 增加 `runtime_context/stateless`
- `scheduler.py`
  - route subject 改为优先使用 `session_id`，否则使用 `user_id`
  - stateless runtime 下使用 `/tmp/hermes-runtime/{route_subject}` 作为临时 runtime home
  - cold start/prepare 请求传递 runtime context
  - stateless 模式下注入 `HERMES_STATE_MODE=remote`、`HERMES_STATE_SERVICE_URL`、`HERMES_STATE_SERVICE_TOKEN`
- `main.py`
  - `/v1/chat/completions` 支持 `X-Tenant-ID`、`X-Session-ID`、`X-Request-ID`
  - 当存在 `Authorization` 时，通过 Auth Service `/users/me` 获取可信用户身份，不信任外部 `X-User-ID`
  - 转发给 Agent Pod 时携带 runtime context 相关 header

### 6. 部署配置

修改 `deploy/docker-compose/docker-compose.yml`：

- 新增 `state-service` 服务。
- router 增加 state-service 相关环境变量。
- router `depends_on` 增加 state-service。
- 修正 router build context。

新增 Kubernetes 资源：

- `k8s/configmaps/state-service-cm.yaml`
- `k8s/deployments/state-service-deploy.yaml`
- `k8s/services/state-service-svc.yaml`

修改 Kubernetes 资源：

- `k8s/kustomization.yaml`: 纳入 state-service 资源。
- `k8s/configmaps/router-service-cm.yaml`: 增加 stateless runtime 和 state-service URL。
- `k8s/deployments/router-service-deploy.yaml`: 注入 `ROUTER_STATE_SERVICE_TOKEN`。
- `k8s/secrets/hermes-agent-secret.yaml`: 增加 `INTERNAL_API_KEY`。

### 7. 测试

新增和更新测试：

- `tests/test_state_store.py`
  - `RuntimeContext.from_mapping`
  - `RemoteMemoryStore` 行为
- `services/state-service/tests/test_state_service.py`
  - config/session/message/search/usage/memory/cache 的核心 flow
  - 使用 SQLite + aiosqlite 验证 schema 和 endpoint 逻辑
- `services/router/router_service/tests/test_stateless_runtime_schemas.py`
  - router runtime context schema
  - stateless prepare request schema
- `services/router/router_service/tests/test_agent_router.py`
  - 修复 Redis session lock 测试，使其对齐当前 Lua `register_script` 原子锁实现

## 验证记录

使用 conda 测试环境：

```bash
/tmp/hermes-state-test/bin/python
```

已安装目标依赖：

```text
pytest
pydantic
pydantic-settings
fastapi
sqlalchemy
asyncpg
redis
httpx
pyyaml
uvicorn
aiosqlite
```

目标测试：

```bash
PYTHONPATH=.:services/router:services/state-service \
/tmp/hermes-state-test/bin/python -m pytest -o addopts='' \
services/router/router_service/tests/test_agent_router.py \
tests/test_state_store.py \
services/router/router_service/tests/test_stateless_runtime_schemas.py \
services/state-service/tests/test_state_service.py -q
```

结果：

```text
32 passed, 1 warning
```

语法检查：

```bash
PYTHONPATH=.:services/router:services/state-service \
/tmp/hermes-state-test/bin/python -m py_compile \
agent/state_store.py \
run_agent.py \
tools/memory_tool.py \
services/state-service/state_service/main.py \
services/state-service/state_service/models.py \
services/state-service/state_service/schemas.py \
services/state-service/state_service/security.py \
services/state-service/state_service/database.py \
services/router/router_service/main.py \
services/router/router_service/scheduler.py \
services/router/router_service/schemas.py \
services/router/router_service/config.py \
tests/test_state_store.py \
services/router/router_service/tests/test_stateless_runtime_schemas.py \
services/state-service/tests/test_state_service.py \
services/router/router_service/tests/test_agent_router.py
```

结果：

```text
passed
```

Diff 检查：

```bash
git diff --check -- \
agent/state_store.py \
run_agent.py \
tools/memory_tool.py \
services/state-service \
services/router/router_service \
k8s \
deploy/docker-compose \
tests/test_state_store.py
```

结果：

```text
passed
```

## 重要兼容性修复

- Pydantic v2 中 `model_config` 是保留字段，State Service schema 使用 `model_config_data` 并通过 alias 暴露为 `model_config`。
- SQLite 不会对 `BIGINT PRIMARY KEY` 做隐式自增，SQLAlchemy model 使用 `BigInteger().with_variant(Integer, "sqlite")` 保持 Postgres BigInteger，同时支持 SQLite 测试。
- 直接调用 FastAPI endpoint 函数时，默认参数仍可能是 `Query(...)` 对象，State Service 对 `list_sessions`、`search_messages`、`list_memory` 做了直接调用兼容。

## 当前边界

- 远程状态层已经具备最小可用能力，但尚未实现完整审计日志、限流、配额、secret-service 最小权限注入。
- cache 当前保存 metadata，真实对象内容应接入 S3/MinIO/NAS 对象存储。
- skills registry 尚未完整远程化，本轮主要完成 StateStore 和 runtime context 基础。
- `LocalStateStore` 保持 CLI 本地兼容，企业 runtime 默认应使用 remote mode。
- 工作区中存在非本轮修改的脏文件或未跟踪目录，例如 `AGENTS.md`、`mcp_serve.py`、`uv.lock`、`_deps/`、`docs/research/`，本轮没有回滚这些内容。

## 后续建议

1. 为 State Service 增加 Alembic migrations。
2. 接入 Postgres/Redis/MinIO 的 docker-compose 集成测试。
3. 将 MCP/OAuth/token 文件迁移到 secret-service 引用模型。
4. 将 prompt skills snapshot 和 user custom skills 接入远程 registry。
5. 为 Router Auth Service 添加真实 JWT 校验测试，禁止公网入口伪造 `X-User-ID`。
6. 增加审计事件表和脱敏日志策略测试。
