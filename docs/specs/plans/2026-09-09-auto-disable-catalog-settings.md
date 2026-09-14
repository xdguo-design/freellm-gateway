# 自动停用失败路由与控制台联动实施计划

> **给执行者：** 任务使用 `- [ ]` 跟踪；每个竖向切片都先写失败测试，再实现并验证。

**目标：** 修复认证失败路由污染 `auto` 聚合的问题，联动模型池与同步目录，并将设置页改造成可用的运行控制台。

**非目标：** 不更换 Provider 协议、不上传凭据、不修改目录源数据格式、不实现跨 Provider 的全局停用。

**架构要点：** `ModelGateway` 负责判定路由错误，应用层通过回调持久化自动停用；目录状态由 API 根据本地 routes 注入，前端只渲染状态；设置页使用同一份 overview/route/provider 数据，不新增敏感凭据接口。

**技术栈/运行方式：** Python 3.10、FastAPI、SQLite、原生 HTML/JS、Tauri/Rust；验证命令为 `\.venv\Scripts\python.exe -m pytest -q` 和 `cargo test --manifest-path desktop\src-tauri\Cargo.toml`。

**关联设计文档：** `docs/specs/2026-09-09-auto-disable-catalog-settings-design.md`

---

## 文件变更清单

- 修改：`freellm_gateway/service.py`，在认证失败时触发路由停用回调。
- 修改：`freellm_gateway/api.py`，接入持久化回调、扩展 overview、为目录条目注入池状态。
- 修改：`freellm_gateway/templates/admin.html`，加入目录标记、设置运行信息和统一复制按钮。
- 修改：`freellm_gateway/runtime.py`，将 Repository 持久化能力传入 gateway。
- 测试：`tests/test_failover.py`、`tests/test_admin_features.py`、`tests/test_admin_api.py`、`tests/test_api.py`。
- 测试：`desktop/src-tauri/src/main.rs` 现有 Rust 单元测试保持通过。

## 任务列表

### 任务 1：认证失败自动停用

- [ ] 编写测试：真实流量收到 `authentication_error` 后 route 的 `enabled` 变为 false，并调用持久化回调；下一次 `auto` 使用第二条路由。
- [ ] 编写测试：探测收到 `authentication_error` 后同样停用，网络错误仍保持可冷却切换。
- [ ] 运行 `\.venv\Scripts\python.exe -m pytest tests\test_failover.py -q`，确认新增断言因实现缺失失败。
- [ ] 实现最小回调接口和 API 层 `Repository.save_route` 持久化，不改变其他错误策略。
- [ ] 运行 `\.venv\Scripts\python.exe -m pytest tests\test_failover.py tests\test_admin_features.py -q`，确认通过。

### 任务 2：目录状态联动

- [ ] 编写 API 测试：目录条目返回 `pool_status`，精确匹配启用/停用路由分别得到可区分状态，未匹配条目保持未加入。
- [ ] 运行 `\.venv\Scripts\python.exe -m pytest tests\test_admin_features.py tests\test_admin_api.py -q`，确认新增断言失败。
- [ ] 实现服务端匹配和脱敏状态字段；前端将“加入模型池”切换为状态徽标/查看操作，并让模型池显示目录徽标。
- [ ] 运行同一组测试并检查响应不包含 `credential`、`keyring` 或 Key。

### 任务 3：设置运行控制台与复制按钮

- [ ] 编写 HTML/API 测试：设置页包含运行统计、地址、日志/数据库路径占位字段、复制操作；概览和设置中的地址/模型名/Token 均有复制按钮。
- [ ] 运行 `\.venv\Scripts\python.exe -m pytest tests\test_admin_api.py tests\test_api.py -q`，确认新增断言失败。
- [ ] 扩展 overview 提供安全的运行元数据，重做设置页信息布局，抽取统一 `copyText` 交互和中英文反馈；不显示管理员 Token/Provider 凭据。
- [ ] 运行前端相关测试并用本地浏览器检查复制按钮、目录标记和设置页可见文本。

### 任务 4：完整回归与 EXE 验证

- [ ] 运行 `\.venv\Scripts\python.exe -m pytest -q`，预期全部通过。
- [ ] 运行 `cargo test --manifest-path desktop\src-tauri\Cargo.toml`，预期 2 个 Rust 单元测试通过。
- [ ] 重新构建 sidecar 和 Tauri release EXE，启动 `desktop\src-tauri\target\release\freellm-studio.exe`。
- [ ] 读取 EXE 动态端口，验证 `/health`、管理台、脱敏路由状态和 `auto` 非流式/流式请求；确认认证失败路由在数据库中保持停用。
- [ ] 运行 `git diff --check` 和 `git status --short`，确认无空白错误且只包含本任务变更。

## 质量门控

- [ ] 每个生产实现前都有因正确原因失败的测试。
- [ ] 不输出、不提交、不回显任何 API Key。
- [ ] 不覆盖用户已有未提交修改。
- [ ] 未通过完整测试、Rust 测试和 EXE 实测前不宣称完成。
