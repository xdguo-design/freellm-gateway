# 多连接与多模型选择实施计划

> **给代理执行者：** 推荐配合 `subagent-driven-development（子任务独立执行 + 两阶段审查）`；本计划也可在当前会话中按勾选逐步执行。每个测试先执行 RED，再执行最小 GREEN 实现，保留现有用户改动。

**目标：** 管理台完整保留同一 Provider 的多个连接候选，让用户分别验证连接、选择模型和凭据，并一次性保存多个连接的模型路由；同时加入 AtomGit CodingPlan 本机 sidecar 预设。

**架构要点：** Provider 连接以 `provider + normalized_base_url` 区分，现有数据库表和单连接接口保持兼容；新的批量连接接口按连接返回 `created`、`skipped`、`failed`，部分失败不回滚其他连接。AtomGit OAuth、额度和请求签名留在用户本机 sidecar，网关只访问 loopback OpenAI-compatible Base URL，并只在 keyring 保存 sidecar API Key。

**技术栈：** Python 3.10、FastAPI、SQLite、原生 HTML/JavaScript 管理台、pytest；验证命令为 `pytest -q`。

**关联设计文档：** `docs/specs/2026-09-10-multi-connection-model-selection-design.md`

---

## 文件清单

实现前先确认以下职责边界；除测试和文档外，不新增数据库迁移：

- 修改 `freellm_gateway/api.py`：集中实现 loopback Base URL 校验、批量连接 payload 校验、连接匹配、临时模型发现接口和批量保存接口。
- 修改 `freellm_gateway/templates/admin.html`：增加 AtomGit sidecar 预设和多连接/多模型选择器；保留现有单连接添加、编辑、发现、探测和排序流程。
- 修改 `tests/test_admin_api.py`：覆盖 loopback 校验、sidecar 预设页面标记、临时模型发现和批量连接接口。
- 修改 `tests/test_discovery_api.py`：覆盖多连接保存、重复保存、部分失败和凭据隔离。
- 修改 `tests/test_catalog.py` 或新增 `tests/test_catalog_ui_contract.py`：验证目录候选不会按 Provider 名称丢弃不同 Base URL，并验证前端契约标记。
- 修改 `docs/specs/2026-09-10-multi-connection-model-selection-design.md`：记录实际接口字段和 sidecar 使用约束（若实现字段与设计中的建议字段不同，必须同步修改）。
- 修改 `README.md`：补充 AtomGit CodingPlan sidecar 的本地配置和安全边界，不写入 OAuth Token、`auth.toml` 示例内容或第三方绕过方法。

## 任务 1：loopback Base URL 校验与 AtomGit sidecar 连接预设

**涉及文件：**

- 修改：`freellm_gateway/api.py`
- 修改：`freellm_gateway/templates/admin.html`
- 测试：`tests/test_admin_api.py`

- [ ] **步骤 1：编写失败测试**

在 `tests/test_admin_api.py` 增加以下行为断言：

```python
def test_admin_provider_accepts_loopback_http_but_rejects_public_http(tmp_path):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    app = create_app(repository=repository, secrets=BulkSecrets(), api_token="api", admin_token="admin")
    client = TestClient(app)
    headers = {"Authorization": "Bearer admin"}
    base = {
        "id": "atomgit-codingplan-local",
        "name": "AtomGit CodingPlan · 本机 sidecar",
        "protocol": "openai",
        "official_url": "https://ai.atomgit.com",
    }

    accepted = client.post(
        "/api/admin/providers", headers=headers,
        json={**base, "base_url": "http://127.0.0.1:8080/v1"},
    )
    rejected = client.post(
        "/api/admin/providers", headers=headers,
        json={**base, "id": "public-http", "base_url": "http://example.test/v1"},
    )

    assert accepted.status_code == 201
    assert rejected.status_code == 422
    assert "https URL" in rejected.json()["detail"]


def test_admin_page_exposes_atomgit_sidecar_preset_and_multi_connection_contract(tmp_path):
    response = TestClient(create_app(repository=Repository(Database(tmp_path / "gateway.sqlite3")), api_token="api", admin_token="admin")).get(
        "/admin", headers={"Authorization": "Bearer admin"}
    )
    assert response.status_code == 200
    assert "AtomGit CodingPlan" in response.text
    assert "http://127.0.0.1:8080/v1" in response.text
    assert "/api/admin/routes/bulk-connections" in response.text
```

