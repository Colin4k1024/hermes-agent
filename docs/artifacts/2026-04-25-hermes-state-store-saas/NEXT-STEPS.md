# Hermes StateStore SaaS 下一步实施计划

日期: 2026-04-25
状态: in-progress
前置提交: `16325bab feat: add remote state store for stateless SaaS runtime`

## 目标

把当前已经落地的 StateStore 基础能力继续推进到企业内部可验证、可部署、可审计的 SaaS 化助手平台。下一阶段重点不是继续扩大范围，而是补齐生产化闭环：数据库迁移、真实依赖集成、安全审计、secret 引用注入、skills/cache 远程化、端到端验证。

## 当前基线

已经完成：

- `StateStore`、`RuntimeContext`、`LocalStateStore`、`RemoteStateStore`。
- `AIAgent` 接入 `runtime_context/state_store`。
- `RemoteMemoryStore` 接入 memory tool。
- `services/state-service` 最小可用 API。
- Router stateless runtime context 转发。
- docker-compose/k8s state-service 资源。
- 目标测试 `36 passed`。

未完成：

- Postgres/Redis/MinIO 端到端容器测试。
- 脱敏日志、限流、配额。
- secret-service 引用注入。
- skills registry 和 prompt skills snapshot 远程化。
- Auth Service 真实 JWT/mTLS/service JWT 链路测试。
- 飞书/Web/API 到 Agent/State Service 的端到端验证。

## Phase 1: State Service 生产化

状态: partially-completed

### 目标

让 `services/state-service` 从代码级最小实现变成可迁移、可回滚、可观测、可在 Postgres 上长期运行的服务。

### 任务

- 增加 Alembic：
  - 初始化 `services/state-service/alembic.ini`。
  - 增加 `services/state-service/alembic/env.py`。
  - 生成首个 migration，覆盖 config/session/message/memory/cache 表。
  - migration 必须包含 `tenant_id/user_id/session_id` 相关索引。
- 增加数据库约束：
  - `sessions`: `tenant_id + user_id + id` 查询索引。
  - `messages`: `tenant_id + user_id + session_id + timestamp + id` 顺序索引。
  - `memory`: `tenant_id + user_id + namespace + key` 唯一约束。
  - `cache_metadata`: `tenant_id + user_id + cache_key` 唯一约束。
- 增加健康检查深度：
  - `/health` 返回数据库可用性。
  - 增加 `/ready` 检查 migration 版本。
- 增加 State Service 配置文档：
  - `DATABASE_URL`
  - `REDIS_URL`
  - `STATE_INTERNAL_API_KEY`
  - `STATE_SERVICE_CORS_ALLOW_ORIGINS`

### 验收标准

- 空库可通过 Alembic 创建完整 schema。
- 重复执行 migration 不破坏数据。
- Postgres 环境下 State Service 可启动并通过 `/health`。
- SQLite 测试继续通过。

### 2026-04-25 执行结果

已完成：

- 新增 Alembic 配置和首个 migration：`20260425_0001`。
- State Service 容器启动前执行 `alembic upgrade head`。
- 新增 `/ready`，同时检查数据库连通性和 Alembic revision。
- 新增 `state_audit_events` 表和审计写入 hooks。
- 增加 `STATE_AUTO_CREATE_SCHEMA`、`STATE_EXPECTED_MIGRATION_REVISION`、`STATE_OBJECT_STORAGE_ENDPOINT`、`STATE_OBJECT_STORAGE_BUCKET` 配置。
- 增加 `services/state-service/README.md` 记录运行配置、迁移和探针。
- docker-compose 增加 MinIO，并让 state-service 依赖 Postgres/Redis/MinIO。
- K8s readiness probe 改为 `/ready`。

测试结果：

```text
services/router/router_service/tests/test_agent_router.py
services/router/router_service/tests/test_stateless_runtime_schemas.py
services/state-service/tests/test_state_service.py
services/state-service/tests/test_state_service_http.py
tests/test_state_store.py

36 passed
```

仍需完成：

- 使用真实 docker-compose 启动 Postgres/Redis/MinIO/State Service 的容器级测试。
- 对生产 Postgres 执行 migration rollback/upgrade 演练。

### 测试

```bash
PYTHONPATH=services/state-service \
/tmp/hermes-state-test/bin/python -m pytest -o addopts='' \
services/state-service/tests/test_state_service.py -q
```

新增：

- migration smoke test。
- Postgres docker-compose integration test。

## Phase 2: 真实依赖集成测试

### 目标

验证 Router、Agent Runtime、State Service 在真实 Postgres/Redis/Object Storage 依赖下可协同工作。

### 任务

