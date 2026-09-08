# FreeLLM Gateway

本地运行的个人模型网关，统一管理多个 Provider 和模型，支持优先级排序、健康探测、失败切换和 FreeLLM 网站目录导出。

## 开发运行

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
python -m pytest -q
python -m freellm_gateway.cli run --host 127.0.0.1 --port 8765
```

API 根地址：`http://127.0.0.1:8765/v1`。管理页面：`http://127.0.0.1:8765/admin`，OpenAPI 文档：`http://127.0.0.1:8765/docs`。

首次启动时，终端会打印随机生成的 API token 和 admin token。也可以先复制 `.env.example` 为 `.env`，自行设置两个长随机令牌。

## 安全边界

默认只监听本机回环地址。真实令牌放在未纳入 Git 的 `.env` 或系统凭据存储中，不要写入目录导出文件。

## 对外 OpenAI 兼容接口

所有调用接口都使用 `Authorization: Bearer <FREELLM_GATEWAY_API_TOKEN>`。`model` 使用 `/v1/models` 返回的路由 ID，或者使用 `auto` 让网关按请求能力、健康状态和优先级自动选择。

```powershell
$headers = @{ Authorization = "Bearer $env:FREELLM_GATEWAY_API_TOKEN" }
Invoke-RestMethod http://127.0.0.1:8765/v1/models -Headers $headers

Invoke-RestMethod http://127.0.0.1:8765/v1/chat/completions `
  -Method Post -Headers $headers -ContentType "application/json" `
  -Body (@{ model="auto"; messages=@(@{ role="user"; content="你好" }) } | ConvertTo-Json)
```

支持的公共接口：

- `GET /v1/models`：列出 `auto` 和所有启用的模型路由。
- `POST /v1/chat/completions`：普通文本、长上下文和图片输入，支持 `stream=true`。
- `POST /v1/images/generations`：选择带 `image_generation` 能力的路由。

管理页面可以新增 Provider 和模型、修改能力标签与优先级、上下移动排序、启停路由、单模型/全量探测、查看健康详情、导出目录并同步到 `FREELLM_GATEWAY_SITE_REPO`。
