# 添加模型弹窗自定义 Provider 实施计划

> **给代理执行者：** 推荐配合 `subagent-driven-development（子代理驱动开发）`（每任务独立子代理 + 两阶段审查）或在本会话内按勾选逐步执行并在批次节点与用户确认。任务使用 `- [ ]` 勾选跟踪。

**目标：** 在添加模型弹窗内直接填写自定义 Provider 并获取、保存其模型。

**架构要点：** 前端用特殊下拉值区分自定义 Provider，并从表单构造临时 Provider payload；模型发现调用已有未保存连接接口，保存继续调用现有 Provider/route 接口。后端不新增协议或数据库字段，凭据继续只进入本地 SecretStore。

**技术栈：** Python、FastAPI、SQLite、原生 HTML/CSS/JavaScript、pytest。

**关联设计文档：** `docs/specs/2026-09-14-custom-provider-model-design.md`

---

## 文件结构

- 修改：`freellm_gateway/templates/admin.html` — 添加模型弹窗标记、双语文案、自定义 Provider 状态同步、发现和保存分支。
- 修改：`tests/test_admin_api.py` — 管理台 HTML 契约测试。
- 修改：`tests/test_admin_features.py` — 自定义 Provider API 保存/模型路由行为测试。

### 任务 1：管理台 HTML 契约

**涉及文件：**

- 修改：`tests/test_admin_api.py`
- 修改：`freellm_gateway/templates/admin.html`

- [ ] **步骤 1：编写失败测试**

在 `tests/test_admin_api.py` 末尾增加：

```python
def test_admin_page_exposes_custom_provider_fields_in_add_model_form():
    response = TestClient(create_app(ModelGateway([], {}), api_token="api", admin_token="admin")).get("/admin")

    assert response.status_code == 200
    assert 'value="__custom__"' in response.text
    for marker in (
        'id="custom-provider-fields"',
        'name="custom_provider_id"',
        'name="custom_provider_name"',
        'name="custom_protocol"',
        'name="custom_base_url"',
        'name="custom_official_url"',
        "customProviderFromForm",
        "syncCustomProviderFields",
        "/api/admin/connection/models",
    ):
        assert marker in response.text
```

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/test_admin_api.py::test_admin_page_exposes_custom_provider_fields_in_add_model_form -q`

预期：失败，原因是当前添加模型表单没有 `__custom__` 选项、自定义字段和对应 JavaScript 函数。

- [ ] **步骤 3：最小实现**

在 `freellm_gateway/templates/admin.html` 中：

1. 给 Provider 下拉框追加 `<option value="__custom__">自定义 Provider…</option>`，并加入英文翻译。
2. 在 Provider 字段下追加隐藏的 `#custom-provider-fields`，包含 `custom_provider_id`、`custom_provider_name`、`custom_protocol`、`custom_base_url`、`custom_official_url` 五个字段。
3. 增加 `CUSTOM_PROVIDER_ID='__custom__'`、`customProviderFromForm(form)` 和 `syncCustomProviderFields()`。
4. `selectedProvider()` 在特殊值下返回表单构造的 Provider payload；非特殊值保持原有 `providerChoices()` 查找逻辑。
5. Provider 切换事件调用 `syncCustomProviderFields()`；已有 Provider 选择继续调用 `applyProviderMetadata()`。

自定义字段的协议选项使用现有 `openai`、`anthropic`、`gemini` 值，Base URL 使用现有协议默认值和 placeholder；自定义 Provider 字段默认隐藏。

- [ ] **步骤 4：运行测试确认通过**

运行：`pytest tests/test_admin_api.py::test_admin_page_exposes_custom_provider_fields_in_add_model_form -q`

预期：通过。

### 任务 2：自定义 Provider 的模型发现

**涉及文件：**

- 修改：`tests/test_admin_api.py`
- 修改：`freellm_gateway/templates/admin.html`

- [ ] **步骤 1：编写失败测试**

在同一测试模块增加静态行为契约：

```python
def test_admin_page_uses_unsaved_connection_discovery_for_custom_provider():
    response = TestClient(create_app(ModelGateway([], {}), api_token="api", admin_token="admin")).get("/admin")

    assert response.status_code == 200
    script = response.text
    assert "customProviderFromForm(form)" in script
    assert "'/api/admin/connection/models'" in script
    assert "'/api/admin/providers/'+encodeURIComponent(providerId)+'/models'" in script
```

将第二个断言写成当前代码已有内容，确认测试先因第一项缺少自定义分支而失败；如果现有静态代码使测试意外通过，则改为对自定义分支周围的 `provider.protocol` 和 `provider.base_url` payload 标记做精确断言，再运行确认失败。

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/test_admin_api.py::test_admin_page_uses_unsaved_connection_discovery_for_custom_provider -q`

预期：失败，原因是 `fetchProviderModels` 当前总是先 `ensureProvider()`，再调用已保存 Provider 模型接口。

- [ ] **步骤 3：最小实现**

修改 `fetchProviderModels`：

```javascript
const provider = selectedProvider();
if (!provider) {
  showMessage(t('providerRequired'), 'error');
  return;
}
const credential = form.elements.credential.value.trim();
if (!credential) {
  showMessage(t('credentialRequired'), 'error');
  return;
}
const custom = form.elements.provider_id.value === CUSTOM_PROVIDER_ID;
const result = custom
  ? await api('/api/admin/connection/models', {
      method: 'POST',
      body: JSON.stringify({provider, credential}),
    })
  : await api('/api/admin/providers/' + encodeURIComponent(provider.id) + '/models', {
      method: 'POST',
      body: JSON.stringify({credential}),
    });
