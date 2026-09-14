# Anthropic Provider 支持实施计划

> **给代理执行者：** 本计划在当前工作区按 TDD 的 RED-GREEN-REFACTOR 节奏执行。保留已有未提交改动，不执行 reset 或覆盖无关文件。

**目标：** 增加 Anthropic Messages 上游适配，并让管理台 Provider 协议可选且默认 OpenAI。

**架构要点：** 公共 API 仍接收 OpenAI Chat Completions；协议差异封装在 Provider adapter 内。Anthropic adapter 负责请求/响应/SSE 转换，runtime 和管理 API 只负责按协议选择适配器。

**技术栈：** Python 3、httpx、FastAPI、pytest、pytest-asyncio；验证命令为 `pytest -q`。

**关联设计文档：** `docs/specs/2026-09-10-anthropic-provider-design.md`

---

### 任务 1：Anthropic 非流式适配器

**涉及文件：**
- 新建：`freellm_gateway/adapters/anthropic.py`
- 新建：`tests/test_anthropic_adapter.py`

- [ ] **步骤 1：编写失败测试**

测试 MockTransport 断言 `POST /v1/messages`、`x-api-key`、`anthropic-version` 和请求体转换；返回 Anthropic message 后断言得到 OpenAI `choices`、`finish_reason` 和 `usage`。

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/test_anthropic_adapter.py::test_anthropic_adapter_translates_messages_and_response -v`

预期：因 `freellm_gateway.adapters.anthropic` 尚不存在而失败。

- [ ] **步骤 3：最小实现**

实现 `AnthropicAdapter.complete`、消息转换、响应转换和与现有 OpenAI adapter 一致的 HTTP/ProviderError 处理。

- [ ] **步骤 4：运行测试确认通过**

运行：`pytest tests/test_anthropic_adapter.py -v`

预期：非流式适配器测试全部通过。

### 任务 2：Anthropic 流式输出、模型发现与 runtime 选择

**涉及文件：**
- 修改：`freellm_gateway/adapters/anthropic.py`
- 修改：`freellm_gateway/runtime.py`
- 修改：`tests/test_anthropic_adapter.py`
- 修改：`tests/test_runtime.py`

- [ ] **步骤 1：编写失败测试**

增加 Anthropic `message_start`、`content_block_delta`、`message_delta`、`message_stop` SSE 转 OpenAI chunk 的测试；增加 `/v1/models` ID 列表测试；增加 `adapter_for_route` 返回 AnthropicAdapter 的测试。

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/test_anthropic_adapter.py tests/test_runtime.py -v`

预期：流式转换和协议分派断言失败。

- [ ] **步骤 3：最小实现**

实现 Anthropic SSE 解析、OpenAI chunk 序列化、`GET /v1/models` 和 runtime 的 `protocol == "anthropic"` 分支。

- [ ] **步骤 4：运行测试确认通过**

运行：`pytest tests/test_anthropic_adapter.py tests/test_runtime.py -v`

预期：相关测试全部通过。

### 任务 3：管理 API 接受协议并复用协议适配器发现模型

**涉及文件：**
- 修改：`freellm_gateway/api.py`
- 修改：`tests/test_admin_api.py`
- 修改：`tests/test_admin_features.py`

- [ ] **步骤 1：编写失败测试**

增加 Provider 创建接受 `protocol: anthropic`、未知协议返回 422、Anthropic Provider 模型读取使用 Anthropic endpoint 的测试；增加批量导入可接受 Anthropic Provider 的测试。

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/test_admin_api.py tests/test_admin_features.py -v`

预期：当前创建接口未校验/支持协议，模型接口固定使用 OpenAI adapter，批量导入拒绝 Anthropic，因此相关断言失败。

- [ ] **步骤 3：最小实现**

新增允许协议集合；Provider 创建和 `_provider_from_payload` 使用集合校验；模型读取根据 Provider 生成临时 adapter，并在请求结束后关闭。

- [ ] **步骤 4：运行测试确认通过**

运行：`pytest tests/test_admin_api.py tests/test_admin_features.py -v`

预期：管理 API 相关测试全部通过。

### 任务 4：管理台 Provider 协议下拉

**涉及文件：**
- 修改：`freellm_gateway/templates/admin.html`
- 修改：`tests/test_admin_api.py`

- [ ] **步骤 1：编写失败测试**

断言 Provider 表单包含 `name="protocol"` 的 select、`openai` 和 `anthropic` 选项，并且 `openai` 带 `selected`；断言提交脚本不再无条件覆盖协议。

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/test_admin_api.py::test_admin_page_exposes_provider_protocol_selector -v`

预期：当前页面没有协议 select，测试失败。

- [ ] **步骤 3：最小实现**

在 Provider 表单加入协议下拉，提交时从 `FormData` 读取并发送 `protocol`，新增/编辑模型 Provider 下拉保留实际协议值。

- [ ] **步骤 4：运行测试确认通过**

运行：`pytest tests/test_admin_api.py -v`

预期：页面标记测试全部通过。

### 任务 5：回归验证与重构

**涉及文件：**
- 以上变更文件

- [ ] **步骤 1：运行完整测试**

运行：`pytest -q`

预期：所有既有和新增测试通过。

- [ ] **步骤 2：静态检查变更**

运行：`git diff --check` 与 `git status --short`；确认没有密钥、Prompt、响应正文或无关文件进入变更。

- [ ] **步骤 3：必要重构后复测**

仅在全绿后合并重复的 HTTP 错误处理或转换辅助函数；再次运行 `pytest -q`。
