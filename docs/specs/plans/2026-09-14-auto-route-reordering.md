# Auto 路由健康排序实施计划

> **给代理执行者：** 按 TDD 的 RED-GREEN-REFACTOR 节奏执行。

**目标：** 为 `auto` 请求增加调用前预检，并根据真实成功/失败结果持久化调整路由优先级。

**架构要点：** `ModelGateway` 负责候选预检、真实调用和动态排序；现有 `RoutePolicy` 继续负责健康/冷却；通过 `on_route_changed` 保存 priority 变更。手动 `probe()` 默认保持诊断隔离，自动预检使用内部非隔离路径。

**技术栈：** Python、pytest、pytest-asyncio；验证命令为 `pytest tests/test_failover.py tests/test_probe.py tests/test_health.py -q` 和 `pytest -q`。

**关联设计文档：** `docs/specs/2026-09-14-auto-route-reordering-design.md`

---

### 任务 1：普通 completion 的排序回归

**涉及文件：**
- 修改：`tests/test_failover.py`
- 修改：`freellm_gateway/service.py`

- [ ] 编写测试：模拟高优先级路由预检成功但真实请求返回 `invalid_request`，低优先级路由预检和真实请求成功；断言低优先级路由成功、两条路由 priority 交换、回调收到排序结果。
- [ ] 运行 `pytest tests/test_failover.py::<test_name> -q`，当前实现应因未执行预检/未调整 priority 失败。
- [ ] 实现内部自动预检和 `_promote_route` / `_demote_route`，只让 `auto` 进入该流程。
- [ ] 重新运行该测试并确认通过。

### 任务 2：streaming 与预检失败

**涉及文件：**
- 修改：`tests/test_failover.py`
- 修改：`freellm_gateway/service.py`

- [ ] 编写测试：预检失败路由不执行真实流式请求，下一条路由完成流式响应并被提升。
- [ ] 运行目标测试确认 RED。
- [ ] 为 streaming 接入相同的候选预检和排序回调。
- [ ] 运行目标测试确认 GREEN。

### 任务 3：保护手动探测隔离和全量回归

**涉及文件：**
- 修改：`tests/test_probe.py`（仅在需要补充行为断言时）
- 修改：`freellm_gateway/service.py`

- [ ] 增加手动探测失败不改变 priority 的断言。
- [ ] 运行 `pytest tests/test_failover.py tests/test_probe.py tests/test_health.py -q`。
- [ ] 运行 `pytest -q`。
- [ ] 检查 `git diff`，确认只包含本需求变更和新增规格/计划文档，不覆盖用户已有改动。
