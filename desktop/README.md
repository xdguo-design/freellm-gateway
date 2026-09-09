# FreeLLM Studio（桌面版）

用 Tauri 把「本地网关 + 管理界面 + freellm.top 模型目录」封装成一个桌面应用：

- 启动时自动拉起内置的网关 sidecar（PyInstaller 打包的 `freellm_gateway`，监听 `127.0.0.1:18900`，不与你手动跑的 18787 实例冲突）；
- 每次启动随机生成 API / Admin 令牌，自动注入界面，用户无感知；
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

```powershell
# 1. 重建网关 sidecar（onedir 模式：免解压，启动只需 2-3 秒；onefile 每次启动要解压 200MB 并被 Defender 全量扫描，冷启动十几秒）
cd D:\WorkSpace\freellm-gateway
python -m PyInstaller --onedir --noconsole --name freellm-gateway --noconfirm `
  --distpath desktop/sidecar --workpath %TEMP%\pyinstaller-build --specpath %TEMP%\pyinstaller-build `
  --add-data "D:\WorkSpace\freellm-gateway\freellm_gateway\templates;freellm_gateway\templates" `
  --hidden-import uvicorn.loops.auto `
  --hidden-import uvicorn.protocols.http.auto `
  --hidden-import uvicorn.protocols.websockets.auto `
  --hidden-import uvicorn.protocols.websockets.websockets_impl `
  --hidden-import uvicorn.lifespan.on `
  freellm_gateway/desktop_entry.py

# 2. 同步到资源目录（tauri.conf.json 的 resources 映射：binaries/freellm-gateway -> sidecar/）
rm -rf desktop/src-tauri/binaries/freellm-gateway
cp -r desktop/sidecar/freellm-gateway desktop/src-tauri/binaries/freellm-gateway

# 3. 构建应用
cd desktop
npm install
npx tauri build              # 产物：NSIS 安装包 + target/release/freellm-studio.exe
npx tauri build --debug --no-bundle   # 快速验证，不打包安装器
```

产物位置：`src-tauri/target/release/freellm-studio.exe`（便携版，sidecar 在同目录）与
`src-tauri/target/release/bundle/nsis/*-setup.exe`（安装包）。
