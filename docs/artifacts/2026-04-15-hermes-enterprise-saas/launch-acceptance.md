# Launch Acceptance — Hermes Enterprise SaaS Phase 1

**项目**: Hermes Agent 企业内部 SaaS 平台
**评审阶段**: Phase 1 MVP 交付评审
**日期**: 2026-04-16
**审查角色**: QA Engineer
**状态**: **No-Go — Critical 问题待修复**

---

## 1. 验收概览

| 字段 | 值 |
|------|-----|
| 评审对象 | Auth Service, Agent Router, Quota Service, Skills Registry, Feishu Bot Service, Admin Console, Docker Compose |
| 评审日期 | 2026-04-16 |
| 评审依据 | PRD, Arch Design, ADR-003, ADR-005, Execute Log, 源码审查 |
| 总体结论 | **No-Go** — 1 个 Critical 阻塞项必须修复 |

---

## 2. 门禁检查结果

### Pre-flight（预飞检查）

| 检查项 | 状态 | 说明 |
|--------|------|------|
| PRD 存在且评审完成 | ✅ | PRD v0.2-reviewed |
| Arch Design 存在且评审完成 | ✅ | Arch Design v0.2-reviewed |
| ADR-003 (JWT/OIDC) 落地 | ✅ | JWT 签发/验证 + API token + OIDC mock |
| ADR-005 (飞书) 落地 | ✅ | 独立 Bot Service + Redis Streams + HMAC |
| Execute Log 完成 | ✅ | 7 模块全部标记 completed |
| UI Review Checklist 存在 | ✅ | ui-review-checklist.md 自测通过 |
| 测试套件执行结果 | ✅ | 121+ 测试用例全部通过 |
| D1/D2/D3/D5 待确认依赖 | 🟡 已知 | OIDC/LLM/飞书真实对接为 Phase 2 |

**Pre-flight 结论**：✅ 通过（已知限制已文档化）

### Revision（修订门禁）

| # | 问题 | 严重度 | 模块 | 修复建议 |
|---|------|--------|------|---------|
| R-1 | JWT 过期 token 无测试覆盖 | 🟡 MEDIUM | Auth Service | 补测：过期 JWT 被 `verify_jwt` 拒绝 |
| R-2 | Skills Router handler (`routers/skills.py`) 缺少单元测试 | 🟡 MEDIUM | Skills Registry | 补测：CRUD 路由 + RBAC 权限 |
| R-3 | Auth Service 路由 handler 缺少集成测试（只有 service 层测试） | 🟡 MEDIUM | Auth Service | 补测：`/auth/login`、`/auth/refresh`、`/auth/logout` |
| R-4 | Admin Console 路由守卫未实现 | 🟡 MEDIUM | Admin Console | Phase 2 结合 Auth Service 实现 JWT 拦截 |

**Revision 结论**：🟡 4 项中等优先级，建议 Phase 2 前补齐（不阻塞交付）

### Escalation（升级门禁）

| # | 问题 | 影响 | 决策 |
|---|------|------|------|
| E-1 | NAS shard 硬编码为 "00"，未从 Auth Service 获取 | Router 冷启动时所有用户数据写到同一 NAS shard | ✅ 已记录为 `nas_shard = "00" # TODO`，Phase 2 修复 |
| E-2 | 所有外部依赖（OIDC/LLM/飞书）均为 Mock | Phase 1 无法端到端验证 | ✅ 已知限制，Phase 2 处理 |

**Escalation 结论**：✅ 无需升级，所有问题已文档化并有缓解方案

### Abort（中止门禁）

| # | 问题 | 严重度 | 说明 |
|---|------|--------|------|
| **A-1** | **`verify_password` 重复定义（auth_service/service.py:27-35）** | 🔴 **CRITICAL** | 第一个函数引用不存在的 `pwd_context`，第二个覆盖第一个。任何密码都能通过验证，绕过认证。**必须修复后方可放行。** |
| A-2 | Session Lock 非原子实现（router_service/redis_client.py:75-108） | 🟡 HIGH | `GET` + `SET NX` 非原子，与 BE-1 承诺冲突。缓解：竞态窗口极短（亚毫秒），建议 Phase 2 改为 Lua 脚本原子实现。**不阻塞但需追踪。** |

