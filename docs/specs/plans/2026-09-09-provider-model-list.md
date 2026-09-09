# Provider 模型列表实施计划

> **给代理执行者：** 本计划基于已批准的设计文档，按 TDD 的 RED-GREEN-REFACTOR 节奏在当前会话执行。任务使用 `- [ ]` 勾选跟踪。

**目标：** 让管理台按供应商卡片展示其多个模型，并让目录添加入口自动带出对应供应商。

**架构要点：** 复用现有 Provider 与 ModelRoute 数据，前端根据 `provider_id` 分组渲染模型行，不改变数据库结构。目录添加逻辑继续使用已加载的目录 offer，并优先匹配已有 Provider。

**技术栈：** Python 3.11+、FastAPI、静态 HTML/JavaScript、pytest；验证命令为 `python -m pytest -q`、`python -m compileall freellm_gateway`、`git diff --check`。

**关联设计文档：** `docs/specs/2026-09-09-provider-model-list-design.md`

---

## 文件结构与职责

- 修改 `freellm_gateway/templates/admin.html`：Provider 卡片模型列表、空状态和目录默认 Provider 的前端行为。
- 修改 `tests/test_admin_api.py`：管理页暴露 Provider 模型列表所需的标记和空状态文案。
- 修改 `tests/test_admin_features.py`：验证 `/api/admin/providers` 与 `/api/admin/routes` 的数据可以支持同供应商多模型及跨供应商同名模型。

### 任务 1：Provider 多模型数据契约

**涉及文件：**
- 修改：`tests/test_admin_features.py`
- 修改：`freellm_gateway/api.py`（仅在测试证明现有响应缺字段时调整）

- [ ] **步骤 1：编写失败测试**

新增行为测试：创建一个 Repository，保存两个 Provider 和三个 Route，其中两个 Route 属于同一 Provider，另一个 Route 使用不同 Provider 但复用相同远端模型名；断言两个管理接口分别返回完整 Provider 与 Route 数据，且不因为同名模型去重。

```python
def test_admin_lists_provider_and_routes_without_collapsing_same_model_name(tmp_path):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    repository.initialize()
    repository.save_provider(Provider("p1", "Provider One", "openai", "https://p1.example/v1", "https://p1.example"))
    repository.save_provider(Provider("p2", "Provider Two", "openai", "https://p2.example/v1", "https://p2.example"))
    routes = [
        ModelRoute(id="p1-a", provider_id="p1", remote_model="shared-model", priority=1),
        ModelRoute(id="p1-b", provider_id="p1", remote_model="second-model", priority=2),
        ModelRoute(id="p2-a", provider_id="p2", remote_model="shared-model", priority=3),
    ]
    for route in routes:
        repository.save_route(route)
    app = create_app(ModelGateway(routes, {}), repository=repository, api_token="api", admin_token="admin")
    client = TestClient(app)
    headers = {"Authorization": "Bearer admin"}

    providers = client.get("/api/admin/providers", headers=headers)
    listed_routes = client.get("/api/admin/routes", headers=headers)

    assert [item["id"] for item in providers.json()["data"]] == ["p1", "p2"]
    assert [item["id"] for item in listed_routes.json()["data"]] == ["p1-a", "p1-b", "p2-a"]
    assert [item["provider_name"] for item in listed_routes.json()["data"]] == [
        "Provider One", "Provider One", "Provider Two"
    ]
```

- [ ] **步骤 2：运行测试确认失败**

运行：`python -m pytest tests/test_admin_features.py::test_admin_lists_provider_and_routes_without_collapsing_same_model_name -v`

预期：通过。该行为使用现有接口确认数据契约已经满足，若测试失败只修复测试与当前数据装配的实际缺口。

- [ ] **步骤 3：最小实现**

仅在步骤 2 暴露缺口时，调整 `route_json` 或 Provider 列表响应；不得改变已有字段含义，不返回凭据或其他敏感字段。若现有实现已满足，则保持生产代码不变。

- [ ] **步骤 4：运行并确认通过**

运行：`python -m pytest tests/test_admin_features.py::test_admin_lists_provider_and_routes_without_collapsing_same_model_name -v`

预期：通过。

### 任务 2：Provider 卡片逐模型渲染

**涉及文件：**
- 修改：`tests/test_admin_api.py`
- 修改：`freellm_gateway/templates/admin.html`

- [ ] **步骤 1：编写失败测试**

增加页面契约断言，确保模板包含 Provider 模型列表、模型空状态和分组渲染所需标识。

