# 桌面版 GA4 页面打开统计 实施计划

> **给代理执行者：** 按 TDD 的红—绿—重构节奏执行；保持现有工作区改动，不覆盖无关文件。

**目标：** 为桌面启动页增加可配置、每页面会话最多一次的 GA4 `page_view`。

**架构要点：** Rust 启动入口读取 `FREELLM_GA_MEASUREMENT_ID` 并注入 WebView；静态启动页负责懒加载 GA4、手动发送一次 page view，并用 `sessionStorage` 去重。统计失败不影响网关和管理页。

**技术栈：** Tauri 2/Rust、静态 HTML/JavaScript；验证命令为 `\.venv\Scripts\python.exe -m pytest tests/test_desktop_analytics.py -q` 与 `cargo test --manifest-path desktop\src-tauri\Cargo.toml`。

**关联设计文档：** `docs/specs/2026-09-10-desktop-ga4-page-view-design.md`

---

### 任务 1：启动页统计契约

**涉及文件：**
- 新建：`tests/test_desktop_analytics.py`
- 修改：`desktop/ui/index.html`

- [ ] **步骤 1：编写失败测试**

测试读取启动页源码，验证运行时配置、GA4 脚本、手动 `page_view` 和会话去重标记存在。

- [ ] **步骤 2：运行测试确认失败**

运行：`\.venv\Scripts\python.exe -m pytest tests/test_desktop_analytics.py -q`

预期：因启动页尚未包含 GA4 配置和 `page_view` 逻辑而失败。

- [ ] **步骤 3：最小实现**

在启动页脚本中读取 `window.__FREELLM_GA_MEASUREMENT_ID__`；ID 非空且 `sessionStorage` 未标记时，加载 `https://www.googletagmanager.com/gtag/js?id=<ID>`，设置 `send_page_view: false`，手动发送一次 `page_view`，最后写入会话标记。脚本加载失败只静默结束。

- [ ] **步骤 4：运行测试确认通过**

运行：`\.venv\Scripts\python.exe -m pytest tests/test_desktop_analytics.py -q`

预期：全部通过。

### 任务 2：Tauri 注入 Measurement ID

**涉及文件：**
- 修改：`desktop/src-tauri/src/main.rs`

- [ ] **步骤 1：编写失败测试**

扩展 Rust 单元测试，验证初始化脚本包含注入的 GA4 Measurement ID。

- [ ] **步骤 2：运行测试确认失败**

运行：`cargo test --manifest-path desktop\src-tauri\Cargo.toml init_script_injects_ga_measurement_id`

预期：因初始化脚本签名尚未接收 Measurement ID 而失败。

- [ ] **步骤 3：最小实现**

让 `init_script` 接收 GA4 ID，在 Tauri setup 中读取 `FREELLM_GA_MEASUREMENT_ID`，并把值安全注入 `window.__FREELLM_GA_MEASUREMENT_ID__`；保持现有 token 与端口注入逻辑不变。

- [ ] **步骤 4：运行测试确认通过**

运行：`cargo test --manifest-path desktop\src-tauri\Cargo.toml`

预期：Rust 测试全部通过。

### 任务 3：回归验证

**涉及文件：** 无新增文件。

- [ ] **步骤 1：运行 Python 回归测试**

运行：`\.venv\Scripts\python.exe -m pytest -q`

预期：现有 Python 测试全部通过。

- [ ] **步骤 2：检查差异**

运行：`git diff --check`

预期：无空白错误。
