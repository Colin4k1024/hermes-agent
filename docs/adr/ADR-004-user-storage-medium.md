# ADR-004: 用户存储介质 — NAS/NFS v4 vs 对象存储（MinIO/S3）vs 本地 PVC

**状态**: accepted
**日期**: 2026-04-15
**更新**: 2026-04-16（增加 NFS Subdir External Provisioner 方案）
**Owner**: architect
**关联需求**: hermes-enterprise-saas PRD
**关联 Arch Design**: docs/artifacts/2026-04-15-hermes-enterprise-saas/arch-design.md

> **更新（2026-04-16）**：原 `hostPath + subPath` 方案在多 Node K8s 集群中存在调度限制。确认方案为 **NFS Subdir External Provisioner + StorageClass**，每用户独立 PVC，Pod 调度完全自由。

---

## 背景与约束

ADR-001 决定保留 SQLite Per-user 文件模型。本 ADR 进一步决定这些文件存储在什么介质上。

**存储需求**：

- 20,000 用户 × ~500MB/用户 = ~10TB 总量
- SQLite 要求 POSIX 文件锁语义（`fcntl()` advisory locking）
- SQLite WAL 模式要求写入者和数据库文件在同一文件系统上
- Pod Pool 架构下，同一用户的数据需要能被不同的 Agent Pod 访问

**关键约束**：

1. SQLite 对存储介质有严格的 POSIX 文件锁要求
2. Pod Pool 中任意 Pod 都可能服务任意用户，数据不能绑定 Pod
3. 需要支持 256-shard 分片策略
4. 网络存储延迟需要 < 50ms（NFS v4 缓存后 < 5ms）

---

## 备选方案

### Option A: NAS / NFS v4（本方案）

**描述**：企业 NAS 设备通过 NFS v4 协议挂载到 K8s Node，Agent Pod 通过 hostPath + subPath 访问 `/nas/hermes-homes/{shard}/user-{id}/`。

**优点**：
- **SQLite 文件锁兼容**：NFS v4 支持 `fcntl()` advisory locks，是唯一能正确支持 SQLite WAL 模式的网络文件系统协议
- **POSIX 语义完整**：目录操作、文件读写、锁机制与本地文件系统一致
- **任意 Pod 可访问**：所有 K8s Node 挂载同一 NFS export，任意 Pod 都能访问任意用户目录
- **运维简单**：目录级备份（NAS 快照）、迁移（`rsync`）、删除（`rm -rf`）

**风险或成本**：
- **NFS v4 版本强制要求**：NFS v3 的文件锁实现（NLM 协议）不可靠，SQLite 在 NFS v3 上可能静默损坏数据
- **I/O 争用**：20k 用户目录的并发元数据操作可能导致 NFS server 压力。缓解：256-shard + 可选 4 NFS export
- **基础设施依赖**：需要 D5 确认 NAS 设备可用、NFS v4 支持、SSD 后端

### Option B: 对象存储（MinIO / S3）

**描述**：用户文件存储在 S3-compatible 对象存储中，Agent Pod 启动时 sync 到 local ephemeral storage，关闭时 sync 回去。

**优点**：无限扩展能力，成本低（HDD tier），内置多副本。

**风险或成本**：
- **SQLite 根本不兼容**：对象存储不支持 POSIX 文件锁，也不支持原地更新（每次写入是全量 PUT）
- **sync 机制复杂且危险**：Pod 异常退出时 sync 未完成导致数据丢失
- **冷启动延迟大增**：下载 500MB 需要 5–10s，远超 3s SLA
- **并发冲突**：sync 过程中并发请求可能导致数据分叉

**不选原因**：SQLite 与对象存储从根本上不兼容。要使用对象存储，必须先完成 SQLite → PostgreSQL 迁移（ADR-001 已排除）。

### Option C: 本地 PVC（每 Pod 一个 Persistent Volume Claim）

**描述**：每个 Agent Pod 绑定一个 K8s PVC（local SSD 或 cloud disk）。

**优点**：本地 SSD 性能最佳（< 0.1ms 延迟），SQLite 完美兼容。

**风险或成本**：
- **与 Pod Pool 架构完全矛盾**：ADR-002 选定 Pod Pool + 热冷调度，同一 Pod 需要服务不同用户。PVC 绑定到 Pod 意味着用户数据无法在 Pod 之间迁移
- **20k PVC 管理不可行**：K8s 管理 20k PVC 的开销与管理 20k Pod 一样不可接受
- **存储浪费**：600 个 Pod × 500MB PVC = 300GB，但无法存储 20k 用户的实际总量（~10TB）

**不选原因**：与 Pod Pool 调度架构根本冲突——用户数据必须能被任意 Pod 访问，PVC 做不到这一点。

---

## 决策结果

**采用 Option A：NAS / NFS v4 作为用户存储介质。**

**核心原因**：

