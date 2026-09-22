# FreeLLM Gateway 测试与验收说明

> 适用项目：FreeLLM Gateway / AI 中台模型接入层  
> 当前基线分支：`feature/ai-base-phase1`  
> 最近一次功能回归日期：2026-09-22

## 1. 文档目的

本文档定义 FreeLLM Gateway 的基础测试、Provider Adapter 验收和提交门槛。

当前阶段的核心目标是保证：

1. Gateway 对上继续提供兼容的 OpenAI 风格 API。
2. Gateway 内部不再把 OpenAI 协议当作唯一核心协议。
3. Provider 通过统一 `ProviderAdapter` 接口接入。
4. OpenAI Compatible Provider 迁移后不破坏已有 API、路由、故障转移、健康检查和持久化能力。
5. 后续 Gemini Native、Claude Native 等 Provider 可以直接实现统一 Adapter，而不需要伪装成 OpenAI Provider。

---

## 2. 当前测试基线

Provider Adapter 第一阶段包含以下主要变更：

- 新增统一协议类型：
  - `ChatRequest`
  - `ChatResponse`
  - `ChatChunk`
  - `ChatMessage`
  - `TokenUsage`
  - `ModelInfo`
- 新增 `ProviderAdapter Protocol`
- OpenAI Compatible Adapter 迁移到统一 Provider 接口
- Gateway chat / vision / long-context 请求优先走统一 Adapter 调用链
- 保留旧 `complete()` / `stream()` 兼容入口，避免旧调用一次性中断
- Provider runtime 注入真实 `provider_id`
- 新增 Provider Adapter contract tests

核心实现提交：

`64ec85c8ee73fa261693f2bba9646a4cf7d85809`

测试过程中发现并修复了一个原有路由一致性问题：

`047b945e2684684d3fffea938e1eeb77a18ef00f`

问题表现为：`health.is_eligible()` 已将 `HealthStatus.SLOW` 视为不可路由，但 `routing.select_candidates()` 没有同步排除 `SLOW`，导致慢节点仍可能进入候选列表。

修复后两处健康判定保持一致。

---

## 3. 自动化测试环境

GitHub Actions 测试环境：

- OS：Ubuntu 24.04
- Python：3.12
- 安装方式：editable install
- 测试框架：pytest
- 异步测试：pytest-asyncio

CI 工作流：

`.github/workflows/tests.yml`

工作流执行以下步骤：

```bash
python -m pip install -U pip
python -m pip install -e ".[test]"
python -m compileall -q freellm_gateway tests
python -m pytest -q
```

---

## 4. 当前回归结果

2026-09-22 Gemini Native Adapter 接入后的最终回归结果：

```text
102 passed, 2 warnings in 1.87s
```

此前 Provider Adapter 第一阶段基线为 95 passed；新增 Gemini 原生适配、统一流式输出和模型发现测试后，当前基线提升为 102 passed。

结论：

- 安装：通过
- Python 编译检查：通过
- 全量 pytest：通过
- 失败测试：0
- Provider Adapter contract：通过
- OpenAI request/response normalized mapping：通过
- Gateway -> ProviderAdapter 调用路径：通过
- Gemini generateContent 原生请求映射：通过
- Gemini streamGenerateContent -> OpenAI SSE 兼容输出：通过
- Gemini systemInstruction：通过
- Gemini data-URL 多模态输入：通过
- Gemini function calling / function response：通过
- Gemini usageMetadata / finishReason 映射：通过
- Gemini Models API 发现：通过
- Gemini quota/error 分类：通过
- API regression：通过
- Route selection：通过
- Failover：通过
- Health / Probe：通过
- Persistence：通过

对应成功的 GitHub Actions Run：

https://github.com/xdguo-design/freellm-gateway/actions/runs/35700958786

当前 2 个 warning 来自 FastAPI / Starlette 测试依赖的弃用提示，不属于业务测试失败。

---

## 5. Provider Adapter 必测项

任何新的 Provider Adapter 在合并前至少需要覆盖以下内容。

### 5.1 请求映射

验证 Gateway 的统一请求能正确转换成 Provider 原生协议：

- model
- system / user / assistant message
- text content
- image content
- temperature
- max tokens
- tools
- Provider 特有参数
- 未识别但允许透传的扩展字段

不得因为统一协议转换而静默丢失关键参数。

### 5.2 响应映射

验证 Provider 原生响应能正确转换成统一响应：

- response id
- model
- assistant content
- finish reason
- token usage
- tool call
- Provider 扩展字段

### 5.3 Streaming

至少验证：

- 首个 SSE/event chunk
- 多 chunk 连续输出
- finish reason
- usage
- DONE / 流结束
- 流开始前失败时允许 failover
- 已输出 chunk 后失败时不能无声切换 Provider

### 5.4 错误分类

至少覆盖：

