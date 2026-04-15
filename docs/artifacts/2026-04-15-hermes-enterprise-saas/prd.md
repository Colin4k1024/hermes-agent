# PRD — Hermes Agent 企业内部 SaaS 平台

**版本**: 0.2-draft  
**日期**: 2026-04-15  
**状态**: requirement-challenge  
**主责角色**: tech-lead  
**Slug**: hermes-enterprise-saas

---

## 背景

### 确认项（2026-04-15）

| # | 问题 | 确认答案 | 架构影响 |
|---|------|---------|---------|
| 1 | 企业 IdP | **SSO（企业级）** | Auth Gateway 需 OIDC/SAML 集成 |
| 2 | 用户规模 | **20,000+** | 每用户独立容器完全不可行；需 Agent 池化 + 冬眠调度 |
| 3 | IM 平台优先 | **飞书（Feishu/Lark）** | 需飞书企业自建应用 Bot + Webhook 接入 |
| 4 | 共享 Skills | **需要** | 需 Skills Registry 服务（org-wide 只读） |
| 5 | LLM 提供商 | **内网代理** | 数据不出境，解除合规风险；需部署 LiteLLM 内网代理 |
| 6 | 基础设施 | **混合（Hybrid）** | K8s on 私有云 + 部分云托管存储 |
| 7 | 访问域名 | **待定** | 需 IT 申请内网域名 + TLS 证书（Let's Encrypt 内网 / 自签 CA）|
| 8 | 数据保留 | **3 个月** | 自动清理任务，3 个月后归档或删除会话数据 |

### 20k+ 规模的关键判断

> **当用户规模到 2 万+，"每用户一个独立容器"方案彻底失效。**
>
> 即使空闲容器占用极低，管理 20k 个独立 K8s Pod 的运维成本、存储卷管理、升级复杂度都不可接受。
> 必须引入 **Agent 池化 + 按需调度 + 状态冷热分离** 的平台层架构。

---

## 目标与成功标准

### 业务目标

1. 2 万员工通过企业 SSO 登录，获得独立 AI Agent 工作空间
2. 飞书 Bot 作为主要 IM 接入，用户在飞书群/单聊中与 Hermes 交互
3. 开发者可通过 OpenAI-compatible API（含独立 token）调用 Hermes
4. 管理员统一管控 LLM 用量、用户账号、组织级 Skills
5. 所有 LLM 调用经由内网代理，数据不出企业网络

### 成功标准

| 指标 | 目标值 |
|------|--------|
| 并发会话支持 | 500 并发（峰值估算 ~2.5% DAU）|
| Agent 冷启动时间 | < 3s（从"用户无活跃实例"到"首个 token 返回"）|
| API P95 响应时间 | < 5s（首 token，含 LLM 调用）|
| 平台可用性 | 99.5%/月（内网环境）|
| 用户数据隔离 | 100%（任意两用户互不可见）|
| 飞书消息响应时间 | < 8s（P90）|
| LLM 用量可观测 | 每用户每日 token 消耗可查，可设配额 |
| 数据自动清理 | 3 个月后自动归档 / 删除 |

---

## 用户故事

### 普通用户

**US-01 Web 登录**  
作为员工，我用企业 SSO 账号登录 `hermes.内网域名`，进入我专属的 Hermes Web 工作台，历史对话、技能、记忆只有我可见。

**US-02 飞书交互**  
作为员工，我在飞书的任意会话中 @Hermes 即可获得回复，机器人识别我的飞书身份并关联我的 Hermes 账户，会话上下文在飞书和 Web 之间可切换继续。

**US-03 API 调用**  
作为开发者，我在管理台生成我的专属 API Token，用标准 OpenAI SDK 调用 `http://hermes-api.内网域名/v1/`，结果返回格式与 OpenAI 一致。

**US-04 使用组织技能**  
作为员工，我在 Hermes 中能看到"组织技能库"（管理员维护的共享 Skills），也能创建只对自己可见的私人技能。

### 管理员

**US-05 用户管理**  
添加/禁用用户、分配角色（普通用户/Power User/Admin），查看用户活跃状态和用量。

**US-06 LLM 配额管理**  
为不同角色设置每日 token 配额，超出后请求被拒绝并提示用户联系管理员。

**US-07 组织技能管理**  
发布、更新、下架组织级 Skills，所有用户实例自动同步最新版本。

