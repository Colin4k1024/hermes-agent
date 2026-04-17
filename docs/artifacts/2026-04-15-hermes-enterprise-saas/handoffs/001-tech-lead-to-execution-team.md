---
artifact: handoff
task: hermes-enterprise-saas
date: 2026-04-16
role: tech-lead
status: ready-for-review
---

# Handoff: Tech-Lead → Execution Team

## 1. 交接信息

| 字段 | 值 |
|------|-----|
| **当前阶段** | design-swarm |
| **目标阶段** | execute |
| **就绪状态** | `ready-for-review`（3 条高优先级质疑已确认方案）|
| **下一跳角色** | backend-engineer, frontend-engineer, devops |
| **交接方** | tech-lead + architect |

---

## 2. 背景

Hermes Agent 企业内部 SaaS 平台改造项目，将开源单用户 Hermes Agent 扩展为支持 20,000+ 用户的企业内部平台。核心原则：**不改 Hermes 核心代码，在外围加控制面**。

---

## 3. 输入依据

| 文档 | 位置 | 状态 |
|------|------|------|
| PRD | `prd.md` | ✅ |
| Arch Design | `arch-design.md` | ✅ |
| ARCH-REVIEW | `ARCH-REVIEW.md` | ✅ v1.1-reviewed |
| Design Context | `context.md` | ✅ |
| Delivery Plan | `delivery-plan.md` | draft |

**ADR 清单**：

| ADR | 决策 |
|-----|------|
| ADR-001 | Per-user SQLite on NAS/NFS v4 |
| ADR-002 | Pod Pool + 热冷调度（TTL 30min）|
| ADR-003 | OIDC + Keycloak + JWT + API Token |
| ADR-004 | NAS + NFS v4 + 256-shard + 4层备份 |
| ADR-005 | 飞书企业自建应用 + Redis Streams |

---

## 4. 结论

### 4.1 架构结论

- **Agent 执行**：600 Pod Pool + Redis 路由表 + 热冷分离
- **数据存储**：Per-user SQLite on NAS + PostgreSQL 平台数据
- **Auth**：OIDC + Keycloak（自托管）+ JWT
- **飞书**：企业自建应用 + tenant_access_token（Bot 模式）
- **LLM**：LiteLLM Proxy（3 副本）+ 内网模型
- **配额**：按角色（user/power_user/admin）
- **Skills 热更新**：Router 遍历 active-pods
- **审计**：登录 + API 调用 + LLM 用量

### 4.2 关键技术参数

| 参数 | 值 |
|------|-----|
| 用户规模 | 20,000+ |
| 峰值并发 | 500 |
| Pod Pool | 600（HPA 400-800）|
| 冷启动目标 | < 3s |
| K8s 集群（推荐）| 250 core / 1000GB |
| NAS 存储 | ~10TB（256-shard）|

---

## 5. 风险

| # | 风险 | 等级 | 缓解 |
|---|------|------|------|
| R1 | NAS NFS v4 SQLite WAL 兼容性 | **高** | Phase 1 前实测验证 |
| R2 | 冷启动超 3s | **高** | 预热池 + NAS SSD |
| R3 | Keycloak 部署延期 | **中** | devops 提前介入 |
| R4 | D3 LLM 模型待确认 | **中** | 开发阶段用 mock provider |

---

## 6. 待确认项

| # | 问题 | 影响 | Owner |
|---|------|------|-------|
| D3 | 内网 LLM 模型清单 | LiteLLM 配置 | AI Infra |
| D5 | NAS 设备确认 | 存储方案 | devops |
| D6 | 域名申请 | TLS/DNS | devops |
| D7 | Admin Console 维护方 | UI 维护 | tech-lead |

**重要**：以上待确认项**不影响开发**，开发阶段使用 mock/本地环境推进。

---

## 7. 下一跳角色动作清单

### 7.1 backend-engineer

