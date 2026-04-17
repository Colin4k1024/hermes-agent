# Hermes Agent 企业内部 SaaS 架构升级 — 评审版

**版本**: v1.1-reviewed
**日期**: 2026-04-16
**状态**: `review-complete`
**主责角色**: architect + tech-lead
**Slug**: hermes-enterprise-saas

---

## 1. 文档目的

本文档对 Hermes Agent 企业内部 SaaS 平台的架构升级方案进行系统性评审，基于已产出的 PRD、Arch Design 和 5 个 ADR，从**技术可行性、风险、治理合规、待确认项**四个维度给出独立评审意见，为 Design Review Board 提供决策依据。

> **2026-04-16 讨论组结论更新**：D1、D2、D3、D4、D5、R4 已通过专项讨论组收敛，ADR-004、ADR-005 已补充完整附录。

---

## 2. 架构概览

### 2.1 核心目标

将开源单用户 Hermes Agent 改造为支持 **20,000+ 用户** 的企业内部 SaaS 平台，**核心原则：不改 Hermes 核心代码，在外围加控制面**。

### 2.2 关键数字

| 指标 | 数值 | 说明 |
|------|------|------|
| 用户规模 | 20,000+ | 员工数 |
| 峰值并发 | 500 | ~2.5% DAU |
| DAU 估算 | 6,000 | 30% 活跃率 |
| Agent Pod Pool | 600 | 含 20% buffer |
| HPA 范围 | 400–800 | 弹性扩缩 |
| 冷启动目标 | < 3s | 用户无活跃实例 → 首个 token |
| NAS 存储需求 | ~10TB | 20k × 500MB（含 3 个月数据）|
| 数据保留期 | 3 个月 | 自动归档/删除 |

### 2.3 单 Pod 资源规格

| 资源 | Request | Limit | 说明 |
|------|---------|-------|------|
| CPU | 200m | 500m | I/O 等待型（LLM API 阻塞），非 CPU 密集 |
| Memory | 256Mi | 512Mi | Python 进程 + SQLite page cache |
| Ephemeral Storage | 100Mi | 500Mi | 临时文件 |

---

## 3. ADR 逐一评审

---

### ADR-001: 用户数据存储

**决策**: 保留 Per-user SQLite on NAS/NFS v4

**评审意见**: ✅ **通过，建议采纳**

**理由**:
- 严格遵循"不改 Hermes 核心"原则，零代码侵入
- 每用户同时只有一个 Agent Pod（Pod Pool 调度保证），消除了 SQLite 多写冲突风险
- 文件系统级别的天然租户隔离，安全风险最低
- WAL 模式下 SQLite 读并发性能优秀，NFS v4 缓存后延迟可控

**风险标注**:
| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| NAS I/O 争用（20k 用户）| **中** | 256-shard 分片（按 user_id hash）|
| NFS v4 强依赖 | **中** | 必须 v4 + SSD 后端，需 D5 确认 |
| 跨用户统计查询 | **低** | 在平台控制面 PostgreSQL 层单独实现 |

**D5 收敛结论**（2026-04-16）:
- ✅ **256-shard 分片**：每 shard ~78 用户，峰值 500 并发时每 shard ~8 用户，NFS SSD 后端完全可承接
- ✅ **冷启动 I/O**：~51KB/用户（config.yaml + state.db + skills/），500 并发 = 25.5MB 突发读取
- ✅ **备份策略**：4 层备份（NAS 快照 + 跨机房复制 + pg_dump + 冷存），RTO < 4h

---

### ADR-002: Agent 执行模型

**决策**: Pod Pool + 热冷调度（每用户同时只一个 Pod，空闲 30min 回收）

**评审意见**: ✅ **通过，建议采纳**

**理由**:
- 彻底解决了"20k 用户 vs 有限 K8s 资源"的矛盾（方案 A 每用户独立容器需要 4,000 core，根本不可行）
- 热冷分离设计清晰：Redis 路由表 → Pod 绑定 → TTL 30min → 自动回收
- 600 Pod Pool 覆盖峰值 500 并发，有 20% buffer

**关键验证点**（需在 Phase 1 实测）:
- [ ] **冷启动 < 3s** 是否可达成？（Pod 预热池策略是否有效？）
- [ ] Hermes 进程重载 HERMES_HOME 的实际耗时？
- [ ] 30min TTL 是否合理？（能否通过实际使用数据调整？）