- [ ] **步骤 2：运行测试确认失败**

运行：

```text
pytest tests/test_admin_api.py::test_admin_provider_accepts_loopback_http_but_rejects_public_http tests/test_admin_api.py::test_admin_page_exposes_atomgit_sidecar_preset_and_multi_connection_contract -q
```

预期：失败；当前 `_require_public_url` 拒绝 `http://127.0.0.1`，页面也没有 sidecar 和新批量接口标记。

- [ ] **步骤 3：最小实现**

在 `freellm_gateway/api.py` 增加 `_require_provider_base_url`：

```python
def _require_provider_base_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.username or parsed.password or not parsed.netloc:
        raise HTTPException(status_code=422, detail="base_url must be a URL without credentials")
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        return
    raise HTTPException(status_code=422, detail="base_url must be an https URL or loopback http URL")
```

仅将 Provider 的 `base_url` 校验调用替换为 `_require_provider_base_url`；`official_url`、route `endpoint`、`public_url` 和 `public_docs_url` 继续调用 `_require_public_url`。对 URL 去掉尾部 `/` 后保留协议、主机、端口和路径，用于后续精确匹配。管理台 Provider 表单增加 `AtomGit CodingPlan（本机 sidecar）` 预设按钮/选项，填入：

```text
id: atomgit-codingplan-local
name: AtomGit CodingPlan · 本机 sidecar
protocol: openai
base_url: http://127.0.0.1:8080/v1
official_url: https://ai.atomgit.com
```

预设旁显示“仅本机使用；OAuth/signing 由 sidecar 处理”，并将 sidecar API Key 继续放入现有密码输入框。页面源码只出现 loopback 地址和说明，不出现 `auth.toml` 内容、OAuth Token、keyring URI 或用户 Key。

- [ ] **步骤 4：运行测试确认通过**

运行：

```text
pytest tests/test_admin_api.py::test_admin_provider_accepts_loopback_http_but_rejects_public_http tests/test_admin_api.py::test_admin_page_exposes_atomgit_sidecar_preset_and_multi_connection_contract -q
```

预期：2 个测试通过；随后运行 `pytest tests/test_admin_api.py -q`，既有 HTTPS 校验测试全部通过。

## 任务 2：保留目录中的全部连接候选并建立稳定身份

**涉及文件：**

- 修改：`freellm_gateway/templates/admin.html`
- 修改：`tests/test_admin_api.py`
- 测试：`tests/test_catalog.py`

- [ ] **步骤 1：编写失败测试**

增加一个静态管理台契约测试，断言源码包含按 Base URL 归一化的候选键和精确匹配逻辑，而不是仅按名称 `Map` 去重：

```python
def test_admin_catalog_contract_keeps_same_provider_on_multiple_base_urls(tmp_path):
    app = create_app(repository=Repository(Database(tmp_path / "gateway.sqlite3")), api_token="api", admin_token="admin")
    response = TestClient(app).get("/admin", headers={"Authorization": "Bearer admin"})
    assert "normalizeConnectionKey" in response.text
    assert "provider + base_url" in response.text
    assert "catalogProviderFor(offer)" in response.text
```

在测试运行前确认当前源码没有 `normalizeConnectionKey`，以确保是针对新行为的 RED。

- [ ] **步骤 2：运行测试确认失败**

运行：

```text
pytest tests/test_admin_api.py::test_admin_catalog_contract_keeps_same_provider_on_multiple_base_urls -q
```

