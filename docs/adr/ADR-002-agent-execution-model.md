# ADR-002: Agent 执行模型 — Pod Pool + 热冷调度 vs 真正多租户进程

**状态**: accepted  
**日期**: 2026-04-15  
**Owner**: architect  
**关联需求**: hermes-enterprise-saas PRD  
**关联 Arch Design**: docs/artifacts/2026-04-15-hermes-enterprise-saas/arch-design.md

---

## 背景与约束

Hermes Agent 当前以单用户单进程模式运行：一个 Python 进程绑定一个 `HERMES_HOME` 目录，通过 `api_server.py` 对外暴露 OpenAI-compatible API（端口 8642）。每个进程同一时刻只能服务一个用户身份。

在 20,000+ 用户的企业 SaaS 场景下，需要决定如何在有限的 K8s 资源（D4: 200 core / 800GB RAM）内高效服务所有用户。

**关键约束**：

1. 峰值并发 500 用户同时活跃
2. DAU 约 6,000（30%）
3. 冷启动时间 < 3s
4. Hermes Agent 核心代码不做修改

**非目标**：

- 不讨论存储方案（见 ADR-001、ADR-004）
- 不讨论 K8s HPA 策略细节

---

## 备选方案

### Option A: 每用户独立容器（1 容器/用户，始终运行）

**描述**：为 20,000 个用户各创建一个 K8s Pod，始终运行。

**优点**：
- 架构最简单：user_id → 固定 Pod，无需调度逻辑
- 零冷启动延迟

**风险或成本**：
- **资源不可行**：20k Pod × 200m CPU = 4,000 core，远超可用资源（200 core）
- **K8s 管控面压力**：20k Pod 的 watch、event 让 etcd 和 kube-apiserver 不堪重负
- **升级灾难**：镜像更新需要滚动重启 20k Pod

**不选原因**：在 20k 用户规模下资源需求超出 K8s 集群能力 20 倍，根本不可行。

### Option B: Pod Pool + 热冷调度（本方案）

**描述**：维护一个大小为 400–800 的 Agent Pod 池（K8s Deployment + HPA）。Agent Router 收到用户请求时，从空闲池取出 Pod，通过 Sidecar API 注入 `HERMES_HOME` 路径并触发配置重载，然后路由请求。空闲 30 分钟后 Pod 回收到池中。

**优点**：
- **Hermes 零改动**：所有切换逻辑在 Sidecar 完成，不侵入主进程
- **资源可控**：600 Pod × 200m CPU = 120 core request，在 200 core 集群内可行
- **冷启动 < 3s**：Pod 已运行，只需切换 HERMES_HOME（~500ms）+ LLM 首 token（~2s）= ~2.5s
- **弹性伸缩**：HPA 按 CPU 使用率在 400–800 之间动态调整

**风险或成本**：
- 调度逻辑复杂：需要 Agent Router + Redis 路由表 + 分布式锁
- 需要新建 Sidecar 容器

**Sidecar 方案详解**：

每个 Agent Pod 内运行两个容器：
1. **Hermes 主容器**：运行 Hermes Agent 进程，暴露 `:8642`
2. **Agent Sidecar**：轻量 FastAPI 进程，暴露以下内部 API：

| Endpoint | 触发方 | 行为 |
|----------|--------|------|
| `POST /internal/prepare` | Agent Router（冷启动时）| 接收 `{user_id, hermes_home_path, env_vars}`，切换 HERMES_HOME，触发配置重载 |
| `POST /internal/release` | Agent Router（回收时）| 执行 SQLite `PRAGMA wal_checkpoint(TRUNCATE)`，清除用户上下文，标记 Pod 为空闲 |
| `POST /internal/skills/reload` | Skills Registry（热更新时）| 重新扫描 `/nas/org-skills/`，触发 skills 重载 |

Sidecar 与主容器共享同一 Pod 网络（localhost 通信）和 NAS volume mount，不需要修改 Hermes 源码。

### Option C: 真正多租户（单进程服务多用户，重构 Hermes 核心）

**描述**：重写 Hermes Agent 核心，使单个进程可以同时处理多个用户的请求，通过请求级的 user context 隔离数据访问。

**优点**：
- 资源效率最高
- 无冷启动问题

**风险或成本**：
- **彻底违反 "核心代码不改" 约束**：需要重写 `run_agent.py`、`hermes_state.py`、所有 plugin 等核心模块
- 开发周期 3–6 个月，引入大量回归风险
- 用户隔离从物理级降为逻辑级，安全风险增加

**不选原因**：违反核心约束，开发周期和风险不可接受。可作为 Phase 4（10 万+用户）的长期方向。

---

## 决策结果

**采用 Option B：Pod Pool + 热冷调度。**

**核心原因**：

1. **Hermes 代码零改动**：所有调度逻辑在平台控制面完成，Sidecar 作为独立容器运行，不侵入主进程。
2. **20k 规模资源可控**：600 Pod Pool 的 CPU request（120 core）在 D4 集群（200 core）范围内留有充足余量。
3. **冷启动达标**：预热 Pod 池 + Sidecar 快速切换 HERMES_HOME（~500ms）+ LLM 首 token（~2s），总计 ~2.5s，低于 3s SLA。

**影响范围**：

- 需要新建 Agent Router（FastAPI + Redis + kubernetes-client）
- 需要新建 Agent Sidecar 容器镜像（轻量 FastAPI，~50 行核心代码）
- Redis 承载路由表、空闲池、健康检查、分布式锁
- K8s 配置：Deployment（replicas: 600）+ HPA（min: 400, max: 800）+ PodDisruptionBudget

**兼容性 / 迁移影响**：

- 对 Hermes 上游代码完全兼容，Hermes 版本升级只需更新 Docker 镜像
- 如果 Phase 4 需要扩展到 10 万+用户，可在此架构基础上评估 Option C

**失败或回退思路**：

- 如果 Sidecar HERMES_HOME 切换不稳定，可回退到"回收时 kill Pod 而非复用"——冷启动时间增加约 2s，但可靠性更高
- 如果 600 Pod Pool 不够，先通过 HPA 扩到 800，再评估是否需要扩大集群资源
- 如果 NAS I/O 导致冷启动超时，引入 local SSD cache layer 作为 NAS 读缓存

---

## 企业内控补充

- **应用等级**: T2，600 Pod Pool 多实例满足高可用要求
- **技术架构等级**: Pod Pool + Sidecar 属于平台级基础设施，需要集群级资源规划
- **关键组件偏离**: Sidecar 容器为自建组件，非集团标准组件。原因：Hermes Agent 的 per-user HERMES_HOME 切换需求没有现成解决方案
- **资产文档入口**: `docs/artifacts/2026-04-15-hermes-enterprise-saas/arch-design.md` Section 4

---

## 后续动作

| 动作 | Owner | 完成条件 |
|------|-------|---------|
| 确认 K8s 集群资源配额（D4） | devops-engineer | 200 core / 800GB 可分配确认 |
| 设计 Agent Sidecar API 规格 | backend-engineer | Sidecar API spec + Dockerfile |
| 实现 Agent Router 核心调度逻辑 | backend-engineer | 路由、冷启动、回收流程 + 单元测试 |
| 设计 Redis 路由表数据结构和 TTL 策略 | architect | Redis schema 文档 |
| HPA 配置与压力测试 | devops-engineer | Helm values + 压力测试报告 |
| 同步到 Delivery Plan | project-manager | delivery-plan.md 更新 |