- 更新 docker-compose：
  - 增加 Postgres service。
  - 增加 Redis service。
  - 增加 MinIO service。
  - State Service 使用 Postgres。
  - Router 使用 Redis 和 State Service。
- 增加 integration test profile：
  - `docker compose -f deploy/docker-compose/docker-compose.yml up -d postgres redis minio state-service router`
  - 自动初始化数据库 migration。
- 增加 State Service HTTP API 测试：
  - config upsert/effective。
  - session create/list/get/search/end/reopen。
  - memory upsert/list/delete。
  - cache metadata put/get。
- 增加 RemoteStateStore client 测试：
  - 使用真实 HTTP State Service。
  - 验证 `tenant_id/user_id/session_id` header 传递。
  - 验证跨用户读取被拒绝。

### 验收标准

- docker-compose 一键启动后，State Service 和 Router 健康。
- RemoteStateStore 对真实 State Service 的核心读写通过。
- 两个用户并发写入不同 session/memory/cache，不发生串读。

### 测试

新增命令建议：

```bash
PYTHONPATH=.:services/router:services/state-service \
/tmp/hermes-state-test/bin/python -m pytest -o addopts='' \
tests/integration/test_remote_state_store_http.py \
services/state-service/tests/test_state_service_http.py -q
```

## Phase 3: 安全边界和审计

### 目标

满足企业内部助手平台的最小安全要求：可信身份、边界校验、审计可追踪、日志不泄露敏感信息。

### 任务

- Auth 边界：
  - Router 外部入口不信任公网 `X-User-ID`。
  - 增加 Auth Service JWT 校验测试。
  - 内部服务间调用使用短期 service JWT 或 mTLS 预留接口。
- State Service 授权：
  - 所有 endpoint 统一校验 `tenant_id/user_id/session_id`。
  - 增加伪造 tenant/user/session header 的拒绝测试。
- 审计事件：
  - 新增 `audit_events` 表。
  - 记录 config read/write。
  - 记录 session read/write/search。
  - 记录 memory write/delete。
  - 记录 cache metadata access。
  - 记录 secret reference usage。
  - 记录 admin 操作。
- 日志脱敏：
  - 明文 secret 不进入普通日志。
  - 完整 prompt 不进入普通日志。
  - 大文件工具输出只记录 hash/size/resource id。
- 限流和配额：
  - 增加用户/角色/部门 quota 配置模型。
  - Router 在调度前执行 quota check。
  - 失败默认拒绝或降级只读助手能力。

### 验收标准

- 伪造 `X-User-ID`、`X-Tenant-ID`、`X-Session-ID` 的访问被拒绝或只能访问授权资源。
- 审计表中可查到关键状态访问事件。
- 测试日志中不出现 API key、refresh token、完整 secret 文件。
- quota 超限时不会启动 Agent Pod。

### 测试

新增：

- `services/state-service/tests/test_security_boundaries.py`
- `services/router/router_service/tests/test_auth_boundary.py`
- `services/state-service/tests/test_audit_events.py`
- `tests/security/test_log_redaction.py`

## Phase 4: Secret Service 和工具执行隔离

### 目标

移除企业 runtime 对本地 `.env`、MCP token 文件、OAuth token 文件的长期依赖，使凭据按请求最小权限临时注入。

### 任务

- 定义 secret reference 模型：
  - provider API key reference。
  - MCP server credential reference。
  - OAuth token reference。
  - tool-specific credential reference。
- State Service 只保存 secret reference，不保存明文 secret。
- Router 或 Agent Runtime 在请求级别向 secret-service 换取短期凭据。
- 工具执行环境：
  - terminal/file/docker backend 不挂载个人 `~/.hermes`。
  - 每次请求或每个 session 使用独立 sandbox workspace。
  - sandbox 只挂载临时 workspace 和只读企业公共资源。
- 增加凭据注入审计：
  - 谁在什么时候为哪个 request/session 使用了哪个 secret reference。
  - 不记录明文 secret。

### 验收标准

- 企业 remote mode 下 Agent Pod 不需要用户 `.env` 文件。
- 工具执行容器无法读取其他用户状态目录。
- secret reference 使用有审计记录。
- 日志和异常中不出现明文 secret。

### 测试

新增：

- secret reference resolve mock 测试。
- terminal sandbox 隔离测试。
- MCP config 临时注入测试。
- secret redaction regression test。

## Phase 5: Cache 和 Skills 远程化

### 目标

把 prompt skills snapshot、document/image/audio/browser cache、用户自定义 skills 从本地目录迁移到远程状态层和对象存储。

### 任务

