---
artifact: delivery-plan
task: hermes-enterprise-saas
date: 2026-04-16
role: tech-lead
status: draft
---

# Hermes 企业内部 SaaS — 交付计划

**版本**: v1.0-draft
**日期**: 2026-04-16
**主责角色**: tech-lead
**Slug**: hermes-enterprise-saas

---

## 1. 需求挑战会结论

> 已完成：PRD Review + ARCH-REVIEW 讨论组（D1-D5, R4）

### 核心假设已确认

| # | 核心假设 | 质疑结论 | 状态 |
|---|---------|---------|------|
| H1 | 每用户单 Pod 即可满足 SQLite 并发安全 | ✅ 确认，Pod Pool 调度保证 | 已验证 |
| H2 | NAS NFS v4 支持 SQLite WAL 文件锁 | ⚠️ 待实测，需 D5 确认 | 待验证 |
| H3 | 冷启动 < 3s 可达成 | ⚠️ 依赖 Phase 1 实测 | 待验证 |
| H4 | Keycloak OIDC 可在 Phase 1 前完成 | ⚠️ 待 devops 确认 | 待确认 |
| H5 | 20k 用户 * 500MB = 10TB 足够 | ⚠️ 需 Phase 1 实测校正 | 待验证 |

### 未决项

| # | 未决项 | 影响 | Owner | 期限 |
|---|-------|------|-------|------|
| D3 | 内网 LLM 模型清单 | LiteLLM 配置 | AI Infra | Phase 1 前 |
| D5 | NAS 设备确认（已有/采购）| 存储方案 | devops | Phase 1 前 |
| D6 | 域名申请 | TLS/DNS | devops | Phase 1 前 |

---

## 2. 交付范围

### Phase 1 — MVP（50 人试点）

**目标**：核心链路跑通，50 真实用户验证

| 模块 | 交付内容 | 主责角色 | 依赖 |
|------|---------|---------|------|
| 基础设施 | K8s 集群（4 节点 × 8c/64GB）、NAS、NFS v4 | devops | D4+D5 |
| Auth Service | OIDC 登录、JWT 签发、基础用户管理 | backend | D1 |
| Agent Router | 路由调度、Redis 路由表、Pod 管理 | backend | - |
| LiteLLM Proxy | 3 副本部署、内网 LLM 接入 | backend | D3 |
| Feishu Bot | 企业自建应用、Webhook 接收、消息推送 | backend | D2 |
| API Token | per-user token、路由、计量 | backend | Auth |
| Admin Console | 基础版（用户列表、用量查看、API Token 管理）| frontend+backend | - |
| 监控 | Prometheus + Grafana 基础指标 | devops | - |

**Phase 1 验收门槛**：50 真实用户、飞书 Bot 可用、会话隔离验证

### Phase 2 — 生产就绪（全公司 20k 用户）

**目标**：弹性扩缩、完整管理能力

| 模块 | 交付内容 | 主责角色 |
|------|---------|---------|
| Agent Pool | HPA 弹性（400-800）、热冷调度优化 | backend |
| 配额系统 | 按角色配额、超限告警 | backend |
| Skills Registry | Org Skills 发布/同步、热更新广播 | backend+frontend |
| Admin Console | 完整版（角色管理、配额配置、Skills 管理）| frontend+backend |
| Web Portal | SSO 登录、代理 Hermes Web UI | frontend |
| 数据清理 | 3 个月自动归档/删除 CronJob | backend |

### Phase 3 — 优化扩展

**目标**：性能优化、平台扩展

| 模块 | 交付内容 |
|------|---------|
| 冷启动优化 | < 2s 目标 |
| 多 IM 平台 | 钉钉/企微/Slack 接入 |
| SQLite 演进 | PostgreSQL 迁移评估 |

---

## 3. 角色分工

| 角色 | 职责 | 主责任务 |
|------|------|---------|
| tech-lead | 总体协调、方案收口、升级仲裁 | 架构决策、技术评审 |
| architect | 系统设计、接口约定、风险评估 | Arch Design、ADR |
| backend-engineer | 控制面服务实现 | Auth/Router/Quota/Feishu Bot/Skills Registry |
| frontend-engineer | Admin Console UI 实现 | React + Ant Design Pro |
| devops-engineer | 基础设施、K8s 部署、监控 | 集群/NAS/LiteLLM/Prometheus |
| qa-engineer | 测试计划、验收测试 | Phase 1/2 验收 |