预期：失败，原因是页面尚未声明连接归一化键。

- [ ] **步骤 3：最小实现**

在管理台脚本加入以下纯函数，并让 `buildCatalogProviders` 使用它：

```javascript
const normalizeBaseUrl = value => String(value || '').trim().replace(/\/+$/, '').toLowerCase();
const normalizeConnectionKey = (name, baseUrl) => `${String(name || '').trim().toLowerCase()}|${normalizeBaseUrl(baseUrl)}`;
const providerIdForConnection = (name, baseUrl) => {
  const text = normalizeConnectionKey(name, baseUrl);
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) hash = Math.imul(hash ^ text.charCodeAt(index), 16777619);
  return `${providerIdFor(name)}-${(hash >>> 0).toString(16)}`;
};
```

候选对象保存 `connection_key`、`region`/`line`（有目录字段才显示）和 `offer_ids`；去重键改为 `normalizeConnectionKey(name, providerBaseUrl(endpoint))`。本地 Provider 与目录候选的合并改为按 `normalizeConnectionKey(provider.name, provider.base_url)` 精确匹配，展示同名不同 URL 的所有选项；`catalogProviderFor` 先按 offer 的 provider + endpoint 精确匹配，找不到时才按名称给出无歧义的单一回退。Provider `<option>` 的 value 使用连接稳定 ID，label 显示名称、Base URL 和“目录/已配置”状态，避免两个同名选项不可区分。

目录 endpoint 若为本机 `http`，只作为无效远程目录候选而跳过；sidecar 只能通过管理台预设或 Provider 表单加入，不能由公网目录自动导入。

- [ ] **步骤 4：运行测试确认通过**

运行：

```text
pytest tests/test_admin_api.py::test_admin_catalog_contract_keeps_same_provider_on_multiple_base_urls tests/test_admin_api.py -q
```

预期：新增测试和既有管理台测试全部通过，源码中不存在按 `providerIdFor(name)` 直接丢弃同名不同 URL 的逻辑。

## 任务 3：为未保存候选提供临时模型验证接口

**涉及文件：**

- 修改：`freellm_gateway/api.py`
- 修改：`freellm_gateway/templates/admin.html`
- 测试：`tests/test_admin_api.py`

- [ ] **步骤 1：编写失败测试**

增加 monkeypatch adapter 的测试，验证 Provider 尚未保存时也能用一次性凭据获取模型，且凭据不出现在响应：