- authentication error
- permission error
- rate limit
- quota exhausted
- timeout
- network error
- provider 5xx
- invalid request
- model unavailable
- invalid provider response

错误必须转换为 Gateway 统一 `ProviderError`，避免上层直接依赖厂商错误结构。

### 5.5 路由与健康状态

至少覆盖：

- priority 顺序
- disabled route
- failed route
- slow route
- rate limited route
- quota exhausted route
- cooldown route
- explicit model 不跨模型 failover
- auto model 可以按优先级 failover

### 5.6 兼容性

修改 Provider 层后必须重新执行全量测试，而不是只运行 Provider 自己的单测。

---

## 6. 本地测试方式

推荐使用 Python 3.12。

### 安装

```bash
python -m pip install -U pip
python -m pip install -e ".[test]"
```

### 编译检查

```bash
python -m compileall -q freellm_gateway tests
```

### 全量测试

```bash
python -m pytest -q
```

### 单独运行 Provider Adapter 测试

```bash
python -m pytest -q tests/test_provider_adapter_contract.py tests/test_openai_adapter.py
```

### 路由和故障转移

```bash
python -m pytest -q tests/test_routing.py tests/test_failover.py tests/test_health.py tests/test_probe.py
```

### API 回归

```bash
python -m pytest -q tests/test_api.py tests/test_admin_api.py tests/test_discovery_api.py tests/test_persistence_api.py
```

---

## 7. 真实 Provider Smoke Test

自动化测试中的 HTTP Provider 请求目前主要使用 `httpx.MockTransport`，用于验证协议、请求结构、错误处理和 Gateway 调用链。

这不能替代真实 Provider 联网测试。

进行真实 OpenAI、Gemini 或其他 Provider 验收时：

1. API Key 只通过本地 Secret Storage 或 CI Secret 注入。
2. 不允许把真实 Key 写入仓库、测试文件、日志或截图。
3. 使用成本低、输出短的 smoke prompt。
4. 至少测试一次非流式请求和一次流式请求。
5. 检查返回模型、文本、finish reason 和 token usage。
6. 主动制造或使用无效 Key 验证 authentication error 映射。
7. Provider 支持模型发现时，验证 models endpoint。
8. Provider 支持 tool / image 时，分别执行对应 smoke test。

建议 smoke prompt：

```text
Reply with exactly: FREELLM_OK
```

验收条件：

```text
HTTP success
+ response can be normalized
+ output is non-empty
+ no secret leakage
+ Gateway can record success/failure state correctly
```

---

## 8. Gemini Native Adapter 的最低验收门槛

下一阶段 Gemini Native Adapter 不允许通过 OpenAI Compatible 兼容接口绕接。

应直接调用 Gemini 原生 API，并至少覆盖：

- generateContent
- streamGenerateContent
- systemInstruction
- contents / parts
- text
- image/multimodal
- tools / function calling
- usage metadata
- finish reason
- Gemini 原生错误映射
- models discovery（如果实现）
- Gateway failover
- 全量回归

在 Gemini Adapter 的专项测试通过后，仍必须执行：

```bash
python -m compileall -q freellm_gateway tests
python -m pytest -q
```

只有全量测试为绿色才视为完成。

---

## 9. 提交门槛

功能提交进入 AI 中台主开发分支前，至少满足：

- [ ] 新功能有自动化测试
- [ ] 修改过的协议转换有 round-trip 或等价验证
- [ ] Provider 错误已统一映射
- [ ] 不泄漏 API Key / credential
- [ ] compileall 通过
- [ ] 全量 pytest 通过
- [ ] GitHub Actions 通过
- [ ] 真实外部 API 未测试时，在提交/PR中明确标注
- [ ] 不以 mock 测试冒充真实 Provider 联网测试

---

## 10. 当前已知边界

截至 2026-09-22：

- Provider Adapter 基础架构已通过全量自动化回归。
- OpenAI Compatible 网络行为已通过 MockTransport 自动化测试。
- Gemini Native Adapter 已进入当前测试基线，并通过 generateContent、streamGenerateContent、systemInstruction、data-URL 图片、function calling、Models API 和错误映射测试。
- Gateway Streaming 已优先支持统一 ProviderAdapter.stream_chat()，并继续保留旧 stream() 兼容路径。
- 尚未在本阶段使用真实 OpenAI API Key 或 Gemini API Key 进行公网调用验收。
- Gemini 对普通公网 image_url 不主动下载；当前 OpenAI 风格图片输入支持 data: URI，Gemini Files URI 可通过原生 fileData part 传入。这样避免网关引入任意 URL 下载导致 SSRF 风险。
- 当前两个 CI warning 为上游 FastAPI / Starlette 测试依赖弃用提示，不影响测试结论。

后续每增加一个原生 Provider，都应在本文件中更新对应的专项测试和最近一次全量回归结果。
