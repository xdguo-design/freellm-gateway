# Provider 多模型批量导入实施计划

> **给代理执行者：** 按 TDD 的 RED-GREEN-REFACTOR 节奏执行；任务使用 `- [ ]` 勾选跟踪。

**目标：** 让用户一次获取并导入 Provider 的多个模型，每个模型保存为独立且可单独启用/停用的路由。

**架构要点：** 后端新增批量路由接口，负责 Provider upsert、重复检测、密钥引用和多路由创建；前端将获取结果渲染为默认全部启用的模型复选列表，取消勾选只代表该模型初始停用，所有模型仍会导入。目录中的 OpenAI 兼容 API Provider 自动补全到表单，手工 Provider 流程保持兼容。

**技术栈：** Python 3.10+、FastAPI、SQLite、httpx、静态 HTML/JavaScript、pytest。

**关联设计文档：** `docs/specs/2026-09-09-bulk-provider-model-import-design.md`

---

## 文件变更清单

- 修改：`freellm_gateway/api.py`：增加批量路由接口和稳定路由 ID 生成。
- 修改：`freellm_gateway/templates/admin.html`：增加批量模型选择、目录 Provider 自动带出和批量提交。
- 修改：`tests/test_discovery_api.py`：覆盖批量 Provider upsert、多路由创建、重复跳过和密钥不回显。
- 修改：`tests/test_admin_api.py`：覆盖模型复选框和批量保存控件。

## 任务 1：批量路由 API

- [x] 写失败测试：提交一个新 Provider、两个模型和一个 Key，断言创建两个独立路由、enabled 状态按请求保存、Provider 已持久化、Key 未出现在响应。
- [x] 运行 `python -m pytest tests/test_discovery_api.py::test_admin_can_bulk_import_provider_models -q`，预期因 `/api/admin/routes/bulk` 尚不存在而失败。
- [x] 写最小实现：校验管理员令牌、Provider HTTPS 字段、非空模型数组和 credential；Provider upsert；为每个模型保存独立密钥引用和路由；已存在的 Provider+模型加入 skipped。
- [x] 再运行该测试，预期通过。

## 任务 2：重复与边界行为

- [x] 写失败测试：批量重复提交不新增重复路由；空模型数组、非字符串模型和缺少 SecretStore 分别返回 422/503；Key 不在任何错误响应中。
- [x] 运行对应测试，预期因边界校验未完整实现而失败。
- [x] 补齐校验、稳定 ID 生成和重复检测。
- [x] 运行 `python -m pytest tests/test_discovery_api.py -q`，预期通过。

## 任务 3：添加模型弹窗批量选择

- [x] 写失败测试：管理页面包含批量模型列表容器、全选控件和批量保存动作。
- [x] 运行 `python -m pytest tests/test_admin_api.py::test_admin_page_exposes_bulk_model_controls -q`，预期失败。
- [x] 将获取结果渲染为模型启用复选列表，默认全部启用；支持全部启用/全部停用；提交时把所有模型及各自 enabled 状态一次发给批量接口；成功后刷新并提示新增/跳过数量。
- [x] 运行 `python -m pytest tests/test_admin_api.py -q`，预期通过。

## 任务 4：目录 Provider 自动带出

- [x] 写失败测试：页面保留目录来源入口，批量表单包含 Provider 自动填充所需的 `apiEndpoint`、注册链接和文档信息字段。
- [x] 运行页面测试，预期缺少自动带出字段时失败。
- [x] 从目录模型条目按 Provider 聚合 OpenAI 兼容 API 条目；选择目录条目时自动设置 Provider、Base URL、注册链接、文档链接和免费说明；没有本地 Provider 时批量提交携带 Provider 对象。
- [x] 运行 `python -m pytest tests/test_admin_api.py tests/test_admin_features.py -q`，预期通过。

## 任务 5：全量验证与打包

- [x] 运行 `python -m pytest -q`，预期全套测试通过（91 passed）。
- [x] 运行 `python -m compileall freellm_gateway`，预期无编译错误。
- [x] 运行 `git diff --check`，预期无空白错误。
- [x] 重新构建桌面 sidecar 和 release 包，启动后确认网关健康检查返回 200、没有额外 CMD 窗口。
