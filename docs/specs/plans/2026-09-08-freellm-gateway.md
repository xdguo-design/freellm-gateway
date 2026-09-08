# FreeLLM Gateway 实施计划

> **给代理执行者：** 按 TDD 的 RED-GREEN-REFACTOR 节奏逐个完成任务，每项完成后运行指定测试并提交。所有任务在独立项目 `D:\WorkSpace\freellm-gateway` 执行。

**目标：** 交付一个无需 Docker 的本地模型网关，支持优先级路由、失败自动切换、健康检查和 FreeLLM 网站目录同步。

**架构要点：** 模块化单体；SQLite 保存配置与状态；Provider 通过适配器隔离；网站同步使用脱敏、版本化 JSON，不共享私密配置。

**技术栈：** Python 3.11+、FastAPI、Uvicorn、httpx、sqlite3、cryptography/keyring、pytest、pytest-asyncio。

**关联设计文档：** `docs/specs/2026-09-08-freellm-gateway-design.md`

---

## 文件结构

```text
freellm-gateway/
├── app/
│   ├── main.py                 # FastAPI 应用入口
│   ├── config.py               # 设置与路径
│   ├── db.py                   # SQLite 初始化与事务
│   ├── models.py               # 数据结构与状态枚举
│   ├── repository.py            # Provider/Route/Probe 持久化
│   ├── routing.py               # 排序、筛选、熔断与候选选择
│   ├── health.py                # 探测、延迟与状态转换
│   ├── adapters/base.py         # Provider 适配器协议
│   ├── adapters/openai.py       # OpenAI 兼容 Provider
│   ├── api.py                   # 公共 API 与管理 API
│   ├── catalog.py               # 脱敏目录导出
│   ├── cli.py                   # run/probe/export/catalog 命令
│   └── templates/admin.html     # 本地管理页面
├── tests/
│   ├── test_routing.py
│   ├── test_health.py
│   ├── test_openai_adapter.py
│   ├── test_api.py
│   ├── test_catalog.py
│   └── test_secrets.py
├── pyproject.toml
├── .env.example
├── .gitignore
└── README.md
```

### 任务 1：项目骨架与可运行测试

**涉及文件：** 新建 `pyproject.toml`、`.gitignore`、`.env.example`、`app/__init__.py`、`tests/__init__.py`、`README.md`。

- [ ] 写 `tests/test_smoke.py`，断言 `from app.main import app` 成功且 `GET /health` 返回 `{"status":"ok"}`。
- [ ] 运行 `python -m pytest tests/test_smoke.py -q`，预期因 `ModuleNotFoundError` 或路由不存在失败。
- [ ] 创建最小 FastAPI 应用和 `/health` 路由，加入依赖与 `pytest` 配置。
- [ ] 再运行同一命令，预期 1 passed。
- [ ] 提交：`git add . && git commit -m "chore: bootstrap gateway project"`。

### 任务 2：模型路由排序与候选筛选

**涉及文件：** 新建 `app/models.py`、`app/routing.py`、`tests/test_routing.py`。

- [ ] 编写行为测试：启用路由按 `priority` 升序；禁用、冷却、额度耗尽和能力不匹配路由不进入候选；同优先级按创建时间稳定排序。
- [ ] 运行 `python -m pytest tests/test_routing.py -q`，预期因模块/函数不存在失败。
- [ ] 实现 `ModelRoute`、`HealthState`、`RoutePolicy` 和 `select_candidates(routes, requested_model, capability)`。
- [ ] 运行测试，预期全部通过。
- [ ] 重构重复状态判断并运行 `python -m pytest tests/test_routing.py -q`。
- [ ] 提交：`git add app tests && git commit -m "feat: add prioritized route selection"`。

### 任务 3：健康状态、失败分类与熔断恢复

**涉及文件：** 新建/修改 `app/health.py`、`tests/test_health.py`。

- [ ] 编写测试：429 进入限流状态；额度耗尽进入额度状态；连续失败达到阈值进入冷却；冷却后成功探测恢复健康；单次慢请求不会永久禁用。
- [ ] 运行 `python -m pytest tests/test_health.py -q`，预期失败。
- [ ] 实现纯状态机函数 `record_probe(state, result, now, policy)` 和 `is_eligible(state, now)`，不在函数内发网络请求。
- [ ] 运行测试，预期全部通过。
- [ ] 增加首 Token/总耗时阈值判断与半开放恢复测试，运行全健康测试。
- [ ] 提交：`git add app tests && git commit -m "feat: add health states and circuit breaker"`。

### 任务 4：SQLite 配置库与密钥保护

**涉及文件：** 新建 `app/config.py`、`app/db.py`、`app/repository.py`、`app/secrets.py`、`tests/test_secrets.py`、`tests/test_repository.py`。

- [ ] 编写测试：临时 SQLite 可初始化；Provider/Route 可增删改查；密钥读取可恢复原值；序列化模型和目录对象不包含密钥。
- [ ] 运行 `python -m pytest tests/test_secrets.py tests/test_repository.py -q`，预期失败。
- [ ] 实现 SQLite 表、仓储接口和本机密钥包装器；测试环境使用临时密钥，生产环境优先使用系统凭据存储。
- [ ] 运行测试，预期全部通过。
- [ ] 增加重复 ID、缺失 endpoint、非法 priority 和密钥不存在的错误测试。
- [ ] 提交：`git add app tests && git commit -m "feat: persist routes and protect credentials"`。