```python
def test_admin_can_validate_unsaved_connection_and_list_models(tmp_path, monkeypatch):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    app = create_app(repository=repository, api_token="api", admin_token="admin")
    monkeypatch.setattr("freellm_gateway.api.OpenAICompatibleAdapter", OneTimeModelsAdapter, raising=False)
    response = TestClient(app).post(
        "/api/admin/connection/models",
        headers={"Authorization": "Bearer admin"},
        json={
            "provider": {
                "id": "candidate", "name": "Candidate", "protocol": "openai",
                "base_url": "https://candidate.example/v1", "official_url": "https://candidate.example",
            },
            "credential": "temporary-key",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"data": ["model-a", "model-b"]}
    assert "temporary-key" not in response.text
    assert OneTimeModelsAdapter.instances[-1].closed is True
```

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/test_admin_api.py::test_admin_can_validate_unsaved_connection_and_list_models -q`。

预期：404，因为新接口尚不存在。

- [ ] **步骤 3：最小实现**

新增 `POST /api/admin/connection/models`。复用 `_provider_from_payload`（其中 Base URL 改用任务 1 的 Provider 校验），只在内存构造 OpenAI/Anthropic adapter，调用 `list_models()` 后在 `finally` 中 `aclose()`；不写 Repository、不写 keyring、不把 credential 放进异常 detail。错误统一转为已有 `ProviderError.kind` 和 status code。管理台对每个已选候选调用这个接口，把返回模型列表存入候选自身的 `models`、`selected_models` 和 `status/error` 字段，互不共享 DOM 选择状态。

- [ ] **步骤 4：运行测试确认通过**

运行：

```text
pytest tests/test_admin_api.py::test_admin_can_validate_unsaved_connection_and_list_models tests/test_admin_api.py -q
```

预期：新增接口测试通过，既有已保存 Provider 模型发现测试仍通过。

## 任务 4：实现逐连接批量保存接口和部分失败结果

**涉及文件：**

- 修改：`freellm_gateway/api.py`
- 修改：`tests/test_discovery_api.py`

- [ ] **步骤 1：编写失败测试**

增加以下接口测试：

```python
def test_admin_bulk_connections_saves_each_connection_with_own_credential(tmp_path):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    secrets = BulkSecrets()
    app = create_app(ModelGateway([], {}), repository=repository, secrets=secrets, api_token="api", admin_token="admin")
    response = TestClient(app).post(
        "/api/admin/routes/bulk-connections",
        headers={"Authorization": "Bearer admin"},
        json={"connections": [
            {"provider": {"id": "p-us", "name": "Same", "protocol": "openai", "base_url": "https://us.example/v1", "official_url": "https://same.example"}, "credential": "us-key", "models": [{"remote_model": "us-model"}]},
            {"provider": {"id": "p-eu", "name": "Same", "protocol": "openai", "base_url": "https://eu.example/v1", "official_url": "https://same.example"}, "credential": "eu-key", "models": [{"remote_model": "eu-model", "enabled": False}]},
        ]}
    )
    assert response.status_code == 200
    assert len(response.json()["data"]["created"]) == 2
    assert response.json()["data"]["skipped"] == []
    assert response.json()["data"]["failed"] == []
    assert {(route.provider_id, route.remote_model) for route in repository.list_routes()} == {("p-us", "us-model"), ("p-eu", "eu-model")}
    assert [value for _, value in secrets.saved] == ["us-key", "eu-key"]
    assert "us-key" not in response.text and "eu-key" not in response.text


def test_admin_bulk_connections_is_idempotent_and_reports_one_connection_failure(tmp_path, monkeypatch):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    secrets = BulkSecrets()
    app = create_app(ModelGateway([], {}), repository=repository, secrets=secrets, api_token="api", admin_token="admin")
    payload = {"connections": [
        {"provider": {"id": "good", "name": "Good", "protocol": "openai", "base_url": "https://good.example/v1", "official_url": "https://good.example"}, "credential": "good-key", "models": [{"remote_model": "model"}]},
        {"provider": {"id": "bad", "name": "Bad", "protocol": "openai", "base_url": "http://bad.example/v1", "official_url": "https://bad.example"}, "credential": "bad-key", "models": [{"remote_model": "model"}]},
    ]}
    first = TestClient(app).post("/api/admin/routes/bulk-connections", headers={"Authorization": "Bearer admin"}, json=payload)
    second = TestClient(app).post("/api/admin/routes/bulk-connections", headers={"Authorization": "Bearer admin"}, json={"connections": [payload["connections"][0]]})
    assert first.status_code == 200
    assert first.json()["data"]["failed"][0]["error_type"] == "validation_error"
    assert second.json()["data"]["created"] == []
    assert second.json()["data"]["skipped"] == [{"provider_id": "good", "remote_model": "model"}]
```

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/test_discovery_api.py::test_admin_bulk_connections_saves_each_connection_with_own_credential tests/test_discovery_api.py::test_admin_bulk_connections_is_idempotent_and_reports_one_connection_failure -q`。

预期：404，且数据库没有新路由。

- [ ] **步骤 3：最小实现**

新增 `POST /api/admin/routes/bulk-connections`，payload 结构固定为：