**US-08 审计日志**  
查看用户操作日志（登录、API 调用次数、LLM 调用量），支持按时间范围和用户筛选。

---

## 范围

### In Scope（本次）

- **平台控制层**：用户管理、SSO 集成、JWT Token、配额服务
- **Agent 调度层**：Agent 池化、按需调度、状态冷热分离（HERMES_HOME 挂载）
- **飞书 Bot 接入**：企业自建应用、Webhook 接收、飞书 user_id ↔ 平台 user_id 映射
- **OpenAI-compatible API**：通过平台代理，每用户独立 token，路由到对应 Agent
- **组织 Skills 注册中心**：只读共享技能仓库，个人技能独立存储
- **内网 LLM 代理**：LiteLLM 内网部署，统一出口，接入企业已有 LLM 资源
- **Web UI 认证**：SSO 登录页，现有 Hermes Web UI 通过平台层鉴权后代理展示
- **运维基础**：K8s 部署、Prometheus 指标、日志聚合、3 个月数据清理
- **管理控制台**（基础版）：用户列表、用量看板、Skills 管理、API Token 管理

### Out of Scope

- Hermes Agent 核心推理逻辑修改
- 公网 SaaS / 开放注册
- 移动端原生 App（通过飞书/Web 访问）
- 多 IM 平台同时接入（Phase 1 仅飞书）
- Hermes SQLite → PostgreSQL 迁移（Phase 1 保留 SQLite 按用户隔离）
- 计费系统

---

## 架构设计（20k+ 规模）

### 整体分层

```
┌──────────────────────────────────────────────────────┐
│  接入层 (Access Layer)                                 │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐  │
│  │  Web Portal  │  │  飞书 Bot    │  │  API Client  │  │
│  └──────┬──────┘  └──────┬───────┘  └──────┬──────┘  │
└─────────┼────────────────┼─────────────────┼──────────┘
          ▼                ▼                 ▼
┌──────────────────────────────────────────────────────┐
│  网关层 (Gateway Layer)                                │
│  Nginx/Kong: TLS 终结 + 路由 + Rate Limit             │
└─────────────────────┬────────────────────────────────┘
                      ▼
┌──────────────────────────────────────────────────────┐
│  平台控制层 (Platform Control Plane)                   │
│  ┌──────────────┐  ┌───────────────┐  ┌───────────┐  │
│  │ Auth Service │  │ Quota Service │  │  Admin    │  │
│  │ SSO+JWT+RBAC │  │ token metering│  │  Console  │  │
│  └──────┬───────┘  └───────┬───────┘  └───────────┘  │
│         │                  │                          │
│  ┌──────▼──────────────────▼────────────────────┐    │
│  │         Agent Router (核心调度)                │    │
│  │  user_id → 找/建 Agent 实例 → 路由请求         │    │
│  └──────────────────┬──────────────────────────-─┘    │
└─────────────────────┼────────────────────────────────┘
                      ▼
┌──────────────────────────────────────────────────────┐
│  Agent 执行层 (Agent Execution Layer)                  │
│                                                      │
│  Agent Pool (K8s Deployment, 弹性扩缩)               │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐      │
│  │ Agent-Pod-1│  │ Agent-Pod-2│  │ Agent-Pod-N│      │
│  │ 运行用户A  │  │ 运行用户B  │  │ 空闲/待分配│      │
│  └─────┬──────┘  └─────┬──────┘  └────────────┘      │
│        │               │                              │
│  ┌─────▼───────────────▼──────────────────────────┐   │
│  │  User Home Volume Mount (每用户独立挂载)         │   │
│  │  /homes/user-{id}/  → HERMES_HOME              │   │
│  └─────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────┘
                      ▼
┌──────────────────────────────────────────────────────┐
│  数据层 (Data Layer)                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────┐  │
│  │  PostgreSQL  │  │  NAS/NFS     │  │   Redis    │  │
│  │  (平台数据:  │  │  (per-user   │  │  (路由缓存 │  │
│  │  用户/配额/  │  │  SQLite +    │  │  + 限流)   │  │
│  │  审计/skills)│  │  memory/cfg) │  │            │  │
│  └──────────────┘  └──────────────┘  └────────────┘  │
└──────────────────────────────────────────────────────┘
                      ▼
┌──────────────────────────────────────────────────────┐
│  LLM 代理层 (内网, 数据不出境)                         │
│  LiteLLM Proxy → 企业内网 LLM / 合规外部 API           │
└──────────────────────────────────────────────────────┘
```

