# Artifacts Index

## Hermes Enterprise SaaS (2026-04-15)

| 类型 | 文件 | 状态 | 说明 |
|------|------|------|------|
| **PRD** | `2026-04-15-hermes-enterprise-saas/prd.md` | ✅ | 产品需求文档 |
| **Arch Design** | `2026-04-15-hermes-enterprise-saas/arch-design.md` | ✅ v0.2-reviewed | 架构设计（含 BE-2/BE-3/DO-1 更新）|
| **Arch Review** | `2026-04-15-hermes-enterprise-saas/ARCH-REVIEW.md` | ✅ v1.1-reviewed | 架构评审 |
| **Context** | `2026-04-15-hermes-enterprise-saas/context.md` | ✅ | Design Context（配额粒度、Skills 热更新等）|
| **Delivery Plan** | `2026-04-15-hermes-enterprise-saas/delivery-plan.md` | ✅ | 交付计划 |
| **Execute Log** | `2026-04-15-hermes-enterprise-saas/execute-log.md` | ✅ | 执行记录（第一梯队完成）|
| **Test Plan** | `2026-04-15-hermes-enterprise-saas/test-plan.md` | ✅ | 测试矩阵 + BLOCKER 修复验证 |
| **Launch Acceptance** | `2026-04-15-hermes-enterprise-saas/launch-acceptance.md` | ✅ Go | Phase 1 MVP 通过，所有 Critical 已修复 |
| **Handoff** | `2026-04-15-hermes-enterprise-saas/handoffs/001-*.md` | ready-for-review | 执行团队交接 |

## Hermes StateStore SaaS Implementation (2026-04-25)

| 类型 | 文件 | 状态 | 说明 |
|------|------|------|------|
| **Implementation Changelog** | `2026-04-25-hermes-state-store-saas/CHANGELOG.md` | ✅ implemented | StateStore、State Service、Router stateless runtime、部署和测试记录 |

## ADRs

| # | 文件 | 状态 | 决策 |
|---|------|------|------|
| ADR-001 | `adr/ADR-001-user-data-storage.md` | ✅ | Per-user SQLite on NAS/NFS v4 |
| ADR-002 | `adr/ADR-002-agent-execution-model.md` | ✅ | Pod Pool + 热冷调度 |
| ADR-003 | `adr/ADR-003-auth-and-token.md` | ✅ | OIDC + Keycloak + JWT |
| ADR-004 | `adr/ADR-004-user-storage-medium.md` | ✅ 更新 2026-04-16 | NAS 存储 + 256-shard + NFS Subdir Provisioner |
| ADR-005 | `adr/ADR-005-feishu-integration.md` | ✅ 更新 2026-04-16 | 飞书企业自建应用 + Redis Streams |

---

*最后更新: 2026-04-25*