```json
{
  "connections": [
    {
      "provider": {"id": "...", "name": "...", "protocol": "openai|anthropic", "base_url": "...", "official_url": "..."},
      "credential": "...",
      "models": [{"remote_model": "...", "enabled": true, "display_name": null}],
      "public_url": null,
      "public_docs_url": null,
      "free_summary": null,
      "capabilities": ["chat"]
    }
  ]
}
```

要求如下：

1. `connections` 必须是非空列表；每个连接的 provider、models、model 字段复用单连接校验；public URL 仍只允许 HTTPS。
2. Provider 先按 `normalize_base_url` 精确查找现有记录：同一规范化 Base URL 且协议一致时复用已有 `provider.id`；找不到时使用 payload 的稳定 id。若 payload id 已存在但指向不同 Base URL，返回当前连接的 `failed`，`error_type: "provider_identity_conflict"`，不覆盖旧 Provider。
3. 每个连接独立处理，连接级异常捕获为 `failed: [{provider_id, base_url, error_type, message}]`；禁止把 credential、keyring 引用或完整 payload 写入响应/日志。一个连接失败不影响其他连接。
4. 已存在路由按 `(provider_id, remote_model)` 跳过，追加 `skipped: [{provider_id, remote_model}]`；新路由使用 `_bulk_route_id`，凭据只通过 `app.state.secrets.save(route.id, credential)` 写入 keyring。没有 credential 时允许保存无凭据路由；如果提供 credential 但 secrets 未配置，则仅当前连接失败为 `secret_storage_unavailable`。
5. 每个新模型创建后立即加入 gateway/repository，最后统一 `_resequence_routes`；返回 `created` 使用 `route_json`，该 JSON 不包含 credential_ref。单连接 `/api/admin/routes/bulk` 逻辑和返回格式保持不变。

- [ ] **步骤 4：运行测试确认通过**

运行：

```text
pytest tests/test_discovery_api.py::test_admin_bulk_connections_saves_each_connection_with_own_credential tests/test_discovery_api.py::test_admin_bulk_connections_is_idempotent_and_reports_one_connection_failure tests/test_discovery_api.py -q
```

预期：新增测试和现有发现/批量导入测试全部通过。

## 任务 5：管理台多连接、多模型选择器

**涉及文件：**

- 修改：`freellm_gateway/templates/admin.html`
- 修改：`tests/test_admin_api.py`

- [ ] **步骤 1：编写失败测试**

增加页面契约断言：

```python
def test_admin_page_exposes_connection_and_model_selection_controls(tmp_path):
    app = create_app(repository=Repository(Database(tmp_path / "gateway.sqlite3")), api_token="api", admin_token="admin")
    response = TestClient(app).get("/admin", headers={"Authorization": "Bearer admin"})
    assert response.status_code == 200
    for marker in ("connection-candidates", "selected_models", "validate-connection", "bulk-connections"):
        assert marker in response.text
    assert "credential_ref" not in response.text
```

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/test_admin_api.py::test_admin_page_exposes_connection_and_model_selection_controls -q`。

预期：失败，因为当前弹窗只有单个 Provider、单个 credential 和全局模型列表。

- [ ] **步骤 3：最小实现**

将现有添加模型弹窗扩展为两层状态但保留编辑路由分支：

- 第一层 `#connection-candidates` 列出本地 Provider 与目录候选，每项含 checkbox、名称、Base URL、区域/线路、注册/文档链接和 `configured` 状态；初始目录模型只作为该候选的 `suggested_models`。
- 第二层为每个勾选连接渲染独立卡片，包含 credential password 输入、`data-action="validate-connection"` 按钮、连接错误状态、模型搜索框、全选/全不选和 `data-connection-model` checkbox。模型列表成功后默认全选，并优先勾选目录建议；失败卡片保留且可单独重试。
- 组装请求时从 DOM 逐卡片读取 credential 和选中模型，提交 `/api/admin/routes/bulk-connections`；提交前在前端阻止没有模型的连接并显示该连接错误，其他连接仍可保存。保存结果按 `created/skipped/failed` 展示；成功后清空 password DOM 并关闭弹窗，再刷新路由和 Provider。
- 单连接手工流程仍可从当前 Provider 下拉框提交 `/api/admin/routes` 或旧 `/api/admin/routes/bulk`；编辑模式继续使用 `/api/admin/routes/{id}`。不得把凭据写入 `localStorage`、`state` 的持久化字段、目录数据或任何 `console` 输出。
- AtomGit 预设选中后直接显示 `http://127.0.0.1:8080/v1`，验证失败提示“启动 sidecar、检查地址或 sidecar API Key”，不影响其他连接卡片。

