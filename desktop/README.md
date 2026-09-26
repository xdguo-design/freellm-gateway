# FreeLLM Studio（桌面版）

用 Tauri 把「本地网关 + 管理界面 + freellm.top 模型目录」封装成一个桌面应用：

- 启动时自动拉起内置的网关 sidecar（PyInstaller 打包的 `freellm_gateway`，监听 `127.0.0.1:18900`，不与你手动跑的 18787 实例冲突）；
- 首次启动生成并保存 API / Admin 令牌，后续启动保持不变，自动注入界面；
- 窗口内先显示启动页，网关健康检查通过后自动进入管理台（模型池 / 目录发现 / 注册入口）；
- **关闭窗口只是隐藏到系统托盘**，网关在后台继续服务；托盘左键单击恢复窗口，右键菜单提供「显示主界面 / 退出」——只有托盘菜单的「退出」才会真正结束应用；
- 所有外链（Provider 注册页、文档、freellm.top）自动转交系统默认浏览器打开，webview 永远留在应用内；
- 退出应用时自动结束网关子进程（额外绑定了 Windows Job Object，即使进程被强杀也能保证网关进程树被清理）；数据库与目录导出存放在 `%APPDATA%/top.freellm.desktop/`。

## 目录结构

```
desktop/
├── ui/                  # 启动页（静态页，轮询 /health 后跳转 /admin）
├── sidecar/             # PyInstaller 产物 freellm-gateway.exe（gitignored）
└── src-tauri/
    ├── src/main.rs      # sidecar 拉起、令牌注入、外链拦截
    ├── binaries/        # 带 target triple 的 sidecar 副本（Tauri externalBin）
    └── icons/           # tauri icon 生成
```

## 构建要求

- Rust stable (MSVC) + Visual Studio Build Tools (C++ 工作负载)
- Node.js ≥ 18
- Python 3.10 + PyInstaller（仅重建 sidecar 时需要）

## 构建步骤

推荐直接从仓库根目录执行统一脚本：

```powershell
.\scripts\build_desktop.ps1
```

快速 Debug 验证：

```powershell
.\scripts\build_desktop.ps1 -Debug
```

脚本会自动完成：

1. 安装并构建 `web/` 的 React/TypeScript 管理后台；
2. 用 PyInstaller 构建 Python gateway sidecar，并同时打包 `templates/` 与 `static/admin/`；
3. 把 sidecar 同步到 Tauri resources；
4. 安装桌面依赖并执行 Tauri build。

正式产物位置：

```text
desktop/src-tauri/target/release/freellm-studio.exe
desktop/src-tauri/target/release/bundle/nsis/*-setup.exe
```

React 管理台和 Web 版共用同一份生产 bundle，不再维护单独的桌面 UI。Tauri 运行时通过 `window.__FREELLM_GATEWAY_PORT__` 将 React API 请求定向到本机 sidecar `127.0.0.1:18900`，Admin Token 也使用与 Web 管理台一致的 sessionStorage key。

## GA4 页面打开统计

桌面启动页支持通过 `FREELLM_GA_MEASUREMENT_ID` 配置 Google Analytics 4 Measurement ID。
配置后，每次新的桌面页面会话只上报一次 `page_view`；未配置时不会加载 Google Analytics 或发送统计请求。

```powershell
$env:FREELLM_GA_MEASUREMENT_ID = "G-XXXXXXXXXX"
npx tauri dev
```

发布版启动时也必须在其运行环境中提供这个变量。统计不会上传 API Key、提示词或模型响应。