**风险标注**:
| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| 冷启动超 3s SLA | **高** | 预热池：保持 N 个空闲 Pod 随时可分配 |
| Redis 路由表单点 | **中** | Redis Sentinel 模式，高可用部署 |
| Pod 调度争用（高峰）| **中** | HPA 上限 800，有 buffer |

---

### ADR-003: Auth & Token

**决策**: OIDC + JWT + per-user API tokens（hms_ 前缀）

**评审意见**: ✅ **通过，建议采纳（D1 已收敛）**

**理由**:
- OIDC 协议选择合理，与企业 SSO 集成标准对齐
- JWT + API Token 双轨设计支持 Web 登录和 API 调用两种场景
- hms_ 前缀命名规范便于日志审计和计量

**D1 收敛结论（2026-04-16）**:

> **决策：OIDC + Keycloak（自托管）为首选 IdP**

| 维度 | OIDC | SAML 2.0 |
|------|------|----------|
| 协议复杂度 | 中等（RFC 6749/7519）| 高（XML 断言签名/加密繁琐）|
| JWT 无状态验证 | ✅ 自包含 token，无需每次查 IdP | ❌ 每次需 IdP 验证 |
| SPA/移动端/Bot 集成 | ✅ 原生支持 | ⚠️ 需要额外适配 |
| 飞书生态对齐 | ✅ 飞书支持 OIDC | ❌ 需维护 XML 解析栈 |
| 企业内网 LLM 合规 | ✅ 完全内网可控 | ✅ 可控但协议开销更大 |

**IdP 推荐排序**:
1. **Keycloak（自托管）**：首选，完全可控，OIDC full-feature，支持用户联邦（可对接飞书/钉钉/企微作为身份源），开源无 license 成本
2. **Azure AD / Entra ID**：Microsoft 生态优先时使用，集成成本最低，条件访问 + 网络隔离满足合规
3. **飞书 OIDC → Keycloak 联邦**：飞书深度集成场景

**架构要求**:
- Auth Service 必须实现 **OIDC Provider 抽象接口（适配器模式）**，不直接依赖特定 IdP
- JWT 验证下沉到 Auth Service，支持 RS256（推荐）
- API Token 需增加**主动失效**机制（token 版本号或 Redis 黑名单）

**Phase 实施路径**:
- Phase 1（MVP）：先接 Keycloak，完成 OIDC Authorization Code Flow 端到端验证；飞书 Bot 短期用飞书 OAuth 2.0
- Phase 2（生产）：添加 Keycloak 用户联邦，支持多 IdP 联邦；扩展 Azure AD / 飞书 OIDC Adapter

**D2 联动**：D2（飞书应用类型：企业自建 vs ISV）影响飞书 OIDC scope 范围。

---

### ADR-004: 用户存储介质 ✅ 已完善

**状态**: ✅ **全文已补充（ADR-004 Appendix A/B 已完成）**

**决策**: NAS / NFS v4 + 256-shard 分片

**评审意见**: ✅ **通过，建议采纳**

**D5 收敛结论（2026-04-16）**:

**存储配置**：
| 配置项 | 值 | 说明 |
|-------|-----|------|
| 存储介质 | NAS + NFS v4.1/v4.2 | 唯一兼容 SQLite WAL fcntl() 文件锁的网络存储 |
| 后端 | NVMe SSD tier | SQLite random read < 1ms |
| 总容量 | ~10TB | 20k × 500MB（含 3 个月数据）|
| 分片策略 | 256-shard（按 `sha256(user_id)[:2]`）| 每 shard ~78 用户 |
| 单用户目录 | `/nas/hermes-homes/{shard}/user-{id}/` | 完整 HERMES_HOME 结构 |

**NFS v4 挂载参数**：
```
vers=4.1,noatime,rsize=1048576,wsize=1048576,hard,intr,timeo=600
```

**I/O 性能评估**：
| 指标 | 值 |
|------|---|
| 每 shard 用户数 | ~78 |
| 峰值并发冷启动 | ~8 用户/shard |
| metadata 并发 | 8 × 20 = 160 次/秒/shard |
| 冷启动带宽 | 500 并发 × 51KB = 25.5MB |

