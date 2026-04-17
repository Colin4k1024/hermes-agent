# ADR-005: 飞书集成架构 — 独立 Bot Service vs 复用 Hermes Gateway

**状态**: accepted
**日期**: 2026-04-15
**更新**: 2026-04-16（增加 Redis Streams 双向 Channel 路由方案）
**Owner**: architect
**关联需求**: hermes-enterprise-saas PRD
**关联 Arch Design**: docs/artifacts/2026-04-15-hermes-enterprise-saas/arch-design.md

---

## 背景与约束

Hermes Agent 已内置飞书集成能力：`gateway/platforms/feishu.py` 实现了飞书消息接收、lark_oapi SDK 调用、消息卡片渲染等功能。在单用户桌面场景下，每个用户运行自己的 Hermes Gateway 进程，其中包含一个飞书 platform 实例。

在 20k 用户企业 SaaS 平台中，飞书集成面临根本性架构约束：

1. **飞书企业自建应用只支持一个 Webhook URL**：所有用户的飞书消息都会发送到这一个 URL
2. **20k 用户不能有 20k 个飞书 gateway 进程**：飞书只往一个地址发消息，无法路由到 600 个不同的 Pod
3. **飞书 Webhook 有 3 秒超时限制**：如果回调处理超过 3 秒，飞书平台会重发消息（最多 5 次）。而 LLM 响应通常需要 5–30 秒
4. **身份映射**：飞书消息中的 `sender.union_id` 需要映射到平台的 `user_id` 才能路由到正确的 Agent Pod

**关键约束**：

- D2: 假设为企业自建应用（非 ISV）
- 飞书 Webhook 3s 超时是平台硬限制，无法协商
- 需要支持首次使用时的身份绑定流程
- 消息去重必须可靠（飞书重发机制）

---

## 备选方案

### Option A: 复用 Hermes 现有 `gateway/platforms/feishu.py`（每用户一个飞书 gateway 进程）

**描述**：每个 Agent Pod 启动时同时启动 Hermes Gateway 的飞书 platform，各自监听飞书消息。

**优点**：零新建代码，完全复用 Hermes 现有 feishu.py。

**风险或成本**：
- **根本不可行**：飞书企业自建应用只有一个 Webhook URL，不可能路由到 600 个不同的 Pod。飞书消息中只有 `sender.union_id`，没有 Pod 路由信息
- **20k 个飞书 Bot 应用不现实**：不可能在飞书开放平台注册 20k 个独立 Bot
- **资源浪费**：600 个 Pod 都运行飞书 gateway 进程，但只有收到消息时才有用

**不选原因**：飞书企业应用的单 Webhook URL 限制使此方案从根本上不可行。

### Option B: 新建独立 Feishu Bot Service + Redis Streams 异步解耦（本方案）

**描述**：新建一个独立的 Feishu Bot Service（FastAPI，2 副本），作为飞书企业应用的唯一 Webhook 接收端点：

1. 接收所有飞书事件（签名验证）
2. 提取 `sender.union_id` → 查询 Auth Service 获取 `platform_user_id`
3. 将消息写入 Redis Streams（`feishu:inbound`），**立即返回 200 给飞书**（< 100ms）
4. 消费者从 Redis Streams 读取消息，调用 Agent Router 路由到对应 Agent Pod
5. 收到 Agent 响应后，调用飞书 REST API 发送回复消息卡片

**优点**：
- **解决飞书 3s 超时问题**：Webhook handler 只做签名验证和入队，< 100ms 返回 200
- **统一入口**：所有飞书消息进入同一个 Service，通过 `union_id → user_id` 映射路由
- **消息去重**：Redis Streams 结合飞书事件的 `header.event_id` 做幂等检查
- **复用消息格式化逻辑**：复用 feishu.py 中的消息卡片渲染逻辑和 lark_oapi SDK 调用模式
- **可水平扩展**：消费者组模式，多个 consumer 并行处理不同用户的消息

**风险或成本**：
- 需要新建 Feishu Bot Service（~1 周开发）
- 异步模型增加了消息链路复杂度（入队 → 消费 → 路由 → 回复）

