# Gemini 原生 Provider 接入实施计划

> **给代理执行者：** 推荐在本会话内按勾选逐步执行。每个行为遵循 TDD 的 RED → GREEN → REFACTOR 节奏。

**目标：** 为网关新增 Gemini 原生 REST Provider，并保持现有 OpenAI 兼容公共接口不变。

**架构要点：** 新增独立 `GeminiAdapter` 封装 Gemini GenerateContent API；runtime、管理 API 只增加协议分派，不把 Gemini 转换逻辑泄漏到路由层。API Key 通过 `x-goog-api-key` header 发送，流式响应转换为现有 OpenAI SSE。

**技术栈：** Python 3.10、httpx、FastAPI、pytest、pytest-asyncio；验证命令为 `.venv\Scripts\python.exe -m pytest -q` 与 `.venv\Scripts\python.exe -m ruff check freellm_gateway tests`。

**关联设计文档：** `docs/specs/2026-09-14-gemini-provider-design.md`

---

## 文件结构先行

- 新建：`freellm_gateway/adapters/gemini.py`，负责 Gemini 请求构造、响应转换、SSE 转换和模型发现。
- 修改：`freellm_gateway/models.py`，注册 `gemini` 协议。
- 修改：`freellm_gateway/runtime.py`，从 `protocol=gemini` 构造 `GeminiAdapter`。
- 修改：`freellm_gateway/api.py`，管理 API 的 Provider 校验、模型发现和临时连接验证支持 Gemini。
- 修改：`freellm_gateway/templates/admin.html`，协议下拉增加 Gemini，并更新协议文案。
- 新建：`tests/test_gemini_adapter.py`，覆盖 adapter 的正常、流式、模型发现和协议错误行为。
- 修改：`tests/test_runtime.py`、`tests/test_discovery_api.py`、`tests/test_admin_api.py`，覆盖 runtime 和管理 API 集成行为。
- 修改：`README.md`，记录 Gemini 原生 Provider 配置与模型关停提示。

## 任务 1：Gemini adapter 非流式请求

**涉及文件：** 新建 `tests/test_gemini_adapter.py`、新建 `freellm_gateway/adapters/gemini.py`。

- [ ] 编写失败测试：用 `httpx.MockTransport` 断言请求 URL 为 `.../models/gemini-test:generateContent`，认证使用 `x-goog-api-key`，请求体含 `systemInstruction`、`contents` 和 `generationConfig`，并断言响应转换为 OpenAI completion。
- [ ] 运行 `.venv\Scripts\python.exe -m pytest -q tests/test_gemini_adapter.py::test_gemini_adapter_translates_complete_request_and_response`；预期因 `ModuleNotFoundError` 失败。
- [ ] 实现 `GeminiAdapter.complete`、`gemini_generate_endpoint`、`to_gemini_request`、`from_gemini_response`，只覆盖该测试要求的文本与配置字段。
- [ ] 运行同一测试；预期通过。
- [ ] 重构后运行 `.venv\Scripts\python.exe -m pytest -q tests/test_gemini_adapter.py`；预期当前 adapter 测试全绿。

## 任务 2：Gemini adapter 流式输出

**涉及文件：** 修改 `tests/test_gemini_adapter.py`、修改 `freellm_gateway/adapters/gemini.py`。

- [ ] 编写失败测试：Mock Gemini `data: {...}` SSE，断言输出包含 assistant role、文本 delta、finish reason、标准化 usage 和 `[DONE]`，并断言流式 URL 带 `alt=sse`。
- [ ] 运行 `.venv\Scripts\python.exe -m pytest -q tests/test_gemini_adapter.py::test_gemini_adapter_translates_streaming_sse`；预期因 `stream` 未实现或输出不匹配失败。
- [ ] 实现 `GeminiAdapter.stream`、`openai_stream_chunk` 和 SSE 序列化，保留现有 `ProviderError` / httpx 超时错误分类模式。
- [ ] 运行同一测试；预期通过。
- [ ] 增加 malformed JSON 与上游 401 测试，运行 `.venv\Scripts\python.exe -m pytest -q tests/test_gemini_adapter.py`；预期全绿。

## 任务 3：模型发现和 runtime 分派

**涉及文件：** 修改 `tests/test_gemini_adapter.py`、`tests/test_runtime.py`；修改 `freellm_gateway/adapters/gemini.py`、`freellm_gateway/runtime.py`。

- [ ] 编写失败测试：Mock `GET /v1beta/models` 返回一个支持 `generateContent` 的模型、一个 embedding 模型和一个不带 `baseModelId` 的条目；断言只返回有效生成模型名。
- [ ] 运行 `.venv\Scripts\python.exe -m pytest -q tests/test_gemini_adapter.py::test_gemini_adapter_lists_only_generate_content_models`；预期因 `list_models` 未实现失败。
- [ ] 实现 `GeminiAdapter.list_models` 和 `aclose`，并在 runtime 的 `adapter_for_provider` 增加 `protocol == "gemini"` 分支，默认 Base URL 使用 `.../v1beta`。
- [ ] 运行 `.venv\Scripts\python.exe -m pytest -q tests/test_gemini_adapter.py tests/test_runtime.py`；预期 Gemini 与既有 runtime 测试全绿。

## 任务 4：管理 API 接受 Gemini

**涉及文件：** 修改 `tests/test_discovery_api.py`、`tests/test_admin_api.py`；修改 `freellm_gateway/api.py`。

- [ ] 编写失败测试：Provider 创建接受 `protocol=gemini`；`/api/admin/connection/models` 和 `/api/admin/providers/{id}/models` 使用 Gemini adapter 的模型列表；未知协议仍返回 422。
- [ ] 运行对应测试；预期因协议白名单和 adapter 分派缺少 Gemini 而失败。
- [ ] 修改 API 分派，统一使用 Gemini endpoint helper；更新错误文案为支持 `openai`、`anthropic`、`gemini`。
- [ ] 运行 `.venv\Scripts\python.exe -m pytest -q tests/test_discovery_api.py tests/test_admin_api.py`；预期相关测试全绿。

## 任务 5：管理台、文档和回归验证

**涉及文件：** 修改 `freellm_gateway/templates/admin.html`、`README.md`、`tests/test_admin_api.py`。

- [ ] 编写失败测试：断言管理台协议 select 包含 `gemini`，并显示 Gemini 原生 Base URL 与 API Key 说明；README 包含 Gemini 配置示例和 `gemini-2.0-flash` 已关停提示。
- [ ] 运行对应测试；预期因 UI 和 README 尚未更新而失败。
- [ ] 增加 Gemini 选项、文案和最小配置示例，不把任何真实密钥写入仓库。
- [ ] 运行 `.venv\Scripts\python.exe -m pytest -q`；预期全量测试通过。
- [ ] 运行 `.venv\Scripts\python.exe -m ruff check freellm_gateway tests`；预期无 lint 错误。
- [ ] 检查 `git diff --check`，确认无空白错误；检查 `git status --short`，确认不包含 API Key、数据库或日志文件。

## 完成标准

- `gemini` Provider 可通过管理 API 和管理台创建。
- Gemini 模型可被发现、保存、探测，并通过 `/v1/chat/completions` 以 OpenAI 兼容格式调用。
- 流式和非流式请求均有 adapter 单测；管理 API 和 runtime 有集成测试。
- 现有 OpenAI、Anthropic、路由、失败切换测试保持通过。
- 明确提示 `gemini-2.0-flash` 已关停，不把它宣传为可用模型。
