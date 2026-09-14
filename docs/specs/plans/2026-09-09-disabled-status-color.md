# 停用状态颜色实施计划

> **给代理执行者：** 任务使用 `- [ ]` 勾选跟踪；每步写清路径、命令、预期输出与验收标准。

**目标：** 将管理界面的“停用”状态显示为灰蓝色，与绿色“健康”状态区分。

**非目标：** 不修改后端健康状态、路由启停逻辑、API 响应或其他错误状态颜色。

**架构要点：** 状态颜色由模板内的 `routeStatusClass` 统一决定。渲染模型池、健康监控和 Provider 模型列表时，将启用状态作为第二个参数传给它；停用状态优先返回 `disabled`，其余状态沿用现有健康分类。

**技术栈/运行方式：** FastAPI 模板内嵌 JavaScript/CSS；使用 `pytest tests/test_admin_api.py -q` 验证页面契约。

**关联设计文档：** `docs/specs/2026-09-09-disabled-status-color-design.md`

---

## 文件变更清单

- 新建：
  - `docs/specs/2026-09-09-disabled-status-color-design.md`（已确认的界面设计与验收标准）。
  - `docs/specs/plans/2026-09-09-disabled-status-color.md`（本次实施步骤）。
- 修改：
  - `freellm_gateway/templates/admin.html`（增加停用样式并统一渲染状态类）。
- 测试：
  - `tests/test_admin_api.py`（验证停用状态类与样式契约）。

## 任务 1：停用状态视觉分类

**涉及文件：**

- 修改：`freellm_gateway/templates/admin.html`
- 测试：`tests/test_admin_api.py`

- [x] **步骤 1：编写失败测试**

在 `test_admin_page_exposes_model_fetch_key_and_registration_controls` 后增加：

```python
def test_admin_page_uses_distinct_color_class_for_disabled_status():
    app = create_app(ModelGateway([], {}), api_token="api", admin_token="admin")

    response = TestClient(app).get("/admin")

    assert ".disabled { color:" in response.text
    assert "routeStatusClass=(health,enabled)=>enabled?'disabled'" in response.text
```

- [x] **步骤 2：运行并确认失败**

运行：`pytest tests/test_admin_api.py::test_admin_page_uses_distinct_color_class_for_disabled_status -q`

预期：失败，因为当前模板没有 `.disabled` 样式，也没有把 `enabled` 纳入状态类计算。

- [x] **步骤 3：最小实现**

在 `freellm_gateway/templates/admin.html` 的状态样式区域加入：

```css
.disabled { color:#aab8d1; border:1px solid #536785; }
```

将状态类函数改为：

```javascript
const routeStatusClass=(health,enabled)=>enabled?(health==='healthy'?'ok':['slow','rate_limited','quota_exhausted','cooldown'].includes(health)?'slow':'bad'):'disabled';
```

并将模型池、健康监控、Provider 模型列表中的 `routeStatusClass(route.health)` 改为 `routeStatusClass(route.health,route.enabled)`。

- [x] **步骤 4：运行并确认通过**

运行：`pytest tests/test_admin_api.py::test_admin_page_uses_distinct_color_class_for_disabled_status tests/test_admin_api.py -q`

预期：全部通过，且页面契约确认停用状态拥有独立类和样式。

- [x] **步骤 5：回归验证**

运行：`pytest -q`

预期：项目测试全部通过。
