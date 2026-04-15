# ADR-003: 认证与 API Token 架构 — JWT + OIDC + Per-user API Token

**状态**: accepted  
**日期**: 2026-04-15  
**Owner**: architect  
**关联需求**: hermes-enterprise-saas PRD  
**关联 Arch Design**: docs/artifacts/2026-04-15-hermes-enterprise-saas/arch-design.md

---

## 背景与约束

Hermes Agent 当前的认证模型极其简单：一个全局环境变量 `HERMES_API_KEY`（`api_server.py:380` 中读取 `API_SERVER_KEY`），所有调用方共享同一个静态密钥。这在单用户本地运行时可以接受，但在 20k 用户的企业 SaaS 平台上存在根本缺陷：无法区分请求来自哪个用户，无法撤销单个用户的访问权限，无法对不同用户做配额控制，密钥泄漏影响全平台。

企业 SaaS 平台需要支持三种接入方式：

- **Web 用户**：通过浏览器访问 `hermes.internal.example.com`，需要企业 SSO 登录
- **API 用户**：开发者通过 OpenAI SDK 调用 `/v1/chat/completions`，需要 per-user API token
- **飞书用户**：通过飞书 Bot @Hermes 交互，需要 feishu_union_id → platform_user_id 映射

**关键约束**：

1. 企业已有 SSO/IdP 系统（D1: 假设 Keycloak，支持 OIDC）
2. 数据分类为内部敏感级，认证不能有逻辑漏洞
3. API token 需要独立于 SSO session，支持长期有效、可撤销、可审计
4. 飞书用户身份必须绑定到企业统一 user_id，不能依赖飞书 open_id 作为唯一凭证

---

## 备选方案

### Option A: 全局 HERMES_API_KEY（现有方案）

**描述**：保持现状，所有用户共享一个 API key。

**优点**：零改动。

**风险或成本**：无法做 per-user 配额控制、审计追踪、权限撤销；密钥泄漏等同全平台沦陷；违反企业安全审计要求。

**不选原因**：在 20k 用户场景下安全风险不可接受。

### Option B: JWT + OIDC + Per-user API Token（本方案）

**描述**：分层认证架构：

1. **Web 用户**：OIDC Authorization Code Flow → 企业 IdP 认证 → Auth Service 签发 JWT → HttpOnly Cookie
2. **API 用户**：用户在管理台生成 per-user API Token（`hms_` 前缀）→ SHA-256 hash 存储 → Bearer Token 调用
3. **飞书用户**：feishu_union_id 绑定到 platform_user_id → Feishu Bot Service 内部调用 Auth Service 查询映射

**优点**：
- **统一身份**：三种接入方式统一映射到同一个 `platform_user_id`，配额和审计一致
- **安全设计**：JWT 短期有效（30min）+ refresh token（7d）；API token 明文只返回一次，数据库存 SHA-256 hash；飞书通过 union_id 绑定而非不稳定的 open_id
- **可撤销**：管理员可禁用用户、撤销 API token、解绑飞书 ID，生效即时
- **可审计**：所有认证事件写入 audit_logs 表

**风险或成本**：
- 需要新建 Auth Service（开发成本 ~2 周）
- JWT 签名密钥管理和轮换需要设计
- OIDC 集成依赖企业 IdP 配置（D1 待确认）

### Option C: 引入开源 IdP（Authentik / Authelia）替代自建 Auth Service

**描述**：部署 Authentik 或 Authelia 作为平台认证网关。

**优点**：MFA、RBAC、OIDC proxy 开箱即用，减少自建代码量。

**风险或成本**：
- **不支持 per-user API token 管理**：开源 IdP 的 token 模型面向 OAuth2 client，不面向"用户自己生成 API key"的场景
- **不支持飞书 union_id 绑定**：非标准认证场景，开源 IdP 不内置支持
- 引入开源 IdP 后仍需自建服务补充定制逻辑，不如直接自建聚焦的 Auth Service

**不选原因**：本平台的核心定制需求超出了通用开源 IdP 的能力范围。

---

## 决策结果

**采用 Option B：自建 Auth Service，实现 JWT + OIDC + Per-user API Token 三层认证。**

**核心原因**：

