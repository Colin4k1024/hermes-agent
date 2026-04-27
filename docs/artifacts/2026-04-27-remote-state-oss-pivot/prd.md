# PRD: Remote State Storage — PostgreSQL to OSS Migration

## 1. 背景与动机

**当前架构**: State Service 使用 PostgreSQL 存储所有远程状态（会话、消息、内存、配置、缓存元数据、审计日志），共 6 张表，完整 ACID 事务和关系查询能力。

**变更诉求**: 用户要求评估将远程状态存储从 PostgreSQL 迁移到 OSS（对象存储），以降低成本或简化运维。

**初步分析结论** (来自技术调研):

| 数据类型 | 当前存储 | OSS 适用性 | 备注 |
|----------|----------|-------------|------|
| 会话元数据 (state_sessions) | PostgreSQL | ❌ 不适用 | 需关系查询、tenant_id 过滤、索引 |
| 消息内容 (state_messages.content) | PostgreSQL TEXT | ✅ 可迁移 | 大文本，可存为 OSS blob |
| 消息元数据 | PostgreSQL | ❌ 不适用 | 需按 session_id + timestamp 范围查询 |
| 长期记忆 (state_memory.value) | PostgreSQL TEXT | ✅ 可迁移 | 大文本，可存为 OSS blob |
| 记忆元数据 | PostgreSQL | ❌ 不适用 | 需 namespace + key 唯一约束 |
| 缓存对象 (state_cache_metadata.object_uri) | PostgreSQL + OSS 指针 | ⚠️ 已是混合态 | OSS URI 存在 PG，对象在 OSS |
| 审计日志 (state_audit_events) | PostgreSQL | ❌ 不适用 | append-only 约束，PG 可用 DENY DELETE 保护 |
| 配置 (state_user_configs) | PostgreSQL | ❌ 不适用 | 需 key 唯一性，scope 继承合并逻辑 |

**核心问题**: OSS 是 blob 存储，不支持关系查询、唯一约束、索引、软删除、append-only 审计保护。无法作为 PostgreSQL 的直接替代品。

---

## 2. 目标与成功标准

### 2.1 候选方案

**方案 A — 混合架构（✅ 已确认采纳）**
- PostgreSQL: 元数据、索引、软删除标志、审计日志
- OSS: 大字段内容（message.content、memory.value）
- 收益: 降低 PG 存储成本，保留关系查询能力
- 风险: 两套存储的一致性维护，迁移复杂度

**方案 B — 全 OSS 迁移（❌ 不推荐）**
- 全部迁移到 OSS，元数据索引用 DynamoDB/etcd 等补充
- 收益: 单一存储后端
- 风险: 需重建查询层，架构大幅重构，时间和风险极高

**方案 C — 放弃迁移，维持 PostgreSQL（降级方案）**
- 评估成本后认为 PG 托管服务足够，无需迁移

### 2.2 成功标准（已确认）

- [x] ~~明确迁移目标~~ → 降低 PG 存储成本 60-70%（大文本移至 OSS）
- [x] ~~确定候选 OSS 厂商~~ → 阿里云 OSS（优先），MinIO（备选）
- [x] ~~确定候选 OSS 厂商~~ → 混合架构（PG 元数据 + OSS 内容）
- [x] ~~确定混合架构下一致性保障机制~~ → 两阶段写入 + 最终一致性补偿
- [x] ~~确定数据保留策略~~ → OSS Standard（热）+ Glacier（冷）分层
- [ ] 迁移窗口和数据迁移方案（蓝绿部署 + 双写策略）
- [ ] 兼容性: 现有 RemoteStateStore 调用方式不变
- [x] 审计日志保护 → OSS Object Lock COMPLIANCE 模式（WORM 存储）

---

## 3. 用户故事

| 作为... | 我希望... | 以便... | 验收标准 |
|---------|----------|---------|---------|
| Tenant Admin | 我的会话数据存储成本降低 50%+ | 降低 SaaS 运营成本 | 按用量计费，存储成本可量化 |
| End User | 我的对话历史持久化不变 | 继续跨设备恢复会话 | 会话查询、搜索功能不受影响 |
| DevOps | 减少数据库运维负担 | 聚焦核心业务 | 无需管理 PG 高可用、备份、升级 |
| Security | 审计日志不可删除 | 满足合规要求 | OSS Object Lock 保护，WORM 存储 |

---

## 4. 范围

### In Scope
- State Service 远程状态存储后端架构评估
- 候选方案 A 详细设计（混合架构）
- 数据迁移方案规划（蓝绿部署 + 双写策略）
- OSS Object Lock 审计日志保护设计