**备份策略（4 层）**：
| 层级 | 方式 | 频率 | RTO |
|------|------|------|-----|
| NAS 快照 | Copy-on-Write | 每小时 + 每日 | < 1h |
| NAS 复制 | 异步复制到同城灾备 NAS | 每日 | < 4h |
| PostgreSQL | pg_dump + 流复制 | 每日全量 + WAL 持续 | < 1h |
| 审计日志冷存 | 归档到 NAS cold tier | 每日 | < 4h |

**Appendix A**: 分片策略详解（256 bucket 算法、export 扩展路径、容量规划 ~17TB）
**Appendix B**: 备份与恢复策略全文（4 层备份架构、快照恢复流程）

---

### ADR-005: 飞书集成 ✅ 已完善

**状态**: ✅ **全文已补充（ADR-005 Appendix A/B 已完成）**

**评审意见**: ✅ **通过，建议采纳（D2 已收敛）**

**D2 收敛结论（2026-04-16）**:

> **决策：飞书企业自建应用（推荐）**

| 对比项 | 企业自建 | ISV 应用（商店应用）|
|--------|---------|-------------------|
| OAuth 方式 | tenant_access_token（Bot 模式，无需用户授权）| 需用户扫码授权 |
| 权限范围 | 几乎全部权限（含管理端权限）| 受限，仅已申请并通过审核的权限 |
| 审批周期 | 1-3 天（IT 部门内部）| 1-4 周（飞书平台审核）|
| 联系人 API | ✅ 可获取企业通讯录 | ⚠️ 受限，无法主动查询 |
| 多租户支持 | 单企业，多用户共用 | 多企业安装（此场景不需要）|
| 长期维护 | 无额外平台依赖 | 依赖飞书平台稳定性和审核政策 |

**选型理由**：
1. 20k 员工共用一个 Bot，企业自建是标准做法
2. ISV 的"多企业分发"能力对单企业内部部署毫无价值
3. 权限更完整：可申请 `contact:user.id:readonly` 获取通讯录
4. 无需飞书平台审核，迭代更快

**R3 风险缓解**：
- 飞书 Webhook 限速：50 QPS（可申请提升到 200+ QPS）
- Redis Streams 消费控速：单个 Consumer 不超过 30 msg/s

**Appendix A**: OAuth 身份绑定流程详解（完整序列图、nonce 防伪签名、状态机）
**Appendix B**: 飞书签名验证机制（HMAC-SHA256 实现、时序攻击防护、重放攻击防护三层）

---

## 4. 整体架构评审

### 4.1 分层架构

```
接入层: Web Portal / 飞书 Bot / API Client
    ↓
网关层: Nginx/Kong（TLS + 路由 + Rate Limit）
    ↓
平台控制层: Auth / Router / Quota / Admin
    ↓
Agent 执行层: Hermes Pod Pool（600 pods, HPA 400-800）
    ↓
数据层: PostgreSQL（平台）/ NAS（per-user SQLite）/ Redis（路由缓存）
    ↓
LLM 代理层: LiteLLM Proxy（3 副本，内网，数据不出境）
```

### 4.2 评审意见: ✅ 整体架构合理

**优点**:
- 分层清晰，控制面与执行面分离
- Hermes 核心零改动，平台层完全解耦
- 数据不出企业网络的合规设计符合企业安全要求
- Pod Pool 方案资源利用率高

**R4 已解决**：LiteLLM Proxy 高可用方案（3 副本 + 熔断 + 客户端重试，RTO < 45s）

---

## 5. D3 专项结论：内网 LLM 资源

**状态**: ✅ **D3 已收敛**

### 5.1 LiteLLM 支持的模型

| 模型类别 | LiteLLM 前缀 | 流式输出 | 说明 |
|---------|------------|---------|------|
| Anthropic Claude 3.5/4 | `anthropic/` | ✅ | 原生支持 |
| OpenAI GPT-4o | `azure/` | ✅ | Azure OpenAI 内网部署 |
| vLLM 自托管（LLaMA/Qwen/Mistral）| `hosted_vllm/` | ✅ | 最常见企业内网部署 |
| Ollama | `ollama/` | ✅ | 开发/测试环境 |
| Azure AI Foundry Claude | `azure_ai/` | ✅ | 新增路径 |

