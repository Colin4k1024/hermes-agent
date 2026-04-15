# ADR-001: 用户数据存储 — 保留 SQLite Per-user vs 迁移 PostgreSQL Multi-tenant

**状态**: accepted  
**日期**: 2026-04-15  
**Owner**: architect  
**关联需求**: hermes-enterprise-saas PRD  
**关联 Arch Design**: docs/artifacts/2026-04-15-hermes-enterprise-saas/arch-design.md

---

## 背景与约束

Hermes Agent 的核心数据模型建立在 per-user SQLite 数据库之上。每个用户的 `HERMES_HOME` 目录包含 `state.db`（会话、消息、agent 状态）、`response_store.db`（响应缓存）以及 `config.yaml`、`skills/`、`memories/` 等文件资产。这一设计在单用户桌面场景下运行良好——SQLite WAL 模式提供了高效的单写多读能力，且不需要外部数据库依赖。

当我们将 Hermes 扩展到 20,000+ 用户的企业 SaaS 平台时，面临一个根本性选择：**是保留每用户一个 SQLite 文件的模型，还是迁移到集中式关系型数据库（PostgreSQL）**。

**关键约束**：

1. PRD 明确要求 **Hermes Agent 核心代码不做修改**——SQLite → PostgreSQL 迁移被列为 Out of Scope。
2. Hermes 内部的数据访问层（`hermes_state.py`、`run_agent.py`、plugins 等）全部硬绑定 SQLite 接口，涉及 15+ 个文件。
3. 每用户同一时刻只有一个活跃 Agent Pod（Pod Pool 架构决策），消除了多写并发问题。
4. 数据保留策略为 3 个月，单用户数据量预估 ~500MB（含会话历史、日志、workspace）。
5. 总存储需求 ~10TB（20k × 500MB），需要网络存储方案支持。

**非目标**：

- 本 ADR 不决定存储介质（NAS vs 对象存储），存储介质选型见 ADR-004。
- 本 ADR 不讨论平台级数据（用户账号、配额、审计日志），这些已确认使用 PostgreSQL。

---

## 备选方案

### Option A: 保留 SQLite Per-user on NAS（本方案）

**描述**：每用户一个 `HERMES_HOME` 目录存放在 NAS/NFS v4 共享存储上，包含独立的 SQLite 数据库文件。Agent Pod 通过 subPath mount 访问对应用户目录。

**优点**：
- **零代码改动**：完全复用 Hermes 现有数据层，`hermes_state.py`、`run_agent.py`、所有 plugins 无需修改
- **天然隔离**：文件系统级别的用户数据隔离，不存在 SQL 层面的跨租户泄漏风险
- **运维简单**：单用户数据迁移/备份/删除就是目录级操作（`rsync`、`rm -rf`）
- **性能可控**：SQLite WAL 模式在本地文件系统上读写延迟 < 5ms，NFS v4 缓存后也在可接受范围

**风险或成本**：
- NAS I/O 争用：需要 256-shard 分片缓解
- 不支持跨用户查询：管理员统计需要在平台控制面（PostgreSQL）层单独实现
- NFS v4 依赖：必须 v4（不能 v3），需要 SSD 后端
- 单点写入约束：每用户同时只能有一个 Agent Pod

### Option B: PostgreSQL Per-user Schema

**描述**：在 PostgreSQL 中为每个用户创建独立 schema，每个 schema 内的表结构与 Hermes SQLite 表一致。

**优点**：
- 标准关系型数据库运维，备份恢复成熟
- 支持跨 schema 查询

**风险或成本**：
- **大量代码改动**：需要将 Hermes 的 SQLite 调用全部替换为 PostgreSQL，涉及 15+ 文件
- 20k schema 的 PostgreSQL 性能退化（pg_catalog 膨胀）
- 违反 PRD "核心代码不改" 约束

**不选原因**：违反核心约束，改动量和风险远超收益。

