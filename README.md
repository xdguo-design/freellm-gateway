# FreeLLM Gateway

本地运行的多 Provider 模型网关，提供 OpenAI 兼容接口和 FreeLLM Studio 桌面控制台。

![FreeLLM Studio](docs/screenshots/freellm-studio-overview.png)

## 功能

- 统一管理多个 Provider 和模型
- 从 Provider API 获取多个模型，一次性批量加入模型池
- 每个模型独立启用、停用、探测、删除和调整优先级
- `auto` 模式按优先级、能力和健康状态自动路由，并支持失败切换
- 支持文本、长上下文、视觉和生图能力标签
- 从 `freellm.top` 目录自动带出 Provider、注册地址、文档和免费额度说明
- API Key 仅保存在本机凭据存储，不写入目录导出或接口响应
- Windows 桌面版启动时自动运行本地网关，不弹出 CMD 窗口

## 桌面版

直接运行构建产物：

```powershell
desktop/src-tauri/target/release/freellm-studio.exe
```

桌面版会自动启动网关、打开管理台，并将 Provider 注册页转交系统浏览器。

构建桌面版需要 Node.js、Rust stable、Visual Studio C++ Build Tools 和 Python 3.10+：

```powershell
cd D:\WorkSpace\freellm-gateway
& D:\Python\Python310\python.exe -m PyInstaller --onedir --noconsole --name freellm-gateway --noconfirm `
  --distpath desktop/sidecar --add-data 'D:\WorkSpace\freellm-gateway\freellm_gateway\templates;freellm_gateway\templates' `
  freellm_gateway/desktop_entry.py
cd desktop
npm install
npm run build
```

更多桌面构建说明见 [`desktop/README.md`](desktop/README.md)。

## 开发运行

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
python -m pytest -q
python -m freellm_gateway.cli run --host 127.0.0.1 --port 8765
```

管理页面：`http://127.0.0.1:8765/admin`

OpenAPI 文档：`http://127.0.0.1:8765/docs`

网关接口：`http://127.0.0.1:8765/v1`

## 添加 Provider 和模型

1. 打开“添加模型”，选择目录中的 Provider；注册地址、Base URL 和文档会自动带出。
2. 在 Provider 官网注册并创建 API Key，将 Key 粘贴到窗口。
3. 点击“获取所有模型”。
4. 所有返回模型会一次性加入模型池；取消某项的“启用”即可让它保持停用状态。
5. 保存后，可以在模型池中单独测试、启用或停用每个模型。

以 OpenRouter 为例，注册和创建 Key：[https://openrouter.ai/keys](https://openrouter.ai/keys)。

## OpenAI 兼容接口

所有请求使用：

```http
Authorization: Bearer <FREELLM_GATEWAY_API_TOKEN>
```

```powershell
$headers = @{ Authorization = "Bearer $env:FREELLM_GATEWAY_API_TOKEN" }
Invoke-RestMethod http://127.0.0.1:8765/v1/models -Headers $headers

Invoke-RestMethod http://127.0.0.1:8765/v1/chat/completions `
  -Method Post -Headers $headers -ContentType "application/json" `
  -Body (@{ model="auto"; messages=@(@{ role="user"; content="你好" }) } | ConvertTo-Json)
```

`model` 可以使用 `/v1/models` 返回的路由 ID；使用 `auto` 时，网关会按优先级从上到下尝试启用的模型路由。

支持的接口：

- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/images/generations`

## 安全说明

默认只监听本机回环地址。请将真实 API Token 放入未纳入 Git 的 `.env` 或系统环境变量，不要提交 API Key、数据库、日志和构建缓存。