```python
def test_admin_page_exposes_provider_model_list_markup():
    response = TestClient(create_app(ModelGateway([], {}), api_token="api", admin_token="admin")).get("/admin")

    assert response.status_code == 200
    assert 'id="providers"' in response.text
    assert "provider-model-list" in response.text
    assert "noProviderModels" in response.text
```

- [ ] **步骤 2：运行测试确认失败**

运行：`python -m pytest tests/test_admin_api.py::test_admin_page_exposes_provider_model_list_markup -v`

预期：失败，当前 Provider 渲染函数只有名称、ID、协议和 Base URL，没有模型列表标识与空状态文案。

- [ ] **步骤 3：最小实现**

在 `admin.html` 中：

1. 增加中英文 `noProviderModels` 文案。
2. 修改 `renderProviders`，用 `state.routes.filter(route => route.provider_id === provider.id)` 获取当前供应商的路由；保持路由原顺序，不按远端模型名去重。
3. 每个模型渲染独立 `.provider-model-list` 行，显示 `display_name || remote_model`、远端模型名、能力标签和健康/禁用状态。
4. 供应商没有模型时渲染 `noProviderModels`，不隐藏供应商基础信息和“发现模型”按钮。
5. 在响应式样式中允许模型行换行，不改变现有模型池表格布局。

示例渲染逻辑：

```javascript
const providerRoutes=provider=>state.routes.filter(route=>route.provider_id===provider.id);
const renderProviderModels=provider=>{
  const routes=providerRoutes(provider);
  if(!routes.length)return `<div class="provider-model-list muted">${t('noProviderModels')}</div>`;
  return `<div class="provider-model-list">${routes.map(route=>`
    <div class="provider-model-row">
      <div><b>${esc(route.display_name||route.remote_model)}</b><small>${esc(route.remote_model)}</small></div>
      <div>${tags(route.capabilities)}</div>
      <span class="status ${routeStatusClass(route.health)}">${esc(route.health)}${route.enabled?'':' · '+t('disable').toLowerCase()}</span>
    </div>`).join('')}</div>`;
};
```

- [ ] **步骤 4：运行并确认通过**

运行：`python -m pytest tests/test_admin_api.py::test_admin_page_exposes_provider_model_list_markup tests/test_admin_api.py -v`

预期：通过。

### 任务 3：目录入口自动带出 Provider

**涉及文件：**
- 修改：`tests/test_admin_api.py`
- 修改：`freellm_gateway/templates/admin.html`

- [ ] **步骤 1：编写失败测试**

页面契约测试断言目录添加逻辑包含已有 Provider 优先匹配和目录 Provider 回退逻辑。

```python
def test_admin_page_exposes_catalog_provider_autofill_logic():
    response = TestClient(create_app(ModelGateway([], {}), api_token="api", admin_token="admin")).get("/admin")

    assert "catalogMatch" in response.text
    assert "matched?.id" in response.text
    assert "catalogMatch?.id" in response.text
```

- [ ] **步骤 2：运行测试确认失败**

运行：`python -m pytest tests/test_admin_api.py::test_admin_page_exposes_catalog_provider_autofill_logic -v`

预期：通过。现有未提交实现已经包含该逻辑；该测试用于锁定此次确认的行为，若失败则补齐最小匹配逻辑。

- [ ] **步骤 3：最小实现**

若步骤 2 失败，调整 `openRouteModal` 的 Provider 选择顺序为：编辑路由的 Provider → 已有 Provider 与目录 provider 名称匹配项 → 目录 offer 对应的 catalog Provider → 其他目录 Provider → 第一个本地 Provider。不得在普通添加时自动覆盖用户已选值。

- [ ] **步骤 4：运行并确认通过**

运行：`python -m pytest tests/test_admin_api.py -v`

预期：通过。

### 任务 4：整体验证

**涉及文件：** 无新增修改。

- [ ] **步骤 1：运行完整测试**

运行：`python -m pytest -q`

预期：全部通过。

- [ ] **步骤 2：运行编译与空白检查**

运行：`python -m compileall freellm_gateway`；`git diff --check`

预期：Python 编译成功，Git 不报告空白错误。

- [ ] **步骤 3：检查敏感字段未进入页面**

运行：`rg -n "credential_ref|temporary-key|API_KEY" freellm_gateway/templates/admin.html tests/test_admin_api.py tests/test_admin_features.py`

预期：管理台模板不包含凭据值或凭据引用；测试中只允许出现既有安全断言文本或测试用例字符串。