### Agent 调度机制（关键设计）

**核心问题**：20k 用户不能同时运行 20k 个 Hermes 进程。

**解决方案：热/冷状态分离 + Agent 池**

```
用户请求到达 Agent Router:

1. 检查 Redis: user_id → pod_id 是否存在且 pod 健康?
   ├── 是: 直接路由到该 pod (热启动, ~50ms)
   └── 否: 进入调度流程
       a. 从 Agent Pool 获取空闲 Pod
       b. 挂载该用户的 HERMES_HOME 数据卷 (或 bind mount 目录)
       c. 注入用户的 env 配置 (LLM proxy 地址, API key 等)
       d. Hermes 进程启动, 加载已有状态 (< 3s 目标)
       e. 写入 Redis: user_id → pod_id, TTL=30min
       f. 路由请求

空闲超时:
- 30 分钟无请求 → 从 Redis 移除映射, Pod 回收到空闲池
- 用户 HERMES_HOME 数据持久保留在 NAS
- 下次请求重新调度 (冷启动)
```

**Pool 规模估算（20k 用户）**：
- 假设 DAU = 30%（6,000 人）
- 峰值并发 = 500
- Pool Size = 600（含 20% buffer）
- NAS 存储 = 20k × ~500MB/用户 = ~10TB（含 3 个月数据）

### 飞书接入设计

```
飞书平台 Webhook
    ↓
Feishu Bot Service (新建)
    ├── 验证飞书签名
    ├── 提取 sender.open_id / union_id
    ├── 查询 Auth Service: feishu_union_id → platform_user_id
    │   └── (首次登录飞书时做 SSO 绑定)
    └── 构造 OpenAI-format 请求 → Agent Router → Hermes
        ↓
    异步推送飞书消息卡片（流式打印效果）
```

**关键点**：飞书 user identity 必须通过 SSO 与企业 user_id 绑定，不能依赖飞书 open_id 作为唯一凭证。

### 组织 Skills 注册中心

```
管理员发布 Skill → Skills Registry (PostgreSQL + Git 仓库)
    ↓
Agent 启动时:
    1. 挂载只读 org-skills 目录 (NAS 共享挂载)
    2. 读取 /org-skills/ 下的所有 skill
    3. 合并到 HERMES_HOME/skills/ (个人 skills 覆盖同名 org skill)
    
管理员更新 org skill → Agent Router 广播"技能热更新"信号
    → 活跃 Pod 重新加载 org-skills 目录
```

### 内网 LLM 代理

```
LiteLLM Proxy (内网部署):
  - 统一 OpenAI-compatible 接口
  - 后端: 企业内网 LLM (Qwen/Llama/etc.) + 合规外部 API
  - 用量计量回写到 Quota Service
  - 每 Pod 的 OPENAI_BASE_URL 统一指向内网 LiteLLM 地址
```

---

## 新增服务清单（需新建）

| 服务 | 技术栈 | 职责 |
|------|--------|------|
| Auth Service | FastAPI + PostgreSQL | SSO/OIDC 集成, JWT 签发, RBAC |
| Agent Router | FastAPI + Redis | 用户→Pod 路由, 调度, 会话追踪 |
| Feishu Bot Service | FastAPI | Webhook 接收, 消息推送, 身份映射 |
| Skills Registry | FastAPI + PostgreSQL + NAS | 组织技能发布/同步 |
| Quota Service | FastAPI + PostgreSQL | Token 计量, 配额检查, 告警 |
| Admin Console API | FastAPI | 用户管理, 用量查看, Skills 管理 |
| Admin Console UI | React/Next.js | 管理员前端 |
| LiteLLM Proxy | LiteLLM (开源) | 内网 LLM 统一代理 |
| 数据清理 Job | Python CronJob (K8s) | 3 个月到期数据归档/删除 |

**Hermes Agent 本身代码改动**: 最小化，仅：
- `API_SERVER_HOST` 从 `127.0.0.1` 改为 `0.0.0.0`（或环境变量控制）
- 可能需要禁用 Hermes Web UI 的直接访问（由平台层代理）

---

## 交付分阶段计划

### Phase 1 — MVP 可用（内部试点，~50 人）

**目标**：核心链路跑通，少量用户验证