1. **唯一兼容 SQLite WAL 的网络存储方案**：NFS v4 是目前唯一在网络文件系统层面正确实现 `fcntl()` advisory locking 的协议。SQLite 官方文档明确指出 NFS v4 是网络存储场景的推荐选项（v3 不推荐）。
2. **与 Pod Pool 架构天然适配**：所有 K8s Node 挂载同一 NFS export，任意 Agent Pod 通过 hostPath subPath 即可访问任意用户目录，Pod 回收和重新分配不需要数据迁移。
3. **运维模型简单可靠**：用户数据的备份、迁移、删除都是目录级操作，与 NAS 自身的快照、复制能力天然结合。

**NFS v4 配置要点**：

| 配置项 | 值 | 原因 |
|--------|-----|------|
| NFS 版本 | v4.1 或 v4.2 | v3 的 NLM 锁不可靠 |
| mount option | `vers=4.1,noatime,rsize=1048576,wsize=1048576` | 大块读写，禁用 atime 减少元数据更新 |
| lock type | `local_lock=none` | 使用 NFS server-side lock |
| backend | SSD tier | 保证 SQLite random read < 5ms |
| export 数量 | 初始 1 个，可扩展到 4 个 | 按 shard range 分配 |

**影响范围**：

- 所有 K8s Node 需要安装 NFS v4 client 并配置 mount
- Agent Pod 的 volume mount 配置需要支持 subPath（动态路径）
- NAS 设备需要 SSD 后端、10TB 可用空间、支持快照和异步复制
- 需要监控 NFS server IOPS、延迟和连接数

**兼容性 / 迁移影响**：

- 对 Hermes Agent 代码零影响——只要 `HERMES_HOME` 指向有效的 POSIX 路径即可
- 如果未来扩展到 50k+ 用户且 NAS I/O 成为瓶颈，可评估分布式文件系统（CephFS）

**失败或回退思路**：

- NAS 设备故障：从最近快照恢复（RTO < 4h），期间平台降级但不丢数据
- NFS 连接中断：Agent Router 检测到 Pod health 异常后停止路由，等待 NFS 恢复
- NFS v4 不可用（D5 确认结果不符）：紧急方案是 CephFS（也支持 POSIX 文件锁），需要额外部署 Ceph 集群
- I/O 争用严重：增加 NFS export 数量（4 → 8），将 256 shard 分配到更多 export

---

## 附录 A: 分片策略详解

### A.1 分片算法与分配规则

**分片键选择**：`shard = sha256(user_id).hex()[:2]`

- 生成 256 个桶（`00`–`ff`），每桶 ~78 用户（20,000 / 256）
- `user_id` 为平台 UUID（由 Auth Service 生成），天然具备唯一性和随机性
- 分片数在部署后**不可变更**（否则需要数据迁移），设计时按 50k 用户预留

**目录结构映射**：

```
/nas/hermes-homes/{shard}/
└── user-{user_id}/
    ├── config.yaml
    ├── .env
    ├── state.db / state.db-wal / state.db-shm
    ├── response_store.db
    ├── skills/
    ├── memories/
    ├── sessions/
    ├── logs/
    ├── hooks/
    ├── cron/
    ├── workspace/
    └── home/
```

**分片与 NFS export 的对应关系（可选扩展）**：

| 阶段 | Export 数量 | 每 Export 用户数 | 挂载方式 |
|------|-----------|----------------|---------|
| Phase 1–2 | 1 | 20,000 | 所有 Node 挂载同一 NFS server:/export/hermes-homes |
| Phase 3+ | 4 | 5,000 | 按 shard range 分配到不同 NFS export |
| 未来扩展 | 16 | 1,250 | 每 16 个 shard 对应 1 个 NFS export |

**扩展步骤**（4 export → 更多 export）：
1. 新增 NFS server/export 并配置到 K8s Node
2. 更新 Pod spec 的 volume mount（条件注解，`shard < "40"` → export-1，以此类推）
3. 分批迁移 shard 数据（`rsync -a /nas/{shard}/ /new_export/{shard}/`）
4. 旧 export 下线，数据清理

### A.2 分片与 Pod 分配的解耦

分片仅影响 **NAS 路径**，与 Pod Pool 的 HPA 调度**完全无关**：
- 任意 Pod 可以服务任意 shard 的用户
- Router 在 `/internal/prepare` 时注入 `hermes_home_path = /nas/hermes-homes/{shard}/{user_id}`
- Pod 通过 `hostPath` + subPath 访问：`/nas/hermes-homes/00/user-a1b2c3d4`

### A.3 分片元数据管理

| 元数据 | 存储位置 | 说明 |
|--------|---------|------|
| `users.nas_shard` | PostgreSQL users 表 | 创建用户时由 Auth Service 计算写入 |
| 用户目录所有权 | NAS filesystem | 属主 `nobody:nobody`（NFS anon） |
| 分片目录权限 | NFS export | `755` 目录 / `600` 文件 |
| 分片统计监控 | Prometheus exporter | 每 shard 的目录数、容量、文件数 |

---

## 附录 B: 备份与恢复策略

### B.1 备份层级