**消息去重策略**：

```
飞书事件到达 Feishu Bot Service:

1. 提取 header.event_id（飞书为每个事件分配的唯一 ID）
2. Redis: SETNX dedup:feishu:{event_id} 1 EX 300
   ├── 成功（首次）: 继续处理
   └── 失败（重复）: 返回 200，跳过处理
3. XADD feishu:inbound * user_id {uid} message {msg} chat_id {cid} event_id {eid}
4. 返回 200 给飞书
```

5 分钟 TTL（300s）覆盖了飞书最多 5 次重发的时间窗口。

**用户首次使用飞书 Bot 的身份绑定流程**：

```
1. 员工在飞书 @Hermes "你好"
2. Feishu Bot Service:
   a. 验证飞书签名 ✓
   b. 提取 sender.union_id = "on_xxx"
   c. 调用 Auth: GET /auth/user/by-feishu-id?union_id=on_xxx → 404
3. Bot 回复消息卡片:
   ┌───────────────────────────────────┐
   │  🔗 Hermes 账号绑定               │
   │  您尚未绑定 Hermes 账号。          │
   │  请点击下方按钮完成绑定:           │
   │  [绑定我的 Hermes 账号]            │
   │  → hermes.internal/auth/feishu-bind│
   │    ?union_id=on_xxx&nonce=abc123   │
   └───────────────────────────────────┘
4. 员工点击 → Web SSO 登录 → Auth Service:
   a. 验证 nonce（防伪造，5 分钟有效）
   b. 将 feishu_union_id 写入 users.feishu_union_id
5. 员工再次在飞书 @Hermes → 查询 Auth 200 → 正常路由
```

### Option C: WebSocket 长连接模式

**描述**：不使用 Webhook，改用飞书的 WebSocket 长连接模式接收事件。

**优点**：无 3s 超时限制（长连接双向通信），不需要配置 Webhook URL。

**风险或成本**：
- WebSocket 长连接的高可用需要自行维护（重连、failover）
- 多副本时连接分配和事件分发更复杂
- 飞书 WebSocket 模式的文档和稳定性不如 Webhook 成熟

**不选原因**：Phase 1 优先选择更成熟的 Webhook + Redis Streams 异步模式。WebSocket 可作为 Phase 3 优化方向评估。

---

## 决策结果

**采用 Option B：新建独立 Feishu Bot Service + Redis Streams 异步解耦。**

**核心原因**：

1. **飞书平台架构限制使 Option A 不可行**：企业自建应用只支持一个 Webhook URL，必须有一个统一的消息接收层做 `union_id → user_id → pod` 的路由。
2. **Redis Streams 解决 3s 超时与 LLM 慢响应的矛盾**：飞书 Webhook 3s 超时是硬限制，LLM 响应通常 5–30s。唯一可行的方式是"立即返回 200，异步处理"。Redis Streams 提供了可靠的消息队列（ACK 机制、消费者组、消息持久化）。
3. **消息去重保证幂等性**：飞书在 3s 超时后会重发（最多 5 次）。`event_id` + Redis SETNX 提供了简单可靠的去重机制。

**影响范围**：

- 需要新建 Feishu Bot Service（FastAPI + lark_oapi + Redis Streams），2 副本
- Redis Streams 新增 `feishu:inbound` stream 和消费者组
- Auth Service 新增 `GET /auth/user/by-feishu-id` 内部接口（mTLS）
- 飞书开放平台配置：Webhook URL = `https://hermes.internal.example.com/feishu/webhook`
- Web Portal 新增飞书账号绑定页面 `/auth/feishu-bind`

**兼容性 / 迁移影响**：

- 不直接复用 Hermes `gateway/platforms/feishu.py` 的进程模型，但可复用：lark_oapi SDK 初始化、消息发送逻辑、消息卡片渲染格式、飞书签名验证逻辑
- 如果 Phase 3 扩展多 IM 平台（钉钉、企微），可用相同模式新建对应 Bot Service，共享 Redis Streams 消费者框架

**失败或回退思路**：

