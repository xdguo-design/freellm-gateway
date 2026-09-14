# Anthropic Provider 支持设计

## 目标

让 FreeLLM Gateway 继续对外提供 OpenAI Chat Completions 接口，同时支持将请求路由到 Anthropic Messages API，并在管理台新增 Provider 时可选择协议，默认选择 `openai`。

## 范围

- 支持 `openai` 和 `anthropic` 两种 Provider 协议。
- Anthropic 上游使用 `POST /v1/messages`、`x-api-key` 和 `anthropic-version: 2023-06-01`。
- 将 OpenAI 风格请求转换为 Anthropic 请求，将 Anthropic 非流式响应转换为 OpenAI Chat Completion 响应。
- 将 Anthropic 流式事件转换为 OpenAI SSE chunk，并以 `data: [DONE]` 结束。
- Anthropic 和 OpenAI 均支持管理台的模型列表读取。
- 管理台 Provider 表单提供协议下拉，选项为 OpenAI-compatible 和 Anthropic，默认 `openai`，提交实际选择值。
- Provider 创建接口和批量导入接口校验并接受这两种协议。

## 不在范围内

- 不新增原生 Anthropic 入站 `/v1/messages` 接口；网关公共入站契约仍是 `/v1/chat/completions`。
- 不把所有 OpenAI 高级参数强行映射到 Anthropic；首版保留通用文本、system、图片、`max_tokens`、`temperature`、`top_p`、`stop` 等可安全映射字段。
- 不改变现有路由、健康状态、凭据引用和故障切换模型。

## 适配器行为

`AnthropicAdapter` 与现有适配器提供同样的 `complete`、`stream`、`list_models`、`aclose` 接口。默认 endpoint 为 Provider `base_url` 去掉末尾 `/` 后加 `/v1/messages`；路由自定义 `endpoint` 时优先使用它。

请求转换规则：提取 `system` 消息到顶层 `system`，只向上游发送 `user` / `assistant` 消息；字符串内容原样保留，OpenAI `text` 块转换为 Anthropic `text` 块，`image_url` 的 data URL 转换为 Anthropic base64 image source。未提供 `max_tokens` 时使用 `1024`，并保留 `stream`、`temperature`、`top_p`、`stop` 的对应字段（`stop` 转为 `stop_sequences`）。

非流式响应的文本 content block 合并到 `choices[0].message.content`，`stop_reason` 映射为 `finish_reason`，`usage.input_tokens` / `output_tokens` 映射为 OpenAI usage 字段。

流式响应只对文本增量输出 OpenAI `chat.completion.chunk`，在消息结束后发出 `[DONE]`；非文本或无法解析的上游事件不应导致有效文本流失败。

## 错误与发现

沿用现有 `ProviderError` 分类、重试和限流处理。Anthropic 模型发现请求 `GET /v1/models`，响应读取 `data[].id`。协议不支持或凭据为空时返回现有管理 API 的 422/501 错误语义。

## 测试验收

- Anthropic 非流式请求发送正确 URL、鉴权头、版本头和转换后的 JSON，并返回 OpenAI 风格响应。
- Anthropic 响应 usage、finish reason、文本块转换正确。
- Anthropic SSE 文本增量被转换为 OpenAI SSE chunk，并正常结束。
- Anthropic 错误响应沿用现有错误分类。
- runtime 根据 Provider 协议选择正确适配器，模型列表接口支持 Anthropic。
- Provider 创建和批量导入接受 Anthropic，拒绝未知协议。
- 管理台包含协议下拉，`openai` 为默认值且提交用户选择。
