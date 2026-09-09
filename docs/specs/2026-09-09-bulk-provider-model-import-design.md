# Provider 多模型批量导入设计

## 目标

在“添加模型”窗口中，选择一个 Provider、填写一次 API Key 并获取远程模型后，把返回的多个模型一次性加入模型池。每个模型保存为独立路由，后续可以单独启用或停用。

## 用户流程

1. 打开“添加模型”。Provider 下拉框同时展示已保存 Provider 和目录中的 OpenAI 兼容 API Provider。
2. 从目录选择 Provider 时，自动带出 Provider 名称、Base URL、注册链接、文档链接和能力；如果本地还没有该 Provider，保存批量模型时自动创建。
3. 点击注册链接完成第三方注册并创建 API Key，把 Key 粘贴到窗口。
4. 点击“获取模型”，调用 Provider 的 `/models` 接口，展示全部模型；默认全部启用。
5. 用户对不想立即使用的模型取消“启用”，但这些模型仍然会被导入；点击“批量加入模型池”。
6. 网关为全部返回模型创建独立路由，按每项启用状态保存，并复用同一个本机密钥引用。保存完成后刷新模型池，用户可以对每条路由单独启用/停用和测试连接。

## API 设计

新增 `POST /api/admin/routes/bulk`，仅管理员令牌可调用：

```json
{
  "provider": {
    "id": "openrouter",
    "name": "OpenRouter",
    "protocol": "openai",
    "base_url": "https://openrouter.ai/api/v1",
    "official_url": "https://openrouter.ai/"
  },
  "models": [
    {"remote_model": "qwen/qwen3-30b-a3b:free", "enabled": true},
    {"remote_model": "deepseek/deepseek-chat-v3-0324:free", "enabled": false}
  ],
  "credential": "一次性提交的 API Key"
}
```

接口负责校验 Provider、模型列表和 API Key，Provider 采用 upsert。每个模型生成稳定的路由 ID；已存在相同 Provider + 远程模型的路由不重复创建，而是返回 `skipped`。API Key 不进入响应、日志或目录文件，只写入本机 SecretStore，并为每条新路由保存密钥引用。

响应：

```json
{
  "data": {
    "created": [{"id": "openrouter-qwen-qwen3-30b-a3b-free"}],
    "skipped": [{"remote_model": "already-configured"}]
  }
}
```

## 前端行为

- 将单个远程模型输入替换为模型启用面板；获取成功后显示模型数量、全部启用/全部停用和每项复选框。所有模型都会提交，复选框只决定初始 enabled 状态。
- 批量保存按钮在没有获取到模型列表时阻止提交；手工输入仍兼容单模型添加。
- 目录 Provider 使用 `apiEndpoint` 去掉 `/chat/completions` 作为 Base URL，只对有 OpenAI 兼容 API 地址的条目自动导入；本地手工 Provider 仍可用。
- 编辑已有路由保持原有单模型编辑流程，不误触发批量导入。
- 保存成功后显示新增和跳过数量；单个模型的启用/停用继续使用现有 PATCH 接口。

## 安全与兼容性

- 所有 Provider、注册链接、文档链接和 API 地址只接受 HTTPS 公网 URL。
- 批量接口不返回 credential；错误信息不得包含 Key。
- 不兼容 OpenAI Chat Completions 的目录条目不自动进入 Provider 下拉框。
- 保持现有单路由 POST/PATCH 接口，以兼容已有客户端和手工配置。