- Redis Streams 不可用：临时降级为同步处理，接受飞书重发带来的重复消息（用户体验降级但不丢消息）
- Feishu Bot Service 全部不可用：飞书消息无法处理，但 Web 和 API 接入不受影响。恢复后 Redis Streams 中的未消费消息仍可处理
- 飞书 union_id 映射出错：管理员在 Admin Console 手动解绑/重绑

---

## 附录 A: 飞书 OAuth 身份绑定流程详解

### A.1 身份绑定完整序列

```
┌──────────────────────────────────────────────────────────────────────┐
│                    飞书身份绑定完整流程                              │
└──────────────────────────────────────────────────────────────────────┘

  步骤 1: 飞书用户首次触发
  ───────────────────────────────────────────────────────────────────
  员工在飞书 @Hermes Bot
         │
         ▼
  飞书开放平台 ── im.message.receive_v1 事件 ──▶ Feishu Bot Service
                                                    │
                                                    ▼
                                              ① 签名验证
                                              ② 提取 sender.union_id
                                                    │
                                                    ▼
                                              ③ Auth Service 查询
                                                 GET /auth/user/by-feishu-id
                                                 ?union_id=on_xxx
                                                    │
                                       ┌────────────┴────────────┐
                                       │  404: 未绑定            │
                                       └────────────┬────────────┘
                                                    ▼
                                              ④ 生成绑定 nonce
                                                 nonce = urandom(16).hex()
                                                 写入 Redis:
                                                 SET feishu:bind:nonce:{nonce}
                                                   {union_id, created_at}
                                                   EX 300
                                                    │
                                                    ▼
                                              ⑤ 回复绑定卡片消息
                                                 "请先绑定 Hermes 账号"

  步骤 2: 员工在 Web 端完成绑定
  ───────────────────────────────────────────────────────────────────
  员工点击卡片按钮 ──▶ Browser ──▶ hermes.internal/auth/feishu-bind
                           ?union_id=on_xxx
                           &nonce=abc123def456
                           &timestamp=1715000000
                           &sign=md5(nonce+timestamp+app_secret)
                                                    │
                                                    ▼
                                        Web Portal (Nginx)
                                                    │
                                                    ▼
                                        Auth Service /auth/feishu-bind
                                                    │
                                     ┌────────────────┴────────────────┐
                                     │  验证签名:                          │
                                     │  sign == md5(nonce+timestamp+secret)│
                                     │  AND timestamp within 5 min        │
                                     │  AND Redis feishu:bind:nonce:{n}  │
                                     │    exists                         │
                                     └────────────────┬────────────────┘
                                                    ▼
                                        若未登录: 302 → SSO 登录
                                                    │
                                                    ▼
                                        Auth Service 绑定操作:
                                        UPDATE users
                                          SET feishu_union_id = 'on_xxx'
                                          WHERE id = {current_user_id}
                                                    │
                                                    ▼
                                        删除 Redis nonce:
                                        DEL feishu:bind:nonce:{nonce}
                                                    │
                                                    ▼
                                        回复 "绑定成功" 页面
                                        (员工切回飞书重新发消息即可)

  步骤 3: 正常消息路由
  ───────────────────────────────────────────────────────────────────
  员工再次在飞书 @Hermes Bot
         │
         ▼
  飞书开放平台 ── im.message.receive_v1 ──▶ Feishu Bot Service
                                                    │
                                                    ▼
                                              签名验证 + union_id 查询
                                                    │
                                              Auth: GET /auth/user/by-feishu-id
                                                    │         │
                                       ┌────────────┘         └──── 200: {user_id}
                                       ▼
                               正常路由到 Agent Pod
```

### A.2 签名防伪机制（nonce + timestamp + HMAC）

**绑定链接签名**（防止伪造绑定请求）：

| 参数 | 位置 | 说明 |
|------|------|------|
| `union_id` | query | 飞书 union_id（不敏感，公开传递）|
| `nonce` | query | 随机 16 字节十六进制（一次性使用，5min TTL）|
| `timestamp` | query | Unix timestamp（秒），5 分钟窗口内有效 |
| `sign` | query | `HMAC-SHA256(nonce + timestamp + app_secret)` 的十六进制摘要 |

