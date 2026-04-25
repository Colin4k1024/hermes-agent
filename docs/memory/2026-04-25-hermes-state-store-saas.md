# Memory: Hermes Agent StateStore SaaS 改造

日期: 2026-04-25

## 用户目标

用户明确要求将 Hermes Agent 改造为企业内部可共享的助手平台：

- 不需要每个用户部署一个独立实例。
- Agent Pod 应该是分布式、无状态、可水平扩缩的容器。
- 每个人的配置、记忆、缓存、会话、技能启用状态等个人信息都要远程化访问。
- 远程状态必须按用户隔离，第一阶段可以单企业 `tenant_id=default`，但模型必须保留 `tenant_id`。
- Router 负责鉴权和生成 runtime context，Agent Runtime 只消费可信上下文。

## 本轮实现记忆

本轮已经完成 StateStore 基础设施，而不是只写计划：

- `agent/state_store.py` 是新的状态抽象入口。
- `run_agent.py` 已经能接收 `runtime_context/state_store`。
- `HERMES_STATE_MODE=remote` 会让 Agent 使用 `RemoteStateStore`。
- `tools/memory_tool.py` 已经支持远程 memory backend。
- `services/state-service` 是新的 FastAPI 状态服务。
- router 已经能构造和转发 runtime context。
- docker-compose/k8s 已经有 state-service 资源。

## 运行模式记忆

本地 CLI 模式：

- 继续使用 `LocalStateStore` 和现有 `SessionDB`。
- 继续兼容 `HERMES_HOME`。

企业集群模式：

- 设置 `HERMES_STATE_MODE=remote`。
- 通过 `HERMES_STATE_SERVICE_URL` 指向 State Service。
- 通过 `HERMES_STATE_SERVICE_TOKEN` 调用内部状态 API。
- Router 生成 `RuntimeContext`，Agent Pod 可以任意调度，不绑定用户。

## 安全边界记忆

入口层：

- 外部请求不能直接信任 `X-User-ID`。
- 当请求包含 `Authorization` 时，router 会调用 Auth Service `/users/me` 获取可信用户。

State Service：

- 内部调用要求 bearer token。
- 每次请求必须有 `X-User-ID`。
- 数据库查询必须始终包含 `tenant_id + user_id` 过滤。
- 创建 session 时不能为其他用户创建。

日志和 secret：

- 本轮尚未完成完整日志脱敏和 secret-service 注入。
- 后续实现不能把明文 key、完整 prompt、大文件工具输出写进普通日志。

## 测试记忆

测试环境：

```text
/tmp/hermes-state-test
```

目标测试命令：

```bash
PYTHONPATH=.:services/router:services/state-service \
/tmp/hermes-state-test/bin/python -m pytest -o addopts='' \
services/router/router_service/tests/test_agent_router.py \
tests/test_state_store.py \
services/router/router_service/tests/test_stateless_runtime_schemas.py \
services/state-service/tests/test_state_service.py -q
```

最新结果：

```text
32 passed, 1 warning
```

注意：

- 项目 pytest 默认 addopts 里可能启用 `-n auto`，当前 conda env 没装 pytest-xdist，所以目标测试使用 `-o addopts=''`。
- `PytestConfigWarning: Unknown config option: asyncio_mode` 来自当前临时测试环境未安装 pytest-asyncio，不影响本轮同步测试。

## 已知技术注意点

- Pydantic v2 不允许直接把字段命名为 `model_config`；State Service schema 用 `model_config_data` 加 alias。
- SQLite 对自增主键要求 `INTEGER PRIMARY KEY`；生产保留 `BigInteger`，SQLite 用 dialect variant。
- Router 的 Redis session lock 使用 Lua `register_script`，测试不能再按旧 `get/set/delete` mock。
- FastAPI endpoint 直接单测时，默认参数可能是 `Query(...)` 对象；State Service 已做直接调用兼容。

## 下一步优先级

1. 给 State Service 加 Alembic migrations。
2. 加 Postgres/Redis/MinIO 集成测试。
3. 实现 audit event 表和脱敏日志。
4. 接入 secret-service，替代 `.env` 明文下发。
5. 远程化 skills registry 和 prompt skills snapshot。
6. 做一次端到端：Auth Service -> Router -> Agent Pod -> State Service。