- Cache：
  - 定义 object storage key 规范。
  - key 前缀必须包含 `tenant_id/user_id/session_id`。
  - State Service 保存 metadata，内容进入 S3/MinIO/NAS。
  - 增加 cache TTL 和清理策略。
- Skills：
  - 企业公共 skills 放入 `skills-registry`。
  - 用户自定义 skills 放入 State Service 或 registry user namespace。
  - Agent 启动不再同步用户 skills 到本地目录。
  - 构建 prompt 时按 runtime context 拉取 skills manifest。
- Prompt snapshot：
  - prompt skills snapshot 远程化。
  - snapshot 内容使用 content hash 去重。
  - 记录 snapshot resource id，不在普通日志记录完整内容。

### 验收标准

- Agent Pod 重启后缓存 metadata 和 skills 状态可恢复。
- 不同用户无法读取彼此 cache object。
- 企业公共 skills 和用户自定义 skills 可以同时出现在 prompt manifest。
- prompt caching 不因中途热更新 skills 破坏历史上下文。

### 测试

新增：

- cache object key 隔离测试。
- skills manifest remote fetch 测试。
- prompt snapshot hash 去重测试。
- Agent Pod 重启恢复测试。

## Phase 6: 端到端链路和发布门禁

### 目标

证明平台形态成立：同一个用户连续请求可落在不同 Agent Pod 上，但状态连续；不同用户并发请求严格隔离。

### 任务

- 构建 e2e 环境：
  - Auth Service mock 或真实 Keycloak。
  - Router。
  - Agent Pod 至少 2 个。
  - State Service。
  - Postgres/Redis/MinIO。
- E2E 场景：
  - 同一用户同一 session 多轮对话落到不同 Pod。
  - 同一用户不同 session 可并发落到不同 Pod。
  - 两个用户并发请求不会串读配置、记忆、缓存、会话。
  - Agent Pod 重启后 session 恢复。
  - 飞书入口到 Router、Agent、State Service 全链路。
  - OpenAI-compatible API 到 Router、Agent、State Service 全链路。
- 发布门禁：
  - 单测通过。
  - 集成测试通过。
  - 安全测试通过。
  - K8s manifests dry-run 通过。
  - 日志脱敏扫描通过。

### 验收标准

- E2E 测试能证明无 per-user Pod 绑定。
- Pod 扩缩容不会造成用户状态丢失。
- 无 per-user PVC。
- 失败路径默认拒绝或降级，不泄露其他用户数据。

### 测试

新增：

- `tests/e2e/test_stateless_agent_runtime.py`
- `tests/e2e/test_multi_user_isolation.py`
- `tests/e2e/test_pod_restart_recovery.py`
- `tests/e2e/test_feishu_to_state_service_flow.py`

## 依赖和决策

| 决策点 | 推荐 | 原因 |
|--------|------|------|
| State DB | PostgreSQL | 权威状态源，支持事务和审计查询 |
| Hot Cache | Redis | session lock、route、短期 cache |
| Object Store | MinIO/S3/NAS | 大文件 cache 和附件 |
| Migration | Alembic | FastAPI + SQLAlchemy 标准路径 |
| Auth | Auth Service + JWT/OIDC | 禁止直接信任外部 header |
| Service Auth | service JWT 或 mTLS | 内部 header 只做上下文，不做认证来源 |

## 执行顺序

建议按以下顺序推进：

1. Phase 1: State Service 生产化。
2. Phase 2: 真实依赖集成测试。
3. Phase 3: 安全边界和审计。
4. Phase 4: Secret Service 和工具执行隔离。
5. Phase 5: Cache 和 Skills 远程化。
6. Phase 6: 端到端链路和发布门禁。

不要在 Phase 1/2 未稳定前大规模改 tools。先让状态服务和远程状态访问成为可靠底座，再迁移更多本地状态依赖。

## 工作拆分建议

### Backend owner

- Alembic migrations。
- State Service API hardening。
- audit events。
- quota models。

### Runtime owner

- AIAgent 本地状态依赖扫描。
- tools sandbox 隔离。
- secret reference 注入。
- cache/skills 远程化接入。

### Platform owner

- docker-compose integration profile。
- K8s manifests。
- HPA/no per-user PVC 验证。
- service JWT/mTLS 接入。

### QA/Security owner

- multi-user isolation tests。
- forged header tests。
- log redaction tests。
- pod restart recovery tests。

## 下一次开发起点

优先从 Phase 1 开始：

1. 在 `services/state-service` 加 Alembic。
2. 给现有 SQLAlchemy models 生成首个 migration。
3. 增加 migration smoke test。
4. 把 docker-compose 的 state-service 切到 Postgres。
5. 跑通 Postgres 上的 `test_state_service` 等价测试。