**签名验证伪代码**：

```python
def verify_bind_signature(nonce: str, timestamp: str, sign: str) -> bool:
    # 1. 时间窗口校验（5 分钟）
    if abs(time.time() - int(timestamp)) > 300:
        return False

    # 2. nonce 存在性校验
    if not redis.exists(f"feishu:bind:nonce:{nonce}"):
        return False

    # 3. HMAC 签名校验
    expected = hmac.new(
        app_secret.encode(),
        f"{nonce}{timestamp}".encode(),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, sign)
```

### A.3 身份绑定状态机

```
       ┌──────────────┐
       │   初始态      │  (users.feishu_union_id = NULL)
       └──────┬───────┘
              │ 员工首次在飞书 @Bot
              ▼
       ┌──────────────┐
       │  等待绑定      │  (发送绑定卡片，未消费 nonce)
       └──────┬───────┘
              │ 员工点击链接并完成 SSO 登录
              ▼
       ┌──────────────┐
       │   已绑定      │  (feishu_union_id = union_id)
       └──────┬───────┘
              │ 管理员在 Admin Console 解绑
              ▼
       ┌──────────────┐
       │   已解绑      │  (feishu_union_id = NULL, 回到初始态)
       └──────────────┘
```

**单用户多飞书账号支持**：平台允许一个 `feishu_union_id` 绑定一个 `platform_user_id`。同一员工的多设备共享同一个 union_id，无需额外处理。

---

## 附录 B: 飞书签名验证机制详解

### B.1 签名验证概述

飞书开放平台在每个 Webhook 请求中附加两个 HTTP Header：

| Header | 说明 |
|--------|------|
| `X-Lark-Request-Timestamp` | 请求时间戳（Unix 秒）|
| `X-Lark-Signature` | 请求体 + timestamp + app_secret 的 SHA256 HMAC 十六进制摘要 |

验证目标是确保请求**确实来自飞书开放平台**，而非伪造。

### B.2 飞书官方签名算法

```
signature = HMAC-SHA256(
    key   = app_secret,
    value = "{timestamp}\n{request_body}"
).hex()
```

其中 `{timestamp}` 为 `X-Lark-Request-Timestamp` 的值，`{request_body}` 为原始请求体（JSON 字符串，**不包含**头部）。

### B.3 Feishu Bot Service 签名验证实现

```python
# feishu_bot_service/signature.py

import hmac
import hashlib
import time
from fastapi import Request, HTTPException

APP_SECRET = os.getenv("FEISHU_APP_SECRET")
# 可信时间偏移（秒）：请求时间戳与服务器时间差超过此值则拒绝
MAX_TIMESTAMP_OFFSET = 300  # 5 分钟

async def verify_lark_signature(request: Request) -> bytes:
    """
    验证飞书 Webhook 签名。
    返回原始请求体 bytes。
    验证失败抛出 HTTPException(401)。
    """
    # 1. 读取 header
    timestamp = request.headers.get("X-Lark-Request-Timestamp")
    signature = request.headers.get("X-Lark-Signature")

    if not timestamp or not signature:
        raise HTTPException(
            status_code=401,
            detail="Missing required headers: X-Lark-Request-Timestamp, X-Lark-Signature"
        )

    # 2. 时间偏移校验（防止重放攻击）
    try:
        ts = int(timestamp)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid timestamp format")

    if abs(time.time() - ts) > MAX_TIMESTAMP_OFFSET:
        raise HTTPException(
            status_code=401,
            detail=f"Timestamp out of range (> {MAX_TIMESTAMP_OFFSET}s)"
        )

    # 3. 读取请求体（支持重复读取）
    body = await request.body()

    # 4. 计算期望签名
    message = f"{timestamp}\n{body.decode('utf-8')}".encode("utf-8")
    expected = hmac.new(
        APP_SECRET.encode("utf-8"),
        message,
        hashlib.sha256
    ).hexdigest()

    # 5. 常数时间比较（防止时序攻击）
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    return body
```