```

保留现有模型 datalist、批量勾选、首个模型自动填入和按钮恢复逻辑。发现失败时保留自定义字段与当前表单内容。

- [ ] **步骤 4：运行测试确认通过**

运行：`pytest tests/test_admin_api.py::test_admin_page_uses_unsaved_connection_discovery_for_custom_provider -q`

预期：通过。

### 任务 3：自定义 Provider 保存与路由创建

**涉及文件：**

- 修改：`tests/test_admin_features.py`
- 修改：`freellm_gateway/templates/admin.html`

- [ ] **步骤 1：编写失败测试**

在 `tests/test_admin_features.py` 增加：

```python
def test_admin_can_save_custom_provider_and_route(tmp_path):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    app = create_app(
        ModelGateway([], {}),
        repository=repository,
        secrets=FakeSecrets(),
        api_token="api",
        admin_token="admin",
    )
    client = TestClient(app)
    headers = {"Authorization": "Bearer admin"}

    provider = {
        "id": "custom-openai",
        "name": "Custom OpenAI",
        "protocol": "openai",
        "base_url": "https://llm.example/v1",
        "official_url": "https://llm.example",
    }
    response = client.post(
        "/api/admin/routes/bulk",
        headers=headers,
        json={"provider": provider, "models": [{"remote_model": "custom-model"}], "credential": "secret"},
    )

    assert response.status_code == 200
    assert repository.list_providers()[0].id == "custom-openai"
    assert repository.list_routes()[0].remote_model == "custom-model"
    assert "secret" not in response.text
```

在测试文件顶部增加与 `tests/test_persistence_api.py` 相同的最小 `FakeSecrets`（`save` 返回 `memory://...`，`get` 从字典读取），不修改生产接口。

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/test_admin_features.py::test_admin_can_save_custom_provider_and_route -q`

预期：测试先通过，因为后端接口已经支持临时 Provider 保存；该测试用于锁定本次复用的保存契约，不以生产代码失败作为必要条件。自定义前端分支由任务 1、2 的 RED 测试覆盖。

- [ ] **步骤 3：最小实现**

修改 `route-form` submit handler：

1. 自定义 Provider 提交前读取 `customProviderFromForm(form)`。
2. 多模型时把该 payload 放入现有 `/api/admin/routes/bulk` 的 `provider` 字段。
3. 单模型时先调用现有 `ensureProvider()`，使自定义 Provider 写入 `/api/admin/providers`，再调用现有 `/api/admin/routes`。
4. `ensureProvider()` 对自定义 Provider 不使用目录 Provider 的 `offer` 元数据；仅提交五个 Provider 字段。
5. 保存成功后沿用现有刷新、提示和表单关闭逻辑。

新增 `customProviderRequired` 双语提示，并在保存前对五个自定义字段执行 `required` 检查。自定义 Provider 选择状态下不从空的目录匹配结果覆盖 `public_url`、`public_docs_url` 和 `free_summary`。

- [ ] **步骤 4：运行测试确认通过**

运行：`pytest tests/test_admin_features.py::test_admin_can_save_custom_provider_and_route -q`

预期：通过，Provider 和模型路由均持久化，响应和路由元数据不包含凭据明文。

### 任务 4：回归验证与重构

**涉及文件：**

- 修改：`freellm_gateway/templates/admin.html`（仅在测试反馈要求时）
- 修改：相关测试文件（仅补充明确失败边界）

- [ ] **步骤 1：运行定向回归测试**

运行：`pytest tests/test_admin_api.py tests/test_admin_features.py -q`

预期：全部通过；失败时只修复与本次自定义 Provider 分支相关的行为，不改变无关的现有工作区改动。

- [ ] **步骤 2：运行完整测试套件**

运行：`pytest -q`

预期：完整测试套件通过。

- [ ] **步骤 3：静态安全检查**

运行：`rg -n "credential_ref|keyring://|custom_provider|customProvider" freellm_gateway/templates/admin.html tests/test_admin_api.py tests/test_admin_features.py`

预期：管理台 HTML 不包含 `credential_ref` 或 `keyring://`；自定义字段和函数只包含非秘密字段名，测试只验证凭据未出现在响应中。

- [ ] **步骤 4：提交变更**

在确认 diff 只包含本次设计文档、实施计划、实现和测试后运行：

```bash
git diff --check
git add freellm_gateway/templates/admin.html tests/test_admin_api.py tests/test_admin_features.py docs/specs/2026-09-14-custom-provider-model-design.md docs/specs/plans/2026-09-14-custom-provider-model.md
git commit -m "feat: support custom providers in model dialog"
```
