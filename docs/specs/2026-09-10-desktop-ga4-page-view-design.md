# FreeLLM 桌面版 GA4 页面打开统计设计

## 目标

每次 FreeLLM 桌面程序创建一轮新的页面会话时，向 Google Analytics 4 上报一次 `page_view`，让程序启动可以被统计为一次网页打开。

## 范围与配置

- 只修改桌面启动页，不给模型请求或管理 API 增加统计副作用。
- 通过运行环境变量 `FREELLM_GA_MEASUREMENT_ID` 注入 GA4 Measurement ID（格式如 `G-XXXXXXXXXX`）。
- 未配置 Measurement ID 时不加载 Google Analytics 脚本、不发送网络请求。
- 不上传 API Key、用户提示词、模型响应或其他敏感数据。

## 数据流

1. Tauri 启动时读取 `FREELLM_GA_MEASUREMENT_ID`。
2. Tauri 初始化脚本把值放入启动页的只读运行时配置。
3. 启动页只在存在 Measurement ID 且当前页面会话未上报过时加载 `gtag.js`。
4. 关闭自动 page view，手动发送一个 `page_view` 事件。
5. 用 `sessionStorage` 标记已上报，避免重试、刷新或跳转到管理页重复计算。

## 错误处理

- Measurement ID 为空时静默跳过。
- Google 脚本加载失败不影响网关启动、管理页跳转或模型调用。
- 统计功能不阻塞本地网关健康检查。

## 验收标准

- 配置 ID 后，每个新的桌面页面会话最多出现一个 `page_view`。
- 启动页重试和跳转管理页不会额外产生 `page_view`。
- 未配置 ID 时页面源码仍包含统计逻辑，但运行时不会请求 Google。
- 现有 Python 与 Rust 测试继续通过。