### B.4 时序攻击防护

`hmac.compare_digest`（Python 标准库）在比较两个字符串时使用常数时间算法，确保比较时间与第一个不匹配字符的位置无关，防止攻击者通过测量响应时间推断正确签名。

### B.5 重放攻击防护

| 防护层 | 机制 | 窗口 |
|--------|------|------|
| 时间戳校验 | `X-Lark-Request-Timestamp` 与服务器时间差 ≤ 300s | 5 分钟 |
| 事件 ID 去重 | Redis SETNX `dedup:feishu:{event_id}` TTL 300s | 5 分钟（覆盖飞书最多 5 次重发） |

两者结合确保：
- 5 分钟窗口内的重放请求被时间戳校验拦截（飞书自己的重发也在此窗口内，event_id 去重兜底）
- 超出 5 分钟的旧请求无法通过时间戳校验
- 同一 event_id 在 5 分钟内不会重复处理

### B.6 验证失败处理

| 失败场景 | HTTP 状态码 | 处理方式 |
|---------|-----------|---------|
| Header 缺失 | 401 | 记录日志（warn level），返回 body hash 作为调试 ID |
| 时间戳越界 | 401 | 记录日志（warn level），注明时间差 |
| 签名不匹配 | 401 | 记录日志（error level），触发安全告警（疑似伪造请求）|
| 请求体解析失败 | 400 | 记录日志，记录原始 body，团队排查 |

> 注意：所有验证失败都应**返回 200 给飞书**（参考飞书官方建议），避免飞书平台重复发送。如果返回非 200，飞书会在 3s 后重发。

### B.7 安全边界总结

```
飞书 Webhook 请求 ──▶ Feishu Bot Service
                            │
                            ▼
                    ① 时间戳校验
                       (MAX 5min 窗口)
                            │
                            ▼
                    ② 签名 HMAC-SHA256
                       (app_secret 验证)
                            │
                            ▼
                    ③ Event ID 去重
                       (Redis SETNX)
                            │
                            ▼
                    ④ 消息处理
```

三层防护确保：
1. **伪造请求无法通过**：没有 app_secret 无法构造正确签名
2. **重放攻击被拦截**：时间戳窗口 + event_id 去重双重兜底
3. **响应时间 < 100ms**：验证逻辑无网络调用，本地 Redis 即可完成去重

---

## 企业内控补充

- **应用等级**: T2，Feishu Bot Service 2 副本，Redis Streams 持久化
- **数据分类**: 飞书消息内容属于员工工作内容，内部敏感级。Redis Streams 中的消息消费后保留 24 小时供排查，之后 XTRIM
- **飞书应用配置**: 需要 IT 部门在飞书管理后台注册企业自建应用，配置事件订阅（im.message.receive_v1）、权限（im:message、contact:user.id:readonly）
- **关键组件偏离**: 无——FastAPI + lark_oapi + Redis Streams 均为标准组件
- **资产文档入口**: `docs/artifacts/2026-04-15-hermes-enterprise-saas/arch-design.md` Section 3.2

---

## 后续动作

| 动作 | Owner | 完成条件 |
|------|-------|---------|
| 确认飞书应用类型和权限范围（D2） | tech-lead | 企业自建应用注册 + 测试环境 App ID/Secret |
| 实现 Feishu Bot Service Webhook handler + Redis Streams 入队 | backend-engineer | 签名验证 + 去重 + XADD + 200 返回 |
| 实现 Redis Streams 消费者 + Agent Router 路由 | backend-engineer | 消费者组 + ACK + 路由 + 回复 |
| 实现飞书账号绑定页面和 Auth 接口 | backend-engineer | `/auth/feishu-bind` 页面 + union_id 绑定 |
| 从 Hermes feishu.py 提取可复用的消息格式化逻辑 | backend-engineer | 消息卡片渲染模块 |
| 飞书消息端到端联调测试 | qa-engineer | 绑定→发消息→收回复→去重 全流程 |
| 同步到 API Contract | architect | api-contract.md 更新 Feishu 接口 |