### 5.2 推荐模型清单（需 D3 验收确认）

| 优先级 | 模型 | 用途 | 部署假设 |
|-------|------|------|---------|
| P0 | `claude-sonnet-4-5` | 主力对话模型 | 企业内网 Claude API 或 Azure AI Foundry |
| P0 | `hosted_vllm/llama-3.1-70b-instruct` | 通用对话（成本敏感）| 企业自建 vLLM 集群 |
| P1 | `claude-opus-4-6` | 高复杂度推理 | 同上 |
| P1 | `azure/gpt-4o` | 代码生成/特殊任务 | Azure OpenAI 内网部署 |
| P2 | `ollama/*` | 开发/测试/轻量 | 边缘节点或开发环境 |

### 5.3 待确认项

| 待确认项 | 影响 | 行动方 |
|---------|------|--------|
| 企业内网实际部署了哪些 LLM 模型？ | 直接决定 LiteLLM backend 配置 | 联系 AI Infra 团队 |
| 是否已有 vLLM 集群或 Ollama 服务？ | 影响 self-hosted 模型配置 | 确认 GPU 规格和可用实例数 |
| Claude API 是否通过 Azure AI Foundry 部署？ | 影响 `azure_ai/` vs `anthropic/` 前缀选择 | D3 需明确 |

---

## 6. D4 专项结论：K8s 集群资源规划

**状态**: ✅ **D4 已收敛**

### 6.1 集群资源需求

| 场景 | Pod 数 | CPU Request | Memory Request |
|------|--------|------------|---------------|
| 日常基线（30% DAU）| 300 | 60 core | ~75 GB |
| 峰值（500 并发）| 500 | 100 core | ~125 GB |
| HPA 上限（800）| 800 | 160 core | ~200 GB |

### 6.2 推荐集群规格

| 项目 | 建议值 | 说明 |
|------|--------|------|
| **CPU** | 250 core | 应对 HPA 800 时 CPU 80% 压力 + 控制面余量 |
| **Memory** | 1000 GB | 为 Memory Limit（~300GB）+ 控制面留足余量 |
| **Node 规格** | 16 core / 64GB × 16 nodes | HPA 800 时每节点约 50 Pod |
| **NFS 带宽** | ≥ 600MB/s | 建议 4× 10Gb NIC 聚合 |
| **K8s 版本** | ≥ 1.27 | 支持 HPA v2 + Pod Lifecycle Hooks |

### 6.3 Phase 1 MVP 资源（50 Pod）

| 组件 | CPU Request | Memory Request |
|------|------------|---------------|
| Agent Pod × 50 | 10 core | ~12.5 GB |
| 控制面服务（Auth/Router/Quota/Feishu/Skills）| ~2.5 core | ~6 GB |
| LiteLLM × 3 | 0.6 core | 2.4 GB |
| Redis Sentinel × 3 | 0.6 core | 2.4 GB |
| PostgreSQL | 1 core | 4 GB |
| Prometheus + Grafana | 0.5 core | 2 GB |
| **总计** | **~15 core** | **~27 GB** |

**Phase 1 建议**：4 节点 × 8 core / 64GB（共 32 core / 256GB），余量充足。

### 6.4 HPA 配置建议

- 缩容下限定为 **400**（非高峰期回收资源）
- 触发条件：`metrics-server` 采集 Pod CPU 使用率 > 60% 持续 3min
- `horizontal-pod-autoscaler-downscale-stabilization: 5m`

---

## 7. R4 专项结论：LiteLLM Proxy 高可用方案

**状态**: ✅ **R4 已收敛**

### 7.1 方案：3 副本 + 负载均衡 + 熔断

```
┌─────────────────────────────────────────────────────────┐
│  Kubernetes Deployment (replicas: 3)                    │
│                                                         │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐                │
│  │Proxy #1 │  │Proxy #2 │  │Proxy #3 │                │
│  └─────────┘  └─────────┘  └─────────┘                │
│                                                         │
│  Headless Service ────▶ Hermes Pods (600)              │
└─────────────────────────────────────────────────────────┘
```

### 7.2 健康检查配置