1. **统一身份模型**：三种接入方式统一映射到 `platform_user_id`，配额计量和审计日志以统一身份为锚点。
2. **API Token 安全设计满足企业要求**：`hms_` 前缀便于安全扫描识别泄漏；SHA-256 存储确保数据库被拿也不能直接使用 token；自动过期 + 可撤销满足合规审计。
3. **飞书深度集成**：`feishu_union_id` 作为 users 表的 UNIQUE 字段直接绑定，首次使用飞书 Bot 时通过 Web SSO 完成一次性绑定。

**Token 安全策略**：

| 场景 | Token 类型 | 有效期 | 存储方式 | 安全机制 |
|------|-----------|--------|---------|---------|
| Web 登录 | JWT (hermes_jwt Cookie) | access: 30min, refresh: 7d | HttpOnly + Secure + SameSite=Lax | OIDC code flow, CSRF token |
| API 调用 | API Token (hms_xxx) | 用户设定，默认 90 天 | SHA-256 hash in PostgreSQL | 明文只返回一次，可撤销，last_used_at 追踪 |
| 飞书交互 | 无独立 token | — | feishu_union_id in users 表 | 飞书签名验证 + union_id → user_id 查表 |
| 内部服务间 | mTLS | — | K8s Service Account | 仅限 hermes-control namespace 内部 |

**飞书用户首次绑定流程**：

```
1. 用户首次在飞书 @Hermes
2. Feishu Bot Service 查询 Auth: GET /auth/user/by-feishu-id?union_id=xxx → 404
3. Bot 回复消息卡片，包含链接: hermes.internal/auth/feishu-bind?union_id=xxx&nonce=abc
4. 用户点击 → Web SSO 登录 → Auth Service 验证 nonce（5 分钟有效）→ 写入 feishu_union_id
5. 用户再次在飞书 @Hermes → 查询成功 → 正常路由
```

**影响范围**：

- 所有接入 Agent Router 的请求都需要先经过 Auth Service 验证
- 管理员 API 需要 `role = admin` 的 JWT 才能调用
- Hermes Agent 自身不需要任何认证改动——Agent Pod 之间的 API 调用使用 per-pod HERMES_API_KEY（由 Sidecar 注入）

**兼容性 / 迁移影响**：

- 如果企业 IdP 从 Keycloak 更换为其他 OIDC provider，只需修改 Auth Service 的 OIDC 配置

**失败或回退思路**：

- OIDC 集成受阻（D1 迟迟不确认）：Phase 1 可临时使用用户名/密码登录 + JWT，后续补接 OIDC
- Auth Service 成为性能瓶颈：在 Agent Router 层做 JWT 本地验证（公钥缓存），只有 API token 验证需要查库
- JWT 签名密钥泄漏：立即轮换密钥，所有在线 session 失效，用户重新登录

---

## 企业内控补充

- **应用等级**: T2，Auth Service 双副本，JWT 签名密钥存储在 K8s Secret（加密 etcd）
- **数据分类**: 认证凭证属于高敏感级，API token hash 不可逆，audit_logs 保留 3 个月
- **合规要求**: 管理员不得查看用户会话内容（认证系统只管身份，不碰对话数据）
- **资产文档入口**: `docs/artifacts/2026-04-15-hermes-enterprise-saas/arch-design.md` Section 6.1

---

## 后续动作

| 动作 | Owner | 完成条件 |
|------|-------|---------|
| 确认企业 SSO 协议和 IdP 厂商（D1） | tech-lead | OIDC / SAML 确认 + IdP 测试环境 |
| 实现 Auth Service OIDC 集成 | backend-engineer | SSO 登录流程端到端通过 |
| 实现 API Token CRUD 和 verify 接口 | backend-engineer | `hms_` token 生成、hash 存储、verify 接口 |
| 实现飞书 union_id 绑定流程 | backend-engineer | 绑定页面 + Auth API + Feishu Bot 联调 |
| JWT 签名密钥管理方案 | devops-engineer | 密钥生成、存储、轮换 SOP |
| 认证安全 review | security-reviewer | 认证流程安全测试报告 |
| 同步到 API Contract | architect | api-contract.md 更新 Auth 接口 |
