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

API 根地址：`http://127.0.0.1:8765/v1`。

首次启动时，终端会打印随机生成的 API token 和 admin token。也可以先复制 `.env.example` 为 `.env`，自行设置两个长随机令牌。

## 安全边界

默认只监听本机回环地址。真实令牌放在未纳入 Git 的 `.env` 或系统凭据存储中，不要写入目录导出文件。