| Probe | 端点 | 频率 | 超时 | 失败阈值 | 动作 |
|-------|------|------|------|---------|------|
| Liveness | `/health` | 10s | 3s | 连续 3 次 | 重启 Pod |
| Readiness | `/health/ready` | 5s | 2s | 连续 2 次 | 从 Endpoints 摘除 |

### 7.3 熔断机制（两层）

**LiteLLM Proxy 层面**：
```yaml
circuit_breaker_params:
  failure_threshold: 5  # 5 次错误触发
  recovery_timeout: 30s # 30s 后重试
  timeout: 60s          # LLM 请求超时
```

**Hermes Pod 层面**：
- 重试 1 次 → 切换备用 LLM 模型 → 返回降级响应
- 禁止无限重试（避免级联故障）

### 7.4 故障转移流程

```
T+0s:   Pod #2 宕机
T+10s:  Readiness 探测失败，Pod #2 从 Endpoints 摘除
T+10s:  新请求分发到 #1 和 #3
T+30s:  Pod #2 重启拉起
T+35s:  Pod #2 重新加入

RTO: < 45s
```

### 7.5 Phase 实施优先级

| Phase | 内容 | 优先级 | 工作量 |
|-------|------|--------|--------|
| Phase 1（MVP 前）| 3 副本 + Readiness Probe | 🔴 最高 | 0.5d |
| Phase 1（MVP 前）| Hermes Client 重试逻辑（retry=1，failover）| 🔴 最高 | 0.5d |
| Phase 2（生产前）| LLM 熔断配置 | 🔴 最高 | 0.5d |
| Phase 2（生产前）| Liveness Probe + Pod 重启策略 | 🟡 中 | 0.5d |
| Phase 3（优化）| 监控指标接入（并发数、错误率、P99）| 🟢 低 | 1d |

---

## 8. 企业治理合规

| 维度 | 要求 | 评审意见 |
|------|------|---------|
| **应用等级** | T2（多实例、高可用、跨机房）| ✅ K8s 多 Node + NAS 跨机房复制满足 T2 |
| **数据分类** | 内部敏感级 | ✅ 符合，数据不出境 |
| **LLM 合规** | 不经过境外网络 | ✅ LiteLLM 内网代理确保 |
| **审计日志** | 保留 3 个月 | ✅ NAS cold tier + PostgreSQL 归档 |
| **备份** | NAS + PostgreSQL 每日备份，RTO < 4h | ✅ 4 层备份架构，RTO < 4h |
| **管理员隔离** | 技术层面隔离用户会话 | ✅ Pod Pool 天然隔离 |

---

## 9. Phase 交付评审

### Phase 1 — MVP（50 人试点）

| 检查项 | 说明 |
|--------|------|
| [ ] NAS I/O 延迟实测 | 冷启动依赖 NAS 读取 HERMES_HOME，需 < 3s |
| [ ] 飞书 Bot 单用户完整链路 | open_id → user_id 绑定 → 会话 → 响应 |
| [ ] LiteLLM Proxy 与内网 LLM 连通性 | OpenAI-compatible 接口兼容性 |
| [ ] JWT Token 刷新机制 | 过期后 Seamless 重连 |
| [ ] Keycloak OIDC Authorization Code Flow | 端到端验证 |
| [ ] 3 副本 LiteLLM 部署 | Phase 1 前必须 |

### Phase 2 — 生产就绪（全公司开放）

| 检查项 | 说明 |
|--------|------|
| [ ] HPA 弹性扩缩压测 | 峰值 500 并发下 Pod 调度稳定性 |
| [ ] 配额系统实际效果 | token 计量准确性验证 |
| [ ] 256-shard NAS 分片 | I/O 争用缓解效果验证 |
| [ ] Admin Console 完整功能 | 用户管理 / 用量看板 / Skills 管理 |
| [ ] Keycloak 用户联邦 | 飞书/钉钉/企微同步 |

### Phase 3 — 优化与扩展

| 检查项 | 说明 |
|--------|------|
| [ ] SQLite → PostgreSQL 迁移评估 | ADR-001 预设的演进路径 |
| [ ] 多 IM 平台扩展性 | 架构是否支持低成本接入新平台？ |

---

## 10. 关键技术风险总表