**交接顺序**：
```
tech-lead → architect（Arch Design 评审）
    ↓
architect → backend-engineer（接口契约）
    ↓
backend-engineer + frontend-engineer（并行开发）
    ↓
qa-engineer（验收测试）
    ↓
devops-engineer（发布部署）
```

---

## 4. 风险与依赖

### 高风险

| # | 风险 | 影响 | 缓解措施 | Owner |
|---|------|------|---------|-------|
| R1 | NAS NFS v4 SQLite WAL 兼容性问题 | 冷启动失败 | Phase 1 前实测验证 | devops |
| R2 | 冷启动超 3s | 用户体验差 | 预热池 + NAS SSD | backend |
| R3 | Keycloak 部署延期 | Phase 1 无法 SSO | devops 提前介入 | devops |
| R4 | AI Infra LLM 资源不到位 | LiteLLM 无法配置 | 提前联系确认 | tech-lead |

### 中风险

| # | 风险 | 影响 | 缓解措施 | Owner |
|---|------|------|---------|-------|
| R5 | 飞书企业自建应用审批延迟 | 飞书 Bot 无法上线 | IT 沟通 | tech-lead |
| R6 | 20k 用户 NAS I/O 争用 | 访问延迟增加 | 256-shard 分片 | devops |

---

## 5. 关键技术决策

### 已确认 ADR

| ADR | 决策 | 状态 |
|-----|------|------|
| ADR-001 | Per-user SQLite on NAS/NFS v4 | ✅ |
| ADR-002 | Pod Pool + 热冷调度（TTL 30min）| ✅ |
| ADR-003 | OIDC + Keycloak + JWT + API Token | ✅ |
| ADR-004 | NAS + NFS v4 + 256-shard + 4层备份 | ✅ |
| ADR-005 | 飞书企业自建应用 + Redis Streams | ✅ |

### 新增技术决策（Design Context）

| 决策 | 结论 |
|------|------|
| Admin Console 范围 | Phase 1 基础版（用户+用量+Token）|
| 配额粒度 | 按角色（user/power_user/admin）|
| Skills 热更新 | Router 遍历 active-pods |
| 审计日志范围 | 登录 + API + LLM 用量 |

---

## 6. 应用等级与技术架构

| 维度 | 要求 | 说明 |
|------|------|------|
| **应用等级** | T2 | 多实例、高可用、跨机房备份 |
| **数据分类** | 内部敏感级 | 数据不出境 |
| **LLM 合规** | 内网代理 | LiteLLM 确保 |
| **备份 RTO** | < 4h | 4 层备份架构 |
| **SLA** | 99.5%/月 | 内网环境 |

**关键组件偏离**：
- SQLite（非常规 DB）— 遵循"不改 Hermes 核心"原则，Phase 3 评估 PostgreSQL 迁移

---

## 7. 技能装配清单

| 技能 | 用途 | 阶段 |
|------|------|------|
| `backend-engineer` | 控制面服务实现 | Phase 1/2 |
| `frontend-engineer` | Admin Console UI | Phase 1/2 |
| `devops-engineer` | K8s 部署 + 监控 | Phase 1 |
| `qa-engineer` | 验收测试计划 | Phase 1/2 |

---

## 8. 前端交付物

| 交付物 | 说明 | 检查点 |
|--------|------|--------|
| Admin Console（Phase 1）| 用户列表、用量图表、API Token 管理 | 用户列表分页、用量趋势图 |
| Admin Console（Phase 2）| 角色管理、配额配置、Skills 管理 | 表单验证、状态反馈 |

**设计方向**：React + Ant Design Pro，简洁管理后台风格

---

## 9. 里程碑

| 里程碑 | 目标日期 | 交付内容 |
|--------|---------|---------|
| M1 | Phase 1 开始后 2 周 | 基础设施就绪（K8s + NAS + LiteLLM）|
| M2 | Phase 1 开始后 4 周 | Auth + Router + Feishu Bot 核心链路可用 |
| M3 | Phase 1 开始后 6 周 | Phase 1 MVP 验收（50 用户）|
| M4 | Phase 1 开始后 12 周 | Phase 2 生产就绪（全公司开放）|
| M5 | TBD | Phase 3 优化扩展 |

---

## 10. 升级与检查节点

| 节点 | 条件 | 升级到 |
|------|------|--------|
| Design Review Board | Arch Design + context.md 完成后 | tech-lead + architect |
| Phase 1 Checkpoint | M2 完成时 | tech-lead |
| Handoff to QA | Phase 1 功能完成后 | qa-engineer |
| Phase 2 Gate | Phase 1 验收通过 | tech-lead |

---

*创建日期: 2026-04-16*
*tech-lead: AI Lab User1-1*
