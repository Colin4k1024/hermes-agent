# Hermes 企业内部 SaaS — Design Context

**版本**: v1.0
**日期**: 2026-04-16
**状态**: `design-ready`
**Slug**: hermes-enterprise-saas

---

## 1. Admin Console 范围（D7）

**决策**: ✅ **Phase 1 基础版**

**范围**：
- 用户列表查看
- 基础用量查看（当日/当周 token 消耗）
- API Token 管理（创建/撤销）

**Phase 2 扩展**：
- 角色管理（admin/power_user/user 分配）
- 配额配置（按角色设置）
- Skills 管理（发布/更新/下架）
- 审计日志查看

**维护方**: tech-lead 初期维护，后期移交

---

## 2. 配额粒度

**决策**: ✅ **按角色（user/power_user/admin）**

| 角色 | 典型配额 |
|------|---------|
| user | 100,000 tokens/day |
| power_user | 500,000 tokens/day |
| admin | 无限制 |

**说明**：
- 20k 用户场景下，按用户配置不现实
- 按部门需维护组织树，Phase 2 再评估
- 配额检查在 Agent Router 层前置执行

---

## 3. Skills 热更新广播机制

**决策**: ✅ **Router 遍历 active-pods 调用 /internal/skills/reload**

**流程**：
```
管理员更新 org skill
    ↓
Skills Registry 更新 PG + NAS
    ↓
Skills Registry → Redis PUBLISH channel:skill-update {skill, version}
    ↓
Router SUBSCRIBE 收到通知
    ↓
Router → SMEMBERS active-pods 获取所有活跃 Pod
    ↓
Router 并行调用各 Pod /internal/skills/reload
    ↓
Pod 重新扫描 /nas/org-skills/ 目录
```

**优点**：
- Skills 更新低频（一天几次），遍历开销可接受
- Router 已有 active-pods 数据，无需引入新组件
- 与现有 Redis Streams（飞书消息）不冲突

---

## 4. 审计日志范围

**决策**: ✅ **登录 + API 调用 + LLM 用量**

**记录范围**：

| 操作类型 | 记录内容 | 存储 |
|---------|---------|------|
| 登录/登出 | user_id, timestamp, IP, user_agent | audit_logs |
| API 调用 | user_id, endpoint, tokens_used, latency | audit_logs |
| LLM 用量 | user_id, model, input_tokens, output_tokens | usage_records |
| 管理员操作 | user_id, action, target_resource | audit_logs |

**不记录**：
- Web UI 页面浏览（Phase 1 非核心场景）
- 飞书消息内容（已由飞书平台存储）

**保留策略**：在线 3 个月，归档到 NAS cold tier

---

## 5. 未讨论项（按推荐执行）

以下事项在 PRD/Arch Design/ARCH-REVIEW 中已有明确结论，直接执行：

| 事项 | 结论 | 来源 |
|------|------|------|
| SSO 协议 | OIDC + Keycloak | D1 |
| 飞书应用类型 | 企业自建应用 | D2 |
| 内网 LLM | LiteLLM 原生支持 | D3 |
| K8s 资源 | 250 core / 1000GB | D4 |
| NAS 存储 | 256-shard + 4 层备份 | D5 |
| LiteLLM 高可用 | 3 副本 + 熔断 + 客户端重试 | R4 |
| ADR-004/005 | 全文已完成 | - |

---

## 6. 假设清单（待验证）

| # | 假设 | 影响 | 验证方式 |
|---|------|------|---------|
| ASSUM-1 | AI Infra 团队可提供内网 LLM 模型清单 | D3 | 联系 AI Infra 确认 |
| ASSUM-2 | 现有 NAS 支持 NFS v4.1/v4.2 | D5 | 实测验证 |
| ASSUM-3 | IT 部门可注册飞书企业自建应用 | D2 | IT 沟通 |
| ASSUM-4 | Keycloak 可在 Phase 1 前完成部署 | D1 | devops 确认 |

---

## 7. 排除的选项

| 排除选项 | 排除原因 |
|---------|---------|
| 按用户精细化配额 | 20k 用户场景下管理成本过高 |
| Redis Pub/Sub 用于 Skills 热更新 | 与 Redis Streams 冲突，且 Skills 更新低频无需独立队列 |
| 全量审计日志 | 存储压力大，Phase 1 非必要 |
| Phase 2 再做 Admin Console | Phase 1 50 人试点必须能管理用户 |

---

*讨论日期: 2026-04-16*
*讨论参与者: AI Lab User1-1 + architect*
