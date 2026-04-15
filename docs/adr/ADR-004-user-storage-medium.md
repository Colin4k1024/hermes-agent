# ADR-004: 用户存储介质 — NAS/NFS v4 vs 对象存储（MinIO/S3）vs 本地 PVC

**状态**: accepted  
**日期**: 2026-04-15  
**Owner**: architect  
**关联需求**: hermes-enterprise-saas PRD  
**关联 Arch Design**: docs/artifacts/2026-04-15-hermes-enterprise-saas/arch-design.md

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
