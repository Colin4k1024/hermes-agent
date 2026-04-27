# Delivery Plan: Remote State Storage — PostgreSQL to OSS Migration

## 版本信息

| 字段 | 内容 |
|------|------|
| 版本 | v0.1 |
| 日期 | 2026-04-27 |
| 状态 | draft |
| 主责角色 | backend-engineer |
| 关联 PRD | `docs/artifacts/2026-04-27-remote-state-oss-pivot/prd.md` |

---

## 1. 版本目标

### 1.1 范围说明

**目标**：将 State Service 的 message.content 和 memory.value 从 PostgreSQL 迁移到 OSS（阿里云 OSS），采用混合架构（PG 元数据 + OSS Blob）。

**迁移范围**：
- state_messages.content → OSS
- state_memory.value → OSS
- PG Schema 变更：移除 content/value 字段，添加 object_uri 字段
- 新增 OSS 客户端封装（state_service 内部使用）
- 双写 + 补偿一致性机制
- OSS Object Lock 配置（审计日志 WORM 存储）

**非迁移范围**：
- state_sessions（元数据保留在 PG）
- state_audit_events（仅配置 Object Lock 保护，不迁移）
- state_user_configs（元数据保留在 PG）
- state_cache_metadata（已是混合态，OSS URI 在 PG）

### 1.2 放行标准

- [ ] 所有现有 RemoteStateStore 调用方式不变（向后兼容）
- [ ] 双写期间无数据丢失
- [ ] 补偿任务能检测并修复 OSS/PG 不一致
- [ ] 审计日志满足 WORM 存储要求
- [ ] 成本降低 60-70%（以实际数据量验证）

---

## 2. 工作拆解

### Phase 1: 设计阶段（1 周）

| 工作项 | 主责 | 依赖 | 计划时间 |
|--------|------|------|----------|
| 详细架构设计（arch-design.md） | architect | PRD | Week 1 |
| OSS Bucket 和 Object Key 规范定义 | backend-engineer | PRD | Week 1 |
| PG Schema 变更设计（migration script） | backend-engineer | arch-design | Week 1 |
| 双写一致性机制设计 | backend-engineer | arch-design | Week 1 |
| 成本建模（基于实际数据量） | tech-lead | 数据量级确认 | Week 1 |

### Phase 2: 开发阶段（2-3 周）

| 工作项 | 主责 | 依赖 | 计划时间 |
|--------|------|------|----------|
| OSS 客户端封装（state_service 内部） | backend-engineer | Phase 1 | Week 2 |
| PG Schema 迁移脚本（content → object_uri） | backend-engineer | OSS 客户端 | Week 2 |
| 双写逻辑实现（写 OSS + 写 PG） | backend-engineer | OSS 客户端 | Week 2 |
| 补偿任务实现（OSS/PG 不一致检测） | backend-engineer | 双写逻辑 | Week 3 |
| OSS Object Lock 配置（审计日志） | devops | Phase 1 | Week 3 |
| 读路径改造（优先读 OSS，fallback PG） | backend-engineer | 双写逻辑 | Week 3 |

### Phase 3: 迁移阶段（1 周）

| 工作项 | 主责 | 依赖 | 计划时间 |
|--------|------|------|----------|
| 历史数据迁移（message.content） | backend-engineer + devops | Phase 2 | Week 4 |
| 历史数据迁移（memory.value） | backend-engineer + devops | Phase 2 | Week 4 |
| 双写验证和流量切换 | backend-engineer + devops | 历史迁移 | Week 4 |
| 监控和告警配置 | devops | Phase 2 | Week 4 |

### Phase 4: 验证阶段（1 周）

| 工作项 | 主责 | 依赖 | 计划时间 |
|--------|------|------|----------|
| 集成测试 | qa-engineer | Phase 3 | Week 5 |
| 性能测试（对比 PG-only 基线） | qa-engineer | Phase 3 | Week 5 |
| 成本验证 | tech-lead | 实际使用数据 | Week 5 |
| 回滚演练 | devops | 迁移完成 | Week 5 |

---

## 3. 风险与缓解

| 风险 | 影响 | 缓解措施 | Owner |
|------|------|----------|-------|
| 双写一致性失败 | 数据丢失 | 补偿任务 + 告警 + 回滚方案 | backend-engineer |
| 历史数据迁移时间长 | 迁移窗口超限 | 分批迁移 + 增量迁移策略 | backend-engineer |
| OSS 访问延迟影响 SLA | 响应时间增加 | 优先读本地缓存 + 异步写入 | backend-engineer |
| Object Lock 配置错误 | 审计日志无法写入 | 预发布环境验证 + 门禁检查 | devops |
| 成本低估 | 超预算 | 基于实际数据量建模 + 上线后复核 | tech-lead |

---

## 4. 节点检查

| 节点 | 进入条件 | 验证方式 |
|------|----------|----------|
| 方案评审 | arch-design.md 完成 | tech-lead + architect 评审 |
| 开发完成 | OSS 客户端 + 双写 + 补偿任务完成 | 代码审查 + 单元测试 |
| 测试完成 | 集成测试 + 性能测试通过 | qa-engineer 报告 |
| 发布准备 | 回滚演练成功 + 监控就绪 | devops + tech-lead 确认 |

---

## 5. 成本估算

### 5.1 阿里云 OSS 成本

假设（待确认实际数据量）：
- 日活用户：2000
- 每用户日均消息：50 条
- 每条消息 content 平均：10 KB
- 每用户 memory 平均：100 KB

```
月度数据量：
messages: 2000 × 50 × 30 × 10 KB = 30 GB/月
memory: 2000 × 100 KB × 30 = 6 GB/月
audit: 忽略（已存在）
总计: 约 36 GB/月（热数据）

OSS Standard: 0.5 元/GB/月 × 36 GB = 18 元/月
OSS Glacier: 0.12 元/GB/月 × 36 GB = 4.3 元/月（90天后冷存）

对比 PostgreSQL 托管（约 500 元/月 500GB）：
成本降低约 95%（仅存储部分）
```

---

## 6. 回滚方案

| 阶段 | 回滚触发条件 | 回滚方式 |
|------|--------------|----------|
| 双写阶段 | OSS 写入失败率 > 1% | 关闭双写，退回 PG-only |
| 读切换阶段 | OSS 读取失败率 > 1% | 退回优先读 PG |
| 迁移完成后 | 任何严重问题 | 恢复 PG 大字段 + 恢复写入 |

---

## 7. 监控指标

| 指标 | 告警阈值 | 用途 |
|------|----------|------|
| OSS 写入成功率 | < 99.9% | 双写健康度 |
| OSS/PG 不一致数量 | > 100 条/小时 | 补偿任务告警 |
| OSS 读取延迟 P99 | > 500ms | 性能监控 |
| OSS 存储总量 | 增长异常 | 容量监控 |