| 动作 | 前置条件 | 产出 |
|------|---------|------|
| 1. Auth Service 开发 | OIDC mock provider | FastAPI Auth Service |
| 2. Agent Router 开发 | Redis mock | FastAPI Router Service |
| 3. Quota Service 开发 | PostgreSQL | FastAPI Quota Service |
| 4. Skills Registry 开发 | PostgreSQL + 本地文件 | FastAPI Skills Registry |
| 5. Feishu Bot Service 开发 | Redis Streams mock + lark_oapi mock | FastAPI Feishu Bot |
| 6. LiteLLM Proxy 配置 | mock LLM endpoint | LiteLLM config.yaml |

### 7.2 frontend-engineer

| 动作 | 前置条件 | 产出 |
|------|---------|------|
| 1. Admin Console 骨架 | React + Ant Design Pro | 项目结构 |
| 2. 用户管理页面 | mock API | 用户列表、详情页 |
| 3. 用量看板页面 | mock 数据 | 图表组件 |
| 4. API Token 管理 | mock API | Token 创建/撤销 |

### 7.3 devops

| 动作 | 前置条件 | 产出 |
|------|---------|------|
| 1. 本地开发环境 | Docker Compose | 本地可运行环境 |
| 2. K8s 部署规划 | Helm Chart 模板 | 部署清单 |
| 3. Prometheus 监控方案 | 指标定义 | 监控配置 |
| 4. Keycloak 部署 | D1 确认 | Keycloak instance |

---

## 8. 开发顺序建议

```
第一梯队（可立即开始）
├── backend: Auth Service（mock OIDC）
├── backend: Agent Router（mock Redis 调度）
├── backend: Quota Service
├── frontend: Admin Console 骨架 + 用户管理页面
└── devops: Docker Compose 本地开发环境

第二梯队（依赖部分确认）
├── backend: Feishu Bot Service（mock Webhook）
├── backend: LiteLLM Proxy（mock provider）
└── backend: Skills Registry

第三梯队（Phase 1 部署前）
├── devops: K8s 部署
├── devops: NAS 挂载
├── devops: Keycloak 真实对接
└── backend: 真实 LLM 配置
```

---

## 9. 下游质疑记录（执行团队评审）

### 🔴 高优先级质疑（阻塞执行）

| ID | 质疑内容 | 质疑目标 | 影响 |
|----|---------|---------|------|
| **BE-2** | Hermes `/internal/skills/reload` 端点不存在，sidecar 方案未设计 | arch-design.md 附录 B | 违反"不改核心"原则，需重新评估 |
| **BE-3** | 飞书 Router → Pod → FBot 回调路径不清，缺少 msg_id 关联机制 | arch-design.md §3.2 §6.2 | Feishu Bot 和 Router 接口无法对接 |
| **DO-1** | K8s `hostPath + subPath` 动态挂载方案冲突，Pod 调度到无 NAS Node 会失败 | ARCH-REVIEW.md §6.2 | 需明确 K8s 层 NAS 挂载完整方案 |

### 🟡 中优先级质疑（影响开发效率）

| ID | 质疑内容 | 质疑目标 | 影响 |
|----|---------|---------|------|
| **BE-1** | Redis `session:lock` GET + SET 非原子操作，并发竞争风险 | arch-design.md §4.3 | 需改用 `SET NX EX` |
| **BE-4** | LiteLLM token callback 字段不明确，流式场景统计时机不清 | arch-design.md §6.2 | Quota Service 无法实现 |
| **FE-1** | Mock API 契约未锁定（字段名、分页参数、响应结构）| handoff §7.2 | 前端无法建模，可能返工 |
| **FE-2** | 用量看板数据源和刷新策略未定义（per-user 聚合 vs 全量）| delivery-plan.md §8 | 图表选型无法确定 |
| **FE-3** | D7 维护方未收敛影响前端架构决策 | context.md §1 | 前端无法确定路由/权限架构 |
| **DO-2** | WAL 验证缺具体标准（benchmark 工具、Pass/Fail 基准）| ARCH-REVIEW.md R1 | Phase 1 前无法验证 |
| **DO-3** | Keycloak HA/规模未规划，Phase 1 时间线不确定 | handoff §5 R3 | 影响 Auth Service 端到端 |
| **DO-4** | 监控 SLO 指标缺失（NAS latency、cold-start success rate 等）| handoff §7.3 | Phase 1 无可观测性 |