### Out of Scope
- 实际的 OSS 集成实现（本次仅为 intake + 评估）
- Gateway 或 Router 的改动
- 其他微服务的存储变更

---

## 5. 风险与依赖

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| OSS 不支持关系查询 | message.content 在 OSS，无法按内容搜索 | 搜索走 PG 元数据索引，content 不参与搜索 |
| 混合架构一致性 | message content 在 OSS 但元数据在 PG | 两阶段写入：①写 OSS ②写 PG；补偿任务处理不一致 |
| 数据迁移窗口 | 迁移期间服务不可用或数据不一致 | 蓝绿部署 + 双写策略，零停机迁移 |
| 审计日志不可删除约束 | PG 的 DENY DELETE 在 OSS 无法实现 | OSS Object Lock COMPLIANCE 模式 = 金融级 WORM |
| RemoteStateStore 接口契约 | 现有调用方无需改动 | 明确接口兼容性要求，State Service 内部封装 OSS 访问 |

---

## 6. 需求挑战结论（已确认）

### 决策确定项

1. **迁移动机**: 降低 PG 存储成本 60-70%（大文本移至 OSS）
2. **OSS 厂商**: 阿里云 OSS（优先），MinIO（备选多云场景）
3. **架构方案**: 混合架构（PG 元数据 + OSS Blob），message.content 和 memory.value 迁移到 OSS
4. **数据保留**: OSS Standard（热数据）+ Glacier（冷数据，90天后自动转存）
5. **迁移策略**: 蓝绿部署 + 双写策略，零停机迁移
6. **审计日志保护**: OSS Object Lock COMPLIANCE 模式（WORM 存储）

### 待实施项

- [ ] 提供实际数据量级（用于最终成本建模）
- [ ] 确定迁移时间窗口
- [ ] 设计双写一致性补偿机制
- [ ] 定义 OSS Bucket 结构和 Object Key 命名规范

---

## 7. 混合架构详细设计

### 7.1 数据分层

```
┌─────────────────────────────────────────────────────┐
│                    PostgreSQL                        │
│  ─────────────────────────────────────────────────  │
│  state_sessions: id, tenant_id, user_id,            │
│    session_id, title, model, create_time, ...       │
│  ─────────────────────────────────────────────────  │
│  state_messages: id, session_id, role, token_count, │
│    finish_reason, created_at, ...                   │
│    ⚠️ content 字段移除，改为 object_uri 指针         │
│  ─────────────────────────────────────────────────  │
│  state_memory: namespace, key, metadata,            │
│    created_at, updated_at, ...                      │
│    ⚠️ value 字段移除，改为 object_uri 指针           │
│  ─────────────────────────────────────────────────  │
│  state_audit_events: id, tenant_id, event_type,    │
│    actor, object_id, payload, created_at, ...       │
│  ─────────────────────────────────────────────────  │
│  state_user_configs: id, tenant_id, user_id,        │
│    config_key, config_value, scope, ...              │
└─────────────────────────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
    ┌──────────┐   ┌──────────┐   ┌──────────┐
    │   OSS    │   │   OSS    │   │   OSS    │
    │ Bucket   │   │ Bucket   │   │ Bucket   │
    │ messages │   │ memory   │   │ audit    │
    └──────────┘   └──────────┘   └──────────┘
```

### 7.2 OSS Object Key 规范

```
# Message content
messages/{tenant_id}/{session_id}/{message_id}/{timestamp}.json

# Memory value
memory/{tenant_id}/{namespace}/{key}/{timestamp}.json

# Audit events (with Object Lock)
audit/{tenant_id}/{event_id}/{timestamp}.json
```

### 7.3 一致性保障

**两阶段写入**：
1. 写入 OSS → 获取 object_uri
2. 写入 PG 元数据 + object_uri
3. 补偿任务：定期比对 OSS 和 PG，发现不一致时告警并修复

---

## 8. UI/UX 范围

**无前端变更** — 本次为后端存储架构变更，对最终用户不可见。

---

## 9. 候选技能包

- `doc-architecture`: 用于补齐现有架构图和模块边界
- `database-reviewer`: PostgreSQL → OSS 迁移的数据库专项评审

---

## 10. 下一步

1. ~~召开需求挑战会，确认上述 6 个关键问题~~ ✅ 已确认
2. 进入 `/team-plan` 创建 delivery-plan
3. 如决定推进，创建 `arch-design.md` 记录混合架构方案
