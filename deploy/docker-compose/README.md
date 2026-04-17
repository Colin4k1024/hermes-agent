# Hermes Agent Enterprise SaaS — Local Development Environment

**路径**: `deploy/docker-compose/`

## 概述

本目录提供 Hermes Agent 企业内部 SaaS 平台的本地开发 Docker Compose 环境，涵盖所有平台控制面服务、LLM 模拟层和 Hermes Agent 执行层。

## 架构组件

```
┌──────────────────────────────────────────────────────────────┐
│  Hermes Agent Enterprise SaaS — Local Dev Stack              │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Control Plane                                               │
│  ├── Auth Service (8001)        FastAPI + JWT + PostgreSQL   │
│  ├── Agent Router (8002)       FastAPI + Redis              │
│  ├── Quota Service (8003)     FastAPI + PostgreSQL + Redis  │
│  ├── Skills Registry (8004)   FastAPI + PostgreSQL + Redis  │
│  └── Feishu Bot (8005)        FastAPI + Redis Streams        │
│                                                              │
│  Data Layer                                                  │
│  ├── PostgreSQL (5432)          Platform metadata             │
│  └── Redis (6379)              Routing table + cache         │
│                                                              │
│  LLM Layer                                                   │
│  └── LiteLLM Mock (4000)        OpenAI-compatible mock       │
│                                                              │
│  Execution Layer                                             │
│  └── Hermes Agent Pod (8642)     Development mode             │
│                                                              │
│  Optional                                                    │
│  └── Keycloak (8880)             OIDC mock (with-keycloak)   │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

## 快速启动

### 1. 前置条件

- Docker Compose v2 (`docker compose` 命令)
- 克隆仓库后，在项目根目录执行：

```bash
cd deploy/docker-compose/
cp .env.example .env
# 编辑 .env（生产部署前必须修改 JWT_SECRET 等密钥）
```

### 2. 启动所有服务（不含 Keycloak）

```bash
docker compose up --build
```

启动顺序由 `depends_on` + `condition: service_healthy` 控制，确保依赖服务就绪后再启动。

### 3. 启动所有服务（含 Keycloak OIDC 模拟

```bash
docker compose --profile with-keycloak up --build
```

### 4. 验证服务健康

```bash
# 检查所有服务状态
docker compose ps

# 逐个健康检查
curl http://localhost:8001/health   # Auth Service
curl http://localhost:8002/internal/health  # Router
curl http://localhost:8003/health  # Quota Service
curl http://localhost:8004/health  # Skills Registry
curl http://localhost:8005/health  # Feishu Bot
curl http://localhost:4000/health  # LiteLLM Proxy
curl http://localhost:8642/health  # Hermes Agent
```

### 5. 查看日志

```bash
# 所有服务
docker compose logs -f

# 特定服务
docker compose logs -f auth-service
docker compose logs -f router-service

# 最近 100 行
docker compose logs --tail=100 postgres
```

## 服务详情

### Auth Service (8001)

OIDC 集成、JWT 签发与验证、用户 CRUD、RBAC、API Token 管理。

**环境变量**：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `POSTGRES_HOST` | `postgres` | PostgreSQL 地址 |
| `JWT_SECRET` | `dev-jwt-secret-...` | **生产必须修改** |
| `OIDC_ISSUER` | `http://localhost:8880/...` | Keycloak OIDC issuer |
| `OIDC_CLIENT_ID` | `hermes-auth` | OIDC 客户端 ID |
| `OIDC_CLIENT_SECRET` | `dev-secret` | **生产必须修改** |

**热重载**：源码目录以 bind mount 方式挂载，修改代码自动重载。

### Agent Router (8002)

用户请求路由调度、Redis 路由表管理、Pod 健康检查、冷启动触发。

**环境变量**：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `REDIS_HOST` | `redis` | Redis 地址 |
| `AUTH_SERVICE_URL` | `http://auth-service:8001` | Auth Service 内网地址 |
| `QUOTA_SERVICE_URL` | `http://quota-service:8003` | Quota Service 内网地址 |
| `LLM_PROXY_URL` | `http://litellm-mock:4000` | LiteLLM Proxy 内网地址 |
| `K8S_ENABLED` | `false` | 本地开发禁用 K8s API |

**热重载**：支持。

### Quota Service (8003)

Per-user token 用量计量、每日配额检查、LiteLLM callback 接收。

**环境变量**：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `POSTGRES_HOST` | `postgres` | PostgreSQL 地址 |
| `REDIS_HOST` | `redis` | Redis 地址 |
| `AUTH_SERVICE_URL` | `http://auth-service:8001` | Auth Service 内网地址 |

**热重载**：支持。

### Skills Registry (8004)

组织级 Skills CRUD、版本管理、NAS 目录同步、Redis PubSub 热更新通知。

**环境变量**：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SKILLS_REGISTRY_DEBUG` | `true` | 开发模式使用本地路径 |
| `SKILLS_REGISTRY_SKILLS_LOCAL_DEV_PATH` | `/app/dev-skills` | 本地开发目录 |
| `SKILLS_REGISTRY_JWT_SECRET` | `dev-jwt-secret-...` | JWT 验证密钥 |
| `SKILLS_REGISTRY_ADMIN_API_KEY` | `dev-admin-key-...` | Admin API 密钥 |

**热重载**：支持。

### Feishu Bot Service (8005)

飞书 Webhook 签名验证、消息接收/推送、Redis Streams 消息缓冲。

**环境变量**：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FEISHU_APP_ID` | `cli_xxx` | 飞书应用 ID（需填写真实值）|
| `FEISHU_APP_SECRET` | `xxx` | 飞书应用密钥（需填写真实值）|
| `FBOT_INSTANCE_ID` | `fbp-local-001` | 实例 ID（多实例时需唯一）|
| `AUTH_SERVICE_URL` | `http://auth-service:8001` | Auth Service 内网地址 |
| `ROUTER_SERVICE_URL` | `http://router-service:8002` | Router 内网地址 |