### 质疑汇总

| 来源 | 质疑数 | 阻塞执行 |
|------|--------|---------|
| backend-engineer | 4 条 | 2 条（BE-2, BE-3）|
| frontend-engineer | 3 条 | 0 条（FE-1/2/3 为效率问题）|
| devops | 4 条 | 1 条（DO-1）|

**结论**：BE-2、BE-3、DO-1 共 3 条高优先级质疑需在 `/team-execute` 前由 architect 响应并更新设计文档。

---

### ✅ Architect 方案确认（2026-04-16）

#### BE-2 确认方案：Pod 容器级切换（方案 C）

| 项目 | 方案 |
|------|------|
| **核心机制** | Sidecar 接收 `{user_id, hermes_home_path}` → 写 `/tmp/pending_user.json` → SIGTERM → K8s 重启 Hermes 容器 → entrypoint.sh 读文件启动 |
| **Hermes 改动** | 0（仅扩展 entrypoint.sh 5-10 行）|
| **冷启动增量** | 1-2s（SIGTERM ~500ms + 容器重启 ~500ms），总计 < 3s SLA |
| **执行前置条件** | WAL checkpoint 由 Sidecar 显式调用；`/tmp/pending_user.json` 启动后立即删除；Skills 更新时分批重启（batch_size=20，间隔 5s）|

#### BE-3 确认方案：Redis Streams 双向 Channel + reply_channel

| 项目 | 方案 |
|------|------|
| **核心机制** | FBot 写 `feishu:requests`（Router 消费）+ `feishu:responses:{fbot_instance_id}`（自己等待） |
| **Router 接口变更** | `/internal/route` 增加 `reply_channel` 字段 |
| **执行前置条件** | XREADBLOCK timeout 30-60s；response stream TTL 24h；Router 读后 XACK（幂等处理避免重复 POST）|

#### DO-1 确认方案：NFS Subdir External Provisioner

| 项目 | 方案 |
|------|------|
| **核心机制** | StorageClass `nfs-hermes-per-user` + NFS Subdir External Provisioner，每个用户独立 PVC |
| **pathPattern** | `/hermes-homes/${namespace}/${pvcName}` |
| **Fallback** | Shared NFS PVC + Init Container 动态创建子目录 |
| **执行前置条件** | 集群 RBAC 允许安装 Provisioner；NFS Server 网络可达（端口 2049）；reclaimPolicy 设为 Retain |

---

### ✅ 解除 blocked 状态

| 质疑 | 状态 | 确认日期 |
|------|------|---------|
| BE-2 | ✅ 已确认 | 2026-04-16 |
| BE-3 | ✅ 已确认 | 2026-04-16 |
| DO-1 | ✅ 已确认 | 2026-04-16 |

**所有高优先级质疑已解除，handoff 状态更新为 `ready-for-review`。**

---

## 10. 验收检查点

| 检查点 | 说明 |
|--------|------|
| Auth Service | OIDC Authorization Code Flow 端到端 |
| Agent Router | 用户→Pod 路由、Redis 路由表更新 |
| Feishu Bot | Webhook 接收、消息推送、身份绑定 |
| Quota Service | Token 计量、配额检查 |
| Admin Console | 用户列表、用量图表、Token 管理 |

---

*创建日期: 2026-04-16*
*tech-lead: AI Lab User1-1*