### 任务 5：OpenAI 兼容适配器与自动故障切换

**涉及文件：** 新建 `app/adapters/base.py`、`app/adapters/openai.py`、`app/service.py`、`tests/test_openai_adapter.py`、`tests/test_failover.py`。

- [ ] 编写 httpx MockTransport 测试：成功请求保留响应；首 Token 前超时切换下一路由；429/5xx 切换；认证失败不无限重试。
- [ ] 运行 `python -m pytest tests/test_openai_adapter.py tests/test_failover.py -q`，预期失败。
- [ ] 实现 `ProviderAdapter` 协议、`OpenAICompatibleAdapter`、`ModelGateway.complete()` 和 `ModelGateway.stream()`；重试仅发生在未向客户端发送流式内容之前。
- [ ] 运行测试，预期全部通过。
- [ ] 增加无可用模型时返回结构化 `503` 的测试，并运行本任务全部测试。
- [ ] 提交：`git add app tests && git commit -m "feat: add compatible adapter and failover"`。

### 任务 6：FastAPI 公共接口和管理接口

**涉及文件：** 修改 `app/main.py`、新建 `app/api.py`、`tests/test_api.py`。

- [ ] 编写 API 测试：`/v1/models` 隐藏密钥；`/v1/chat/completions` 支持 `auto`；无效令牌返回 401；明确模型不存在返回 404；无可用候选返回 503。
- [ ] 运行 `python -m pytest tests/test_api.py -q`，预期失败。
- [ ] 接入 FastAPI 依赖注入、请求模型、响应转发和管理 CRUD；默认绑定 `127.0.0.1`，管理令牌与调用令牌分离。
- [ ] 运行测试，预期全部通过。
- [ ] 增加非流式和流式响应头/状态码测试，运行 `python -m pytest tests/test_api.py -q`。
- [ ] 提交：`git add app tests && git commit -m "feat: expose local compatible gateway api"`。

### 任务 7：探测任务与管理页面

**涉及文件：** 修改 `app/health.py`、`app/api.py`，新建 `app/templates/admin.html`、`tests/test_probe_api.py`。

- [ ] 编写测试：手动 probe 调用适配器并保存结果；拖拽/上下移动后 priority 顺序改变；手动禁用和恢复可观察。
- [ ] 运行 `python -m pytest tests/test_probe_api.py -q`，预期失败。
- [ ] 实现 probe 服务、排序更新接口和单页管理 UI，页面只显示脱敏 Provider/模型、状态、延迟、失败原因和排序控制。
- [ ] 运行测试并用 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8765` 启动后手工访问 `/admin` 验证。
- [ ] 提交：`git add app tests && git commit -m "feat: add probes and local admin page"`。

### 任务 8：FreeLLM 目录导出与网站仓库同步

**涉及文件：** 新建 `app/catalog.py`、`tests/test_catalog.py`、`scripts/sync_freellm_catalog.ps1`、更新 `README.md`。

- [ ] 编写测试：导出只包含已批准公开模型；不包含 endpoint 密钥/账号/日志；新增模型进入 `review`；导出包含 `schemaVersion` 和官方注册链接；相同输入生成稳定 JSON。
- [ ] 运行 `python -m pytest tests/test_catalog.py -q`，预期失败。
- [ ] 实现 `export_catalog(routes, providers, output_path)` 和网站同步脚本：读取网关导出、生成 FreeLLM `offers.json` 增量、调用网站仓库现有构建命令并输出 diff；默认不自动 commit/push。
- [ ] 运行测试，预期全部通过；在 `D:\WorkSpace\freellm` 的副本/测试夹具上运行 `python scripts/build_static.py --check` 与 `python scripts/build_seo_pages.py --check`。
- [ ] 增加“未确认 Provider 只进 review queue”的测试并提交：`git add app scripts tests README.md && git commit -m "feat: sync sanitized catalog to freellm"`。

### 任务 9：CLI、启动方式与最终质量门禁

**涉及文件：** 修改 `app/cli.py`、`pyproject.toml`、`README.md`，新建 `tests/test_cli.py`。

- [ ] 编写测试：`freellm-gateway init` 初始化数据库；`probe`、`export-catalog`、`run` 子命令映射到正确行为；默认 host 为 `127.0.0.1`。
- [ ] 运行 `python -m pytest tests/test_cli.py -q`，预期失败。
- [ ] 实现 CLI、Windows 启动脚本和配置说明；提供 `python -m app.cli run --port 8765` 入口。
- [ ] 运行完整验证：`python -m pytest -q`、`python -m compileall app`、`python -m app.cli --help`。
- [ ] 执行安全检查：确认 `.gitignore` 忽略 `.env`、SQLite 私密数据库和运行日志；用 `rg -n "API_KEY|Bearer |secret|password" --glob '!tests/**'` 检查源码和示例无真实密钥。
- [ ] 最终提交：`git add . && git commit -m "chore: document and verify local gateway"`。

## 最终交付

- 本地 API：`http://127.0.0.1:8765/v1`。
- 管理页：`http://127.0.0.1:8765/admin`。
- 配置、排序、探测和切换均可通过本地程序完成。
- 目录导出可被 `D:\WorkSpace\freellm` 消费，网站构建结果可检查后发布。