```
┌─────────────────────────────────────────────────────────────┐
│  L0: NAS 快照（每日快照，保留 30 天）                        │
│      由 NAS 设备执行（计划快照或 CDP），不影响 Pod 性能       │
├─────────────────────────────────────────────────────────────┤
│  L1: NAS 异步复制（每 4 小时，增量，跨机房）                 │
│      目标 NAS（或对象存储归档桶），RPO ≤ 4h                  │
├─────────────────────────────────────────────────────────────┤
│  L2: PostgreSQL 备份（每日全量 + WAL 连续归档）              │
│      平台元数据（用户、Token、配额、Skills）：pg_dump + WAL  │
├─────────────────────────────────────────────────────────────┤
│  L3: Redis RDB 快照（每小时，RDB 文件备份）                 │
│      路由表、会话锁、限流计数器：BGSAVE + 归档               │
└─────────────────────────────────────────────────────────────┘
```

### B.2 快照与恢复流程

**NAS 快照恢复（RTO < 4h）**：
1. 识别故障时间点 T（从监控告警或最后一次正常快照）
2. 在目标 NAS 上选择 ≤ T 的最新快照
3. 若为单 NAS 故障：将快照克隆到新卷；若为误删除：恢复快照目录
4. 验证：`sqlite3 state.db "PRAGMA integrity_check;"`
5. 通知 Router 逐步恢复 Pod 调度

**跨机房切换（RPO < 4h，数据丢失 ≤ 4h）**：
1. 触发故障转移：DNS 切换 + NFS mount 指向灾备 NAS
2. 验证数据完整性（随机抽检 10 个用户目录的 SQLite integrity_check）
3. 恢复 Pod 调度

**误删除恢复（< 30 天）**：
1. NAS 快照中找到误删除目录（保留 30 天快照）
2. `cp -a` 恢复到原路径
3. 通知受影响用户在 Hermes 中刷新状态

### B.3 备份验证

| 验证项 | 频率 | 方式 | Owner |
|--------|------|------|-------|
| SQLite integrity on snapshot | 每次快照后 | `PRAGMA integrity_check` 抽样 5% 目录 | devops |
| 快照可挂载恢复 | 每月 | 在测试环境恢复最近快照 | devops |
| 跨机房复制数据一致性 | 每日 | rsync dry-run + checksum 对比 | devops |
| PostgreSQL 备份可恢复 | 每周 | 在测试环境 `pg_restore --dry-run` | devops |
| Redis RDB 备份完整性 | 每日 | `redis-cli --rdb` vs `INFO` 对比 key count | devops |

### B.4 容量规划

| 数据类型 | 单用户大小 | 20k 用户总量 | 增长率 | 峰值（1 年） |
|---------|----------|------------|--------|------------|
| SQLite state.db | ~50MB（含 WAL） | ~1TB | 5MB/用户/月 | ~1.6TB |
| Sessions/Messages | ~200MB | ~4TB | 10MB/用户/月 | ~6.4TB |
| Memories | ~50MB | ~1TB | 2MB/用户/月 | ~1.3TB |
| Logs | ~100MB | ~2TB | 5MB/用户/月 | ~3.2TB |
| Workspace | ~100MB | ~2TB | — | ~2TB |
| **合计** | **~500MB** | **~10TB** | **~22MB/用户/月** | **~14.5TB** |

**预留 buffer**: 15%（元数据开销、碎片、快照差异）→ 规划 **17TB 可用**

### B.5 备份时间窗口

NAS 快照：每日 02:00 UTC（低峰期），不影响业务。  
PostgreSQL 全量：`pg_dump` 每日 01:00 UTC，耗时 < 30min（~500MB schema）。  
Redis RDB：`BGSAVE` 每小时，< 1min（~10MB RDB 文件）。  
删除作业（CronJob）：每日 03:00 UTC，分批限速 50MB/s，避免与快照争抢 I/O。

---

## 企业内控补充

- **应用等级**: T2，NAS 需要 RAID 保护 + 每日快照 + 跨机房异步复制
- **数据分类**: 员工工作内容，内部敏感级，NAS 访问权限限制在 hermes-agents 命名空间
- **关键组件偏离**: NFS v4 是标准企业基础设施组件，无偏离
- **存储预算**: ~10TB SSD NAS，需纳入基础设施采购计划
- **资产文档入口**: `docs/artifacts/2026-04-15-hermes-enterprise-saas/arch-design.md` Section 4.4

---

## 后续动作

| 动作 | Owner | 完成条件 |
|------|-------|---------|
| 确认 NAS 设备规格、NFS v4 支持、SSD 后端（D5） | devops-engineer | 设备确认 + 测试环境 NFS v4 mount 成功 |
| SQLite on NFS v4 兼容性验证 | backend-engineer | 在目标 NAS 上运行 SQLite WAL 并发读写压力测试 |
| K8s Node NFS mount 配置和 Pod subPath 方案 | devops-engineer | Helm chart + 测试验证 |
| NAS 监控接入 Prometheus（IOPS、延迟、连接数） | devops-engineer | Grafana dashboard |
| NAS 备份策略确认（快照频率、异步复制目标） | devops-engineer | 备份 SOP 文档 |
| 同步到 Deployment Context | devops-engineer | deployment-context.md 更新 |
