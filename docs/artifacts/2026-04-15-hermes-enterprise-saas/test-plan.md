# Test Plan — Hermes Enterprise SaaS Phase 1

**项目**: Hermes Agent 企业内部 SaaS 平台
**阶段**: Phase 1 MVP
**版本**: 1.0
**日期**: 2026-04-16
**审查角色**: QA Engineer
**状态**: Ready for Phase 2 Integration

---

## 1. 测试范围

### 1.1 功能范围（In Scope）

| 模块 | 端点/功能 | 测试覆盖 | 状态 |
|------|---------|---------|------|
| Auth Service | JWT 签发/验证、bcrypt 密码、API Token 生成/SHA-256、Schema 验证 | 6 项核心验证 | ✅ 通过 |
| Agent Router | Session Lock (SET NX EX)、热路由、冷启动、Pod Pool、Redis Streams (reply_channel)、Health | 26/26 | ✅ 通过 |
| Quota Service | Token 计数、Role 枚举、Redis pipeline、Flow 模拟、Config | 27/27 | ✅ 通过 |
| Skills Registry | YAML frontmatter 解析、path traversal 防护、FileStorage CRUD、Schema | 33/33 | ✅ 通过 |
| Feishu Bot Service | HMAC-SHA256 signature、timestamp window、event dedup (SETNX)、binding/reply card、webhook flow | 29/29 | ✅ 通过 |
| Admin Console | TypeScript build、4 页面状态覆盖、响应式、Mock API | tsc 0 错误 | ✅ 通过 |
| Docker Compose | 10 服务配置、health check、`depends_on`、profile 隔离 | config 通过 | ✅ 通过 |

**Phase 1 总计：121+ 测试用例，全部通过。**

### 1.2 非功能范围（Out of Scope）

| 项目 | 原因 | 计划 |
|------|------|------|
| 真实 OIDC / Keycloak 集成 | 外部依赖待 D1 确认 | Phase 2 |
| 真实 LLM 模型调用 | 外部依赖待 D3 确认 | Phase 2 |
| 真实飞书 App 配置 | 外部依赖待 D2 确认 | Phase 2 |
| K8s 生产部署 | 需 Phase 2 | Phase 2 |
| E2E 联调测试 | 所有模块需联调 | Phase 2 |
| 性能/压力测试 | 需真实环境 | Phase 2 |

---

## 2. 测试矩阵

### 2.1 Auth Service

| 场景 | 类型 | 前置条件 | 预期结果 |
|------|------|---------|---------|
| 正确密码登录 | Happy Path | OIDC mock enabled, 正确凭据 | JWT access + refresh token |
| 错误密码登录 | Failure Path | 错误密码 | 401 Unauthorized |
| Mock OIDC → 真实 OIDC 迁移 | Migration | OIDC_MOCK_ENABLED=false | 301 redirect to IdP |
| JWT 验证有效 token | Happy Path | 有效 JWT | payload 含 user_id/role |
| JWT 验证过期 token | Failure Path | 30min 后重测 | 401 / token expired |
| JWT 验证篡改 token | Security | 修改 payload | 验证失败返回 None |
| API Token `hms_` 前缀生成 | Happy Path | — | `hms_` + 48 字符 UUID |
| API Token SHA-256 存储 | Happy Path | token 生成 | DB 存 hash，不存明文 |
| API Token 撤销 | Happy Path | — | token.is_active=false |
| API Token Redis 缓存 | Happy Path | 首次 verify | 5min TTL cache hit |
| 未绑定飞书 union_id 查询 | Failure Path | union_id 无绑定 | 404 + "not_bound" |
| Redis 不可用时的 Token 验证 | Degraded Path | Redis 宕机 | Fallback 到 DB 直接查询 |
| 并发同一用户请求 | Concurrency | 2 并发请求 | Session lock 保护 |

### 2.2 Agent Router