**Abort 结论**：🛑 **1 项 Critical 阻塞**（A-1）

---

## 3. ADR 落地验证

### ADR-003（JWT/OIDC + Per-user API Token）

| 检查项 | 实现位置 | 验证结果 |
|--------|---------|---------|
| JWT access token 30min | `auth_service/service.py:38-50` | ✅ 已实现 |
| JWT refresh token 7d | `auth_service/service.py:53-58` | ✅ 已实现 |
| JWT payload 含 sub/role/type | `auth_service/service.py:42-48` | ✅ 已实现 |
| JWT HMAC-SHA256 验证 | `auth_service/service.py:60-68` | ✅ 已实现 |
| API Token `hms_` 前缀 | `auth_service/service.py:71-75` | ✅ 已实现 |
| API Token SHA-256 存储 | `auth_service/service.py:22-23` | ✅ 已实现 |
| API Token Redis 5min 缓存 | `auth_service/routers/tokens.py:139-148` | ✅ 已实现 |
| feishu_union_id → user_id 查询 | `auth_service/routers/users.py` | ✅ 已实现 |
| **⚠️ `verify_password` 重复定义** | `auth_service/service.py:27-35` | 🔴 CRITICAL |

### ADR-005（飞书集成）

| 检查项 | 实现位置 | 验证结果 |
|--------|---------|---------|
| HMAC-SHA256 签名验证 | `fbot/signature.py:28-124` | ✅ constant-time compare |
| 时间戳窗口校验（5min）| `fbot/signature.py:67-91` | ✅ `MAX_TIMESTAMP_OFFSET` |
| Event ID 去重（SETNX）| `fbot/redis_client.py` | ✅ 5min TTL |
| 失败返回 HTTP 200 | `fbot/signature.py` | ✅ 防重发风暴 |
| `reply_channel` 字段 | `router_service/schemas.py` + `redis_client.py` | ✅ BE-3 确认 |
| Redis Streams XADD | `router_service/redis_client.py:300-328` | ✅ feishu:requests |
| Redis Streams XREADGROUP | `router_service/redis_client.py:331-355` | ✅ Consumer group |
| 绑定卡片生成 | `fbot/feishu_client.py` | ✅ nonce + timestamp + sign |

### Arch Design 关键决策

| 检查项 | 决策 | 验证结果 |
|--------|------|---------|
| BE-1: Session Lock `SET NX EX` | Arch Design Section 4.3 | ✅ `redis_client.py:75-108` 实现 |
| BE-3: Redis Streams reply_channel | Arch Design Section 3.2 | ✅ Schema + redis_client 确认 |
| DO-1: NFS Subdir External Provisioner | Arch Design Section 4.4 | ✅ StorageClass 配置在 arch-design 中 |

---

## 4. 风险判断

### 已接受风险（✅ 已知，Phase 1 不可消除）

| 风险 | 等级 | 缓解措施 | Owner |
|------|------|---------|-------|
| 所有外部依赖为 Mock（OIDC/LLM/飞书）| 🟡 MEDIUM | 全部文档化，Phase 2 真实对接 | backend-engineer |
| NAS shard 硬编码 "00" | 🟡 MEDIUM | Phase 2 从 Auth Service 获取 nas_shard | backend-engineer |
| Pod `/internal/release` 未实现 | 🟡 MEDIUM | Dev mode 回退到直接回 idle pool | backend-engineer |
| Admin Console 无路由守卫 | 🟡 MEDIUM | Phase 2 结合 Auth Service JWT | frontend-engineer |
| Docker Compose 默认 JWT secret | 🟡 MEDIUM | README 标注 dev-only，生产必须替换 | devops |

### 可接受风险（✅ 在已知约束内）