### Option C: 真正多租户 PostgreSQL（共享表 + user_id 隔离）

**描述**：所有用户共享同一组表，通过 `user_id` 列做行级隔离，配合 RLS 保证访问控制。

**优点**：
- 最标准的 SaaS 多租户模式，运维成本最低

**风险或成本**：
- **完全重写数据层**，需要重新设计所有表并重写所有数据访问代码
- RLS 一个 policy 遗漏就是跨租户数据泄漏
- 彻底违反 "核心代码不改" 约束，开发周期可能超过 3 个月

**不选原因**：改动量最大，违反核心约束，引入 RLS 泄漏风险。适合 Phase 3+ 长期重构方向。

---

## 决策结果

**采用 Option A：保留 SQLite Per-user on NAS。**

**核心原因**：

1. **零代码改动**：完全尊重 PRD 的 "Hermes Agent 核心代码不做修改" 约束。`hermes_state.py`（`get_hermes_home()` → `state.db`）、所有 plugin 数据访问、`response_store.py` 等文件均无需变更。
2. **天然安全隔离**：文件系统级隔离比 SQL RLS 更可靠，不存在忘记加 `WHERE user_id = ?` 或 RLS policy 遗漏的风险。对于处理员工工作内容（内部敏感级）的平台，这种隔离强度更符合企业安全要求。
3. **Pod Pool 架构适配**：ADR-002 确定的 Pod Pool + 热冷调度模型天然保证每用户同时最多一个 Agent Pod，消除了 SQLite 单写进程限制带来的并发问题。

**影响范围**：

- Agent Pod 需要通过 subPath mount 访问 NAS 上的用户目录
- 需要 256 shard 分片策略分散 NAS I/O
- 管理员跨用户统计功能需要在平台控制面（PostgreSQL）层单独实现
- Data Cleanup Job 需要遍历 NAS 目录执行过期数据清理

**兼容性 / 迁移影响**：

- Phase 1/2 完全兼容，无迁移需求
- Phase 3 若评估迁移到 PostgreSQL，可按以下路径推进：
  1. 先为新用户创建 PostgreSQL 后端（双写期）
  2. 编写迁移工具将 SQLite → PostgreSQL（逐用户迁移）
  3. 全量切换后下线 NAS

**失败或回退思路**：

- NAS I/O 争用严重：增加 NFS export 数量（4 → 8 → 16）水平扩展
- SQLite 文件损坏：Per-user 隔离确保影响范围只有单个用户，可从每日备份恢复
- 极端情况（NAS 不可用）：临时回退到 local PVC（每 Pod 绑定用户，牺牲调度灵活性）

---

## 企业内控补充

- **应用等级**: T2（多实例、高可用、跨机房备份）
- **数据分类**: 员工工作内容，内部敏感级，文件系统隔离满足 T2 隔离要求
- **关键组件偏离**: 未使用集团标准关系型数据库作为用户数据主存储，而是保留 SQLite on NAS。原因：Hermes 核心代码绑定 SQLite，迁移成本远超收益。平台级数据仍使用 PostgreSQL。
- **备份策略**: NAS 每日全量快照 + 增量备份，RTO < 4h
- **资产文档入口**: `docs/artifacts/2026-04-15-hermes-enterprise-saas/arch-design.md` Section 5

---

## 后续动作

| 动作 | Owner | 完成条件 |
|------|-------|---------|
| 确认 NAS 存储规格和 NFS v4 支持（D5） | devops-engineer | NAS 设备型号、NFS v4 配置确认 |
| 设计 256-shard 分片方案并验证 I/O 分布 | architect | 分片策略文档 + 模拟数据测试 |
| 实现 Data Cleanup CronJob | backend-engineer | 3 个月过期数据清理脚本 + 测试 |
| Phase 3 迁移路径评估（可选） | architect | SQLite → PostgreSQL 迁移方案文档 |
| 同步到 Delivery Plan | project-manager | delivery-plan.md 更新 |