| 场景 | 类型 | 前置条件 | 预期结果 |
|------|------|---------|---------|
| 热路由存在 | Happy Path | Redis 有 route:{user_id} | 直接返回 pod_id |
| 冷启动空闲 Pod | Happy Path | 无热路由，有 idle Pod | Pod prepare → cold_start_ms < 3s |
| 冷启动无空闲 Pod | Failure Path | idle pool 为空 | 409 + "pool exhausted" |
| Session Lock 获取成功 | Happy Path | 无锁冲突 | (True, pod_id) |
| Session Lock 被占用 | Failure Path | 另一请求持有锁 | (False, holder_pod_id) |
| Session Lock Redis 不可用 | Degraded Path | Redis 宕机 | fail-open: 允许请求通过 |
| Pod 不健康触发冷启动 | Recovery | 热路由存在但 Pod unhealthy | 清除路由 + 触发冷启动 |
| 配额超限拒绝 | Failure Path | 用户用量已达上限 | quota_allowed=False + 429 |
| Quota Service 不可用 | Degraded Path | Quota Service 宕机 | fail-open: 允许请求 + warn log |
| Skills 热更新广播 | Happy Path | Admin 更新 skill | 批量 SIGTERM 活跃 Pod |
| idle_recycler 回收过期路由 | Happy Path | 30min TTL 到期 | Pod 回 idle pool |
| `reply_channel` 字段透传 | Happy Path | 飞书请求带 reply_channel | 透传到 Redis Streams |
| Redis Streams 读 feishu:requests | Happy Path | Consumer group 存在 | XREADGROUP 返回消息 |

### 2.3 Quota Service

| 场景 | 类型 | 前置条件 | 预期结果 |
|------|------|---------|---------|
| 普通用户配额充足 | Happy Path | 30k/100k tokens used | allowed=True, remaining > 0 |
| 普通用户配额超限 | Failure Path | 99.5k/100k tokens used + 500 token 请求 | allowed=False, DENIED |
| Power User 配额充足 | Happy Path | 200k/500k tokens used | allowed=True, UNLIMITED 豁免 |
| Admin 无限制 | Happy Path | role=admin | allowed=True, remaining=-1 |
| 每日重置 | Recovery | 跨越 UTC 0 点 | Redis HASH 清零或新 key |
| Redis 不可用 | Degraded Path | Redis 宕机 | Fallback 读取 PostgreSQL |
| Auth Service 不可用 | Failure Path | Auth Service 宕机 | 500 + fallback to default quota |
| 负数 token 拒绝 | Security | input_tokens=-1 | Pydantic ValidationError |

### 2.4 Skills Registry

| 场景 | 类型 | 前置条件 | 预期结果 |
|------|------|---------|---------|
| 有效 SKILL.md 创建 | Happy Path | 完整 YAML frontmatter | skill created, version=1 |
| 无 frontmatter 降级 | Happy Path | 无 YAML frontmatter | 从首行 heading 推断 name |
| Path traversal 防护 | Security | `../evil.py` reference | ValueError 拒绝 |
| Skill 软删除 | Happy Path | DELETE skill | status=archived, 文件保留 |
| Skill 版本递增 | Happy Path | PUT 更新 skill_md | version += 1 |
| Skills 热更新广播 | Happy Path | PUT/POST skill | Redis PUBLISH channel:skill-update |
| 权限不足写入 | Failure Path | non-admin role | 403 Forbidden |
| 重复 skill 名称 | Failure Path | 已存在同名 skill | 409 Conflict |

### 2.5 Feishu Bot Service

| 场景 | 类型 | 前置条件 | 预期结果 |
|------|------|---------|---------|
| 有效签名验证 | Happy Path | HMAC-SHA256(valid) | 返回原始 body |
| 无效签名 | Security | HMAC-SHA256(wrong key) | HTTP 200 + INVALID_SIGNATURE code |
| 过期时间戳 (>5min) | Security | ts=10min ago | HTTP 200 + TIMESTAMP_OUT_OF_RANGE |
| 缺失签名 Header | Security | 缺少 X-Lark-Signature | HTTP 200 + MISSING_SIGNATURE_HEADERS |
| 首次消息 → 未绑定 | Happy Path | union_id 无绑定记录 | 发送绑定卡片消息 |
| 已绑定 → 写入 Redis Stream | Happy Path | union_id 已绑定 | XADD feishu:requests + response marker |
| 重复 event_id | Dedup | event_id 已存在 | 跳过处理，返回 200 |
| XREAD 响应超时 | Failure | 30s 无响应 | timeout → pending_retry 标记 |
| XREAD 收到 done=chunk | Recovery | done=true in chunk | 组装完整响应发送飞书 |