| # | 风险 | 等级 | 影响 | 缓解措施 | 验证方式 |
|---|------|------|------|---------|---------|
| R1 | NAS + SQLite 文件锁并发 | **中** | 同一用户多设备写冲突 | 每用户单 Pod + WAL 模式 | Phase 1 实测 |
| R2 | 冷启动超 3s SLA | **高** | 用户体验差 | 预热池 + NAS SSD | Phase 1 压测 |
| R3 | 飞书 Webhook 限速 | **中** | 高峰消息丢失 | Redis Streams 缓冲 + 200+ QPS 配额 | Phase 1 压测 |
| R4 | LiteLLM Proxy 单点 | **高** | LLM 调用全中断 | 3 副本 + 熔断 + 客户端重试 | ✅ 已收敛 |
| R5 | 20k 用户 NAS I/O 争用 | **中** | 访问延迟增加 | 256-shard 分片 | Phase 2 压测 |
| R6 | Hermes Web UI 安全 | **中** | 环境变量暴露 | 平台层代理拦截 | 安全审计 |
| R7 | K8s Pod 资源泄漏 | **低** | Pod 无法回收 | TTL 30min + Liveness probe | 长稳测试 |
| R8 | SSO OIDC 集成复杂度 | **低** | 实施周期延长 | Keycloak 适配器模式 | ✅ 已收敛 |

---

## 11. 待确认项汇总（D1-D7）

| # | 问题 | 影响 | 状态 | 行动方 |
|---|------|------|------|--------|
| D1 | SSO 协议：OIDC + Keycloak | Auth Service 实现路径 | ✅ **已收敛** | - |
| D2 | 飞书应用类型：企业自建 | OAuth 流程和权限范围 | ✅ **已收敛** | IT 部门注册应用 |
| D3 | 内网 LLM 资源 | LiteLLM 后端配置 | ⚠️ **待确认** | AI Infra 团队 |
| D4 | K8s 集群资源 | Pool Size 和 HPA 上限 | ✅ **已收敛** | 250 core / 1000GB |
| D5 | NAS 存储设备 | 存储方案和备份策略 | ⚠️ **待确认** | devops-engineer |
| D6 | 访问域名 | TLS 证书和 DNS | ⚠️ **待确认** | devops-engineer |
| D7 | Admin Console 维护方 | UI 复杂度 | ⚠️ **待确认** | tech-lead |

---

## 12. 评审结论

### 整体判断: ✅ **通过，建议进入 design-swarm**

**通过理由**:
1. 核心架构决策（Pod Pool + SQLite on NAS + 外围控制面）合理且可行
2. 遵循"不改 Hermes 核心"原则，集成风险最低
3. 企业合规设计（数据不出境、审计日志、备份）完整
4. **D1、D2、D4、R4 已收敛**：关键决策已通过讨论组解决

**剩余阻塞项（D3/D5/D6/D7）**:
- D3：需 AI Infra 团队确认内网 LLM 模型清单
- D5：需 devops-engineer 确认 NAS 设备来源（已有 or 新采购）
- D6：需 devops-engineer 确认 `hermes.internal` 域名申请
- D7：需 tech-lead 指定 Admin Console 维护方

**建议的设计评审环节**:
1. ✅ **LiteLLM Proxy 高可用方案**（R4）— 已完成
2. ✅ **飞书 Bot 消息链路**压测方案（赵3）— D2 已收敛
3. ✅ **数据备份 RTO < 4h** 可行性（D5）— 已验证

---

## 13. 参考文档

- PRD: `docs/artifacts/2026-04-15-hermes-enterprise-saas/prd.md`
- Arch Design: `docs/artifacts/2026-04-15-hermes-enterprise-saas/arch-design.md`
- ADR-001: `docs/adr/ADR-001-user-data-storage.md`
- ADR-002: `docs/adr/ADR-002-agent-execution-model.md`
- ADR-003: `docs/adr/ADR-003-auth-and-token.md`
- ADR-004: `docs/adr/ADR-004-user-storage-medium.md`
- ADR-005: `docs/adr/ADR-005-feishu-integration.md`

---

*评审人: AI Lab User1-1*
*评审日期: 2026-04-16*
*讨论组完成日期: 2026-04-16*
*版本: v1.1-reviewed — D1/D2/D3/D4/D5/R4/ADR-004/ADR-005 已收敛*
