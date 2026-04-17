# Project Context

## Hermes Enterprise SaaS

**项目名称**: Hermes Agent 企业内部 SaaS 平台
**项目目录**: `/Users/ailabuser1/Desktop/gitcode/hermes-agent`
**当前任务**: hermes-enterprise-saas
**日期**: 2026-04-16

---

## Tech Stack

| 层级 | 技术 |
|------|------|
| **语言** | Python + TypeScript/JavaScript |
| **前端** | React + Ant Design Pro |
| **后端** | FastAPI + PostgreSQL + Redis |
| **AI 代理** | Hermes Agent（核心不变）|
| **LLM 代理** | LiteLLM Proxy |
| **容器** | Kubernetes + Helm |
| **存储** | NAS/NFS v4 + SQLite（per-user）|

---

## 当前状态

| 项目 | 状态 |
|------|------|
| PRD | ✅ 完成 |
| Arch Design | ✅ 完成 |
| ARCH-REVIEW | ✅ v1.1-reviewed |
| Design Context | ✅ 完成 |
| Delivery Plan | 📝 draft |

---

## 关键依赖

| 依赖 | 状态 | Owner |
|------|------|-------|
| D1: Keycloak OIDC | 需 devops 确认部署时间线 | devops |
| D2: 飞书企业自建应用 | 需 IT 部门注册 | tech-lead |
| D3: 内网 LLM 模型 | 需 AI Infra 确认 | AI Infra |
| D4: K8s 集群资源 | 需 250 core / 1000GB | devops |
| D5: NAS 设备 | 需确认已有/采购 | devops |
| D6: 域名申请 | hermes.internal | devops |

---

## 活跃风险

| 风险 | 等级 | 缓解 |
|------|------|------|
| NAS NFS v4 SQLite WAL 兼容性 | 高 | Phase 1 前实测 |
| 冷启动超 3s | 高 | 预热池 |
| Keycloak 部署延期 | 中 | 提前介入 |
| 飞书应用审批延迟 | 中 | IT 沟通 |

---

## 交付里程碑

| 里程碑 | 目标 |
|--------|------|
| Phase 1 MVP（50 用户）| TBD |
| Phase 2 全公司开放 | TBD |
| Phase 3 优化扩展 | TBD |

---

*最后更新: 2026-04-16*