### 2.6 Admin Console

| 场景 | 类型 | 预期结果 |
|------|------|---------|
| 用户列表加载 | Happy Path | 表格展示用户数据 |
| 用户列表 loading 态 | Loading | Spin 组件显示 |
| 用户列表空数据 | Empty | "暂无用户数据" 文案 |
| 用户列表请求失败 | Error | message.error 提示 |
| 用户禁用二次确认 | Confirmation | Popconfirm 弹出 |
| Token 创建一次性展示 | Happy Path | Modal 显示 token 明文（仅一次）|
| Token 撤销确认 | Happy Path | Popconfirm + message.success |
| Dashboard 移动端布局 | Responsive | xs=24, sm=12 响应式 |
| TypeScript 编译 | Build | tsc -b 0 错误 |

---

## 3. 已知限制（Phase 1 Mock）

| 依赖 | 现状 | 影响范围 | Phase 2 验证项 |
|------|------|---------|--------------|
| OIDC / Keycloak | Mock (`dev@hermes.local / devpassword`) | Auth Service `/auth/login` | 真实 OIDC code flow 端到端 |
| LLM 模型 | LiteLLM mock (fake provider) | Agent Router → Hermes → LLM 链路 | 真实模型响应质量、token 计数 |
| 飞书开放平台 | Mock 签名/事件 | Feishu Bot Service | 真实 Webhook + 消息收发 |
| K8s Pod Sidecar | Dev mode: 直接 HTTP | Agent Router 冷启动 | K8s API + Sidecar prepare/release |
| NAS/NFS | Dev mode: 本地 volume | Skills Registry、用户数据持久化 | NFS v4 挂载、文件锁、I/O 性能 |
| PostgreSQL | 本地 Docker volume | 平台数据持久化 | 流复制、连接池、高可用 |

---

## 4. 高风险路径关注

| 路径 | 风险描述 | 缓解 | Phase 2 验证重点 |
|------|---------|------|----------------|
| 飞书消息 → Agent 响应 → 回复飞书 | Redis Streams 延迟或丢失 | XACK 确认机制 | 真实 LLM 响应时间（30s+）下的 XREAD timeout |
| 用户并发冷启动 | Pod Pool 耗尽 | 6 次重试 + 间隔 0.5s | 500 并发压力测试 |
| 冷启动超 3s SLA | NAS I/O 抖动 | 预热池 buffer | 真实 NAS 下的冷启动 P95 |
| JWT 签名密钥轮换 | 在线 session 失效 | 优雅轮换方案待定 | Key 轮换 SOP |
| Auth Service 双副本高可用 | 单副本故障 | Redis 缓存 5min | 故障转移测试 |

---

## 5. 放行建议

| 维度 | 评估 | 结论 |
|------|------|------|
| Happy path 覆盖率 | 7/7 模块全覆盖 | ✅ |
| 失败路径覆盖率 | Router/Quota/FBot 均有 failure 测试 | ✅ |
| 安全关键路径 | HMAC/timing-safe/dedup/SHA-256 均有测试 | ✅ |
| Mock 依赖透明度 | 全部已文档化 | ✅ |
| **关键阻塞项** | 🔴 `verify_password` 重复定义（auth_service/service.py）| 修复后方可放行 |
| 补充测试需求 | JWT 过期测试、Skills Router handler、Redis 不可用路径 | 🟡 Phase 2 前补充 |

---

*创建日期: 2026-04-16*
*QA Engineer: AI Lab User1-1*
*审查依据: PRD, Arch Design, ADR-003, ADR-005, Execute Log, 源码审查*