- [ ] **步骤 4：运行测试确认通过**

运行：

```text
pytest tests/test_admin_api.py -q
```

预期：管理台新增契约和既有页面/校验测试全部通过；人工打开 `/admin` 验收两条同名不同 Base URL 能同时勾选，模型和错误状态按连接隔离。

## 任务 6：文档、安全回归与最终验证

**涉及文件：**

- 修改：`README.md`
- 修改：`docs/specs/2026-09-10-multi-connection-model-selection-design.md`
- 测试：`tests/test_admin_api.py`、`tests/test_discovery_api.py`、`tests/test_openai_adapter.py`、`tests/test_failover.py`、`tests/test_persistence_api.py`

- [ ] **步骤 1：编写失败测试**

在管理 API 测试中补充 URL credential 和公开 HTTP 回归断言，并补充响应泄露断言：

```python
def test_admin_rejects_credentials_in_loopback_base_url(tmp_path):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    app = create_app(repository=repository, api_token="api", admin_token="admin")
    response = TestClient(app).post(
        "/api/admin/providers",
        headers={"Authorization": "Bearer admin"},
        json={"id": "x", "name": "X", "protocol": "openai", "base_url": "http://user:pass@127.0.0.1:8080/v1", "official_url": "https://example.test"},
    )
    assert response.status_code == 422
    assert "pass" not in response.text
```

- [ ] **步骤 2：运行测试确认失败**

运行：`pytest tests/test_admin_api.py::test_admin_rejects_credentials_in_loopback_base_url -q`。

预期：若任务 1 的实现未覆盖 URL 用户名/密码，测试失败；修复前不得进入最终回归。

- [ ] **步骤 3：最小实现与文档**

确认所有 Provider 创建入口（单连接创建、旧 bulk、新 bulk-connections）均调用同一 `_require_provider_base_url`；所有公开 URL 入口仍拒绝 loopback HTTP、用户名和密码。README 新增本地 sidecar 示例：先在 sidecar 自己完成 AtomGit OAuth/CodingPlan 登录，再在 FreeLLM 管理台选择预设、填写 sidecar API Key；明确仅允许本人本机使用，不支持账号轮换、额度规避或公网共享。设计文档补充新接口字段、连接复用规则和错误类型。

- [ ] **步骤 4：运行全量验证**

依次运行：

```text
pytest tests/test_admin_api.py tests/test_discovery_api.py tests/test_catalog.py tests/test_openai_adapter.py tests/test_failover.py tests/test_persistence_api.py -q
pytest -q
```

预期：两条命令均通过；输出中没有失败、凭据值不会出现在测试响应；手工检查 `git diff --check` 无空白错误，并确认未修改/删除用户已有的无关改动。

- [ ] **步骤 5：提交（仅在用户要求提交时执行）**

```text
git diff --check
git status --short
```

如果用户要求提交，再只暂存本计划涉及的文件并使用：

```text
git add freellm_gateway/api.py freellm_gateway/templates/admin.html tests/test_admin_api.py tests/test_discovery_api.py tests/test_catalog.py README.md docs/specs/2026-09-10-multi-connection-model-selection-design.md docs/specs/plans/2026-09-10-multi-connection-model-selection.md
git commit -m "feat: support multi-connection model selection"
```

默认不创建提交，避免覆盖或捆绑工作区中用户已有的变更。