### LiteLLM Proxy (4000)

Mock LLM 端点，OpenAI-compatible 接口。本地开发时替代真实内网 LLM 服务。

**模型**：

| 模型名 | 说明 |
|--------|------|
| `gpt-3.5-turbo-mock` | 模拟 GPT-3.5 |
| `gpt-4o-mock` | 模拟 GPT-4o |
| `claude-3-sonnet-mock` | 模拟 Claude 3 Sonnet |

生产部署时，更新 `services/litellm-mock/config.yaml` 中的 `model_list` 指向真实 LLM 端点。

### Hermes Agent (8642)

Hermes Agent 开发模式容器。源码通过 bind mount 挂载，支持热重载。

**环境变量**：

| 变量 | 说明 |
|------|------|
| `HERMES_HOME` | 固定为 `/opt/data`（卷挂载）|
| `API_SERVER_HOST` | 绑定地址（默认 `0.0.0.0`）|
| `HERMES_API_KEY` | 访问密钥 |
| `OPENAI_API_BASE` | 指向 `litellm-mock:4000` |
| `OPENAI_API_KEY` | 认证密钥 |

### PostgreSQL (5432)

平台元数据库（用户、配额、Skills、用量记录、审计日志）。

- 用户：`hermes` / `hermes`（开发默认值）
- 数据库：`hermes_platform`
- Init script：`init-scripts/01-init-schema.sql`（首次启动自动执行）

### Redis (6379)

路由表、限流计数器、飞书消息队列、分布式锁。

## 卷管理

| 卷名 | 说明 |
|------|------|
| `postgres_data` | PostgreSQL 数据持久化 |
| `redis_data` | Redis 数据持久化（含 AOF）|
| `auth_service_data` | Auth Service 数据 |
| `router_service_data` | Router Service 数据 |
| `skills_registry_dev_skills` | Skills Registry 本地开发目录 |
| `skills_storage` | NAS org-skills 目录（开发时为只读空目录）|
| `hermes_dev_data` | Hermes Agent 用户数据卷 |

**清理数据**：

```bash
# 停止并删除所有卷（所有数据丢失）
docker compose down -v

# 仅重启（保留数据）
docker compose restart
```

## 开发工作流

### 添加新 Service

1. 在 `services/` 下创建子目录（含 `pyproject.toml` 和源码）
2. 在 `docker-compose.yml` 添加 service 定义
3. 在 `services/<name>/Dockerfile` 中添加多阶段 Dockerfile
4. 运行 `docker compose up --build <service-name>`

### 调试服务

```bash
# 进入容器 shell
docker compose exec auth-service sh
docker compose exec redis redis-cli
docker compose exec postgres psql -U hermes -d hermes_platform

# 查看资源使用
docker compose top

# 查看网络
docker network inspect hermes-dev-network
```

### 连接外部服务

在 `.env` 中覆盖默认值：

```bash
# 使用外部 PostgreSQL
POSTGRES_HOST=your-postgres.example.com
POSTGRES_PORT=5432

# 使用外部 Redis
REDIS_HOST=your-redis.example.com
REDIS_PORT=6379
```

## 生产部署注意事项

1. **修改所有密钥**：`.env` 中的 `JWT_SECRET`、`ADMIN_API_KEY`、`HERMES_API_KEY`
2. **移除开发模型**：将 `litellm-mock/config.yaml` 替换为真实 LLM 配置
3. **Keycloak**：使用生产 Keycloak 实例，删除 `with-keycloak` profile
4. **飞书配置**：填写真实的 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET`
5. **NAS 挂载**：生产环境需要 NFS v4 挂载（见 ADR-004）

## 文件清单

```
deploy/docker-compose/
├── docker-compose.yml          # 主配置文件
├── .env.example                # 环境变量模板
├── .dockerignore               # 构建忽略文件
├── README.md                   # 本文档
├── init-scripts/
│   └── 01-init-schema.sql      # PostgreSQL 初始化脚本
└── services/
    ├── auth-service/
    │   ├── Dockerfile          # 多阶段构建（dev/prod）
    │   └── pyproject.toml
    ├── router-service/
    │   ├── Dockerfile
    │   └── pyproject.toml
    ├── quota-service/
    │   ├── Dockerfile
    │   └── pyproject.toml
    ├── skills-registry/
    │   └── Dockerfile          # 复用仓库已有结构
    ├── feishu-bot/
    │   └── Dockerfile          # 复用仓库已有结构
    ├── litellm-mock/
    │   ├── Dockerfile
    │   └── config.yaml         # LiteLLM mock 配置
    └── keycloak/
        └── hermes-realm.json   # Keycloak realm 配置（可选）
```

## 故障排查

### 服务启动失败

```bash
# 查看详细日志
docker compose up --build 2>&1 | tee debug.log

# 检查端口占用
lsof -i :8001 -i :8002 -i :8003 -i :8004 -i :8005 -i :8642 -i :4000 -i :5432 -i :6379
```

### 健康检查超时

健康检查 `start_period` 给予服务初始化时间。若持续失败，检查依赖服务是否就绪：

```bash
docker compose logs <service-name> | grep -i error
```

### Hermes Agent 启动缓慢

首次构建需要安装 Playwright 浏览器（~5 分钟），后续启动会复用缓存。

### PostgreSQL 连接失败

确认 `postgres` 容器的 `hermes_network` 网络已就绪：

```bash
docker compose exec auth-service nc -zv postgres 5432
```