- 内网 LLM 代理（LiteLLM）上线
- Auth Service：SSO 登录 + JWT，基础用户管理
- Agent Router：简化版（K8s Deployment，固定 50 个 Pod）
- Hermes Docker 镜像：支持 HERMES_HOME 环境变量挂载
- Feishu Bot：基础消息收发，open_id → user_id 绑定
- OpenAI-compatible API：per-user token → 路由
- 数据存储：NAS 目录 per-user，PostgreSQL 平台数据
- 基础监控：Prometheus + Grafana

**验收门槛**：50 个真实用户，会话隔离验证，飞书 Bot 可用

### Phase 2 — 生产就绪（全公司开放）

**目标**：弹性扩缩，全量用户

- Agent 调度：热冷分离，Pool 弹性伸缩（HPA）
- 配额系统：每用户每日 token 限额 + 超限告警
- Skills Registry：Org-wide 共享 Skills 上线
- Admin Console：完整用户管理 + 用量看板 + Skills 管理
- Web Portal：SSO 登录，代理 Hermes Web UI
- 3 个月数据自动清理 CronJob
- 文档：用户指引 + 管理员手册

### Phase 3 — 优化与扩展

- 冷启动优化（< 2s 目标）
- 多 IM 平台扩展（钉钉/企微/Slack）
- 组织 Skills 版本管理
- 成本分析 Dashboard（按部门）
- 考虑 SQLite → PostgreSQL 迁移路径评估

---

## 关键技术风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| NAS + SQLite 文件锁 | 并发写入冲突（同一用户多设备）| 每用户同时只有一个 Agent Pod；WAL 模式处理读并发 |
| 冷启动超 3s SLA | 用户体验差 | Agent Pod 预热池，保持 N 个空闲 Pod 随时可分配 |
| 飞书 Webhook 限速 | 高峰消息丢失 | 消息队列缓冲（Redis Streams）|
| LiteLLM 内网代理成为单点 | LLM 调用全部中断 | 多副本部署 + 健康检查熔断 |
| 20k 用户 NAS 存储 I/O 争用 | 访问延迟 | 分片 NAS，按 user_id hash 分配到不同挂载点 |
| Hermes Web UI 无法对外暴露 | 用户配置页面安全问题 | 平台层做 Web UI 代理时拦截危险页面（env vars 页）|
| K8s Pod 数量管理 | 资源泄漏 | TTL 自动回收，Liveness probe |

---

## 企业治理

- **应用等级**: T2（多实例、高可用、跨机房备份）
- **数据分类**: 员工工作内容，内部敏感级，不得外传
- **LLM 调用**: 全部经内网代理，不经过境外网络（已确认）
- **审计**: 所有用户操作和 LLM 调用写入审计日志，保留 3 个月
- **合规**: 管理员不得查看用户会话内容（技术层面访问控制隔离）
- **备份**: NAS 数据每日备份，PostgreSQL 每日备份，RTO < 4h

---

## 待确认项（进入 design-swarm 前需收敛）

| # | 问题 | 影响 |
|---|------|------|
| D1 | 企业 SSO 具体协议：OIDC / SAML 2.0？IdP 厂商？ | Auth Service 实现路径 |
| D2 | 飞书应用类型：企业自建应用 还是 ISV 应用？ | 权限范围和 OAuth 流程 |
| D3 | 内网 LLM 资源：有哪些可用模型和 API？ | LiteLLM 后端配置 |
| D4 | K8s 集群资源：可分配给 Hermes 的 CPU/RAM 总量？ | Pool Size 和 HPA 上限 |
| D5 | NAS 存储：已有 NAS/NFS 设备还是需要新采购？性能规格？ | 存储方案 |
| D6 | 访问域名：`hermes.内网.com` 申请进度？ | TLS 证书和 DNS |
| D7 | 管理控制台由 IT/HR 还是技术团队维护？ | UI 复杂度决策 |

---

## 当前阶段 / 就绪状态

- **当前阶段**: `requirement-challenge`  
- **目标阶段**: `design-swarm`  
- **就绪状态**: `not-ready`（待确认项 D1-D6 需在设计前收敛）
- **阻塞项**:  
  - D1（SSO 协议）是 Auth Service 实现的前置  
  - D4（K8s 资源）决定 Phase 1 Pool Size 是否可行  
  - D5（NAS 存储）是 Agent 状态持久化的基础设施前提