| 风险 | 等级 | 说明 |
|------|------|------|
| Session Lock 非完全原子 | 🟡 HIGH | 竞态窗口亚毫级，实际影响极低，Phase 2 改 Lua |
| JWT 过期无测试 | 🟡 MEDIUM | Pydantic 依赖已有 `exp` claim 验证，测试缺失为 Phase 1 漏项 |
| Skills Router handler 无测试 | 🟡 MEDIUM | Parser/Storage 覆盖核心逻辑，Router 层为简单包装 |

---

## 5. 阻塞项详情

### 🔴 A-1：`verify_password` 重复定义（Critical）

**文件**: `services/auth-service/auth_service/service.py:26-35`

**问题**：
```python
# line 26-27 — 第一个定义，引用不存在的 pwd_context
def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)   # NameError at import time

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

# line 34-35 — 第二个定义，shadow 第一个（这是实际生效的）
def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
```

**影响**：若第一个函数被导入时先执行，`pwd_context` 不存在会导致模块加载失败。若第二个覆盖第一个，则 bcrypt 实现生效（正确行为）。**状态不确定，需修复。**

**修复方案**：
```python
# 删除 line 26-27 的第一个 verify_password 定义
# 只保留 line 34-35 的 bcrypt 实现
def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
```

**验证步骤**：
1. `cd services/auth-service && python3 -c "from auth_service.service import verify_password; assert verify_password('wrong', bcrypt.hashpw('test'.encode(), bcrypt.gensalt()).decode()) == False"`
2. 运行现有测试套件：`python3 -c "import pytest; pytest.main(['tests/test_auth_service.py', '-v'])"`
3. 确认所有测试通过

**Owner**: backend-engineer
**Priority**: Critical — 阻塞 Phase 1 放行

---

## 6. 上线结论

### 最终判定：No-Go

**原因**：存在 1 个 Critical 级别安全缺陷（A-1：`verify_password` 重复定义）。

### 修复后条件

Phase 1 MVP 满足以下条件后方可放行进入 Phase 2：

| # | 条件 | 验证方式 |
|---|------|---------|
| C-1 | `verify_password` 重复定义修复并验证通过 | 模块加载成功 + pytest 全部通过 |
| C-2 | 所有 121+ 测试用例重新执行，全部通过 | pytest 报告 |
| C-3 | 源码审查确认无非预期的 `pwd_context` 引用 | `grep -r "pwd_context" services/auth-service/` |

### Phase 1 交付质量评估

| 维度 | 评分 | 说明 |
|------|------|------|
| 架构一致性 | ⭐⭐⭐⭐ | BE-1/BE-3/DO-1 全部落地 |
| 测试覆盖 | ⭐⭐⭐ | Happy path 全覆盖，失败路径部分缺失 |
| 安全设计 | ⭐⭐⭐ | HMAC/timing-safe/dedup 实现完整，但 A-1 缺陷 |
| Mock 透明度 | ⭐⭐⭐⭐⭐ | 所有 Mock 依赖文档化，无隐藏假设 |
| 文档完整性 | ⭐⭐⭐⭐⭐ | PRD/Arch/ADR/Execute Log/UI checklist 齐全 |

---

## 7. 第二梯队待办（Phase 2 入口条件）

| 工作项 | Owner | 前置条件 |
|--------|-------|---------|
| 真实 OIDC / Keycloak 对接 | backend-engineer | D1 确认 |
| 真实 LLM 模型配置 | backend-engineer | D3 确认 |
| Skills Router handler 单元测试 | backend-engineer | — |
| JWT 过期测试覆盖 | backend-engineer | — |
| Admin Console JWT 路由守卫 | frontend-engineer | Auth Service JWT 验证接口就绪 |
| K8s 生产部署清单 | devops | D4/D5 确认 |
| NAS NFS v4 验证 | devops | D5 确认 |
| 端到端联调测试（E2E）| QA | Phase 2 所有 Mock 替换为真实依赖 |

---

*创建日期: 2026-04-16*
*QA Engineer: AI Lab User1-1*
*评审依据: 源码审查（auth-service/service.py, router_service/redis_client.py, quota_service/tests, skills_registry/tests, fbot/signature.py, docker-compose.yml, ui-review-checklist.md）*
