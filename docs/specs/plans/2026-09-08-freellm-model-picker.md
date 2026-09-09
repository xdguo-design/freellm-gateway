# FreeLLM 模型选择与 Provider Key 实施计划

> **给代理执行者：** 推荐按 TDD 的 RED-GREEN-REFACTOR 节奏执行；任务使用 `- [ ]` 勾选跟踪。

**目标：** 在控制台添加模型窗口内展示 FreeLLM 模型库、填写 API Key、注册 Provider，并通过按钮读取 Provider 全部模型后选择保存。

**非目标：** 不自动抓取或代填第三方注册信息；不自动把 Provider 的全部远程模型写入模型池；不把 API Key 放入响应、日志或目录导出。

**架构要点：** FreeLLM 目录继续通过受保护的管理接口读取，只保留模型/API 条目。新增的模型读取接口使用本次请求中的 Key 创建临时 OpenAI 兼容适配器，调用 `/models` 后立即关闭，不持久化 Key。保存模型时沿用现有路由级密钥安全存储；注册按钮只打开目录或 Provider 官方注册地址。

**技术栈/运行方式：** Python 3.10+、FastAPI、httpx、静态 HTML/JavaScript、pytest；验证命令为 `python -m pytest -q`、`python -m compileall freellm_gateway`。

**关联设计文档：** `docs/specs/2026-09-08-freellm-gateway-design.md`

---

## 文件变更清单

- 修改：
  - `freellm_gateway/api.py`：增加受保护的 Provider 模型读取接口，并验证 Key/Provider 输入。
  - `freellm_gateway/templates/admin.html`：在添加模型窗口加入明确的 API Key、获取模型、注册入口和模型选择交互。
- 测试：
  - `tests/test_discovery_api.py`：覆盖使用临时 Key 获取远程模型、错误响应和 Key 不回显。
  - `tests/test_admin_api.py`：覆盖管理页面包含新交互控件。

## 任务列表

### 任务 1：Provider 模型读取接口

**涉及文件：** `freellm_gateway/api.py`、`tests/test_discovery_api.py`

- [x] **步骤 1：编写失败测试**

```python
def test_admin_can_fetch_provider_models_with_one_time_key(tmp_path, monkeypatch):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    repository.initialize()
    repository.save_provider(Provider("p", "Provider", "openai", "https://api.example/v1", "https://provider.example"))
    app = create_app(ModelGateway([], {}), repository=repository, api_token="api", admin_token="admin")
    monkeypatch.setattr("freellm_gateway.api.OpenAICompatibleAdapter", OneTimeModelsAdapter)
    client = TestClient(app)
    response = client.post(
        "/api/admin/providers/p/models",
        headers={"Authorization": "Bearer admin"},
        json={"credential": "temporary-key"},
    )
    assert response.status_code == 200
    assert response.json()["data"] == ["model-a", "model-b"]
    assert "temporary-key" not in response.text
```

- [x] **步骤 2：运行并确认失败**

运行：`python -m pytest tests/test_discovery_api.py::test_admin_can_fetch_provider_models_with_one_time_key -q`

预期：失败，接口当前返回 404。

- [x] **步骤 3：最小实现**

在 `api.py` 增加 `POST /api/admin/providers/{provider_id}/models`：校验管理员令牌、Provider 和非空 `credential`，根据 Provider 的 OpenAI 兼容地址创建临时 `OpenAICompatibleAdapter`，调用 `list_models()`，在 `finally` 中关闭适配器；只返回模型 ID 列表。

- [x] **步骤 4：运行并确认通过**

运行：`python -m pytest tests/test_discovery_api.py -q`

预期：全部通过，并覆盖 Provider 不存在、缺少 Key、上游失败时不回显 Key。

### 任务 2：添加模型窗口交互

**涉及文件：** `freellm_gateway/templates/admin.html`、`tests/test_admin_api.py`

- [x] **步骤 1：编写失败测试**

```python
def test_admin_page_exposes_model_fetch_key_and_registration_controls():
    response = client.get("/admin")
    assert 'name="credential"' in response.text
    assert 'data-action="fetch-models"' in response.text
    assert 'data-action="register-provider"' in response.text
```

- [x] **步骤 2：运行并确认失败**

运行：`python -m pytest tests/test_admin_api.py::test_admin_page_exposes_model_fetch_key_and_registration_controls -q`

预期：失败，当前页面没有获取模型和注册 Provider 控件。

- [x] **步骤 3：最小实现**

在模型弹窗中将“凭据”改为“API Key / 凭据”，增加“获取所有模型”按钮、可编辑模型下拉列表和“注册并获取 Key”链接；按钮调用新接口，选择结果回填 `remote_model`，注册链接使用当前目录条目的 `register`，无目录条目时回退到 Provider `official_url`。无 Provider 时展示前往设置的提示，避免空下拉框造成误操作。

- [x] **步骤 4：运行并确认通过**

运行：`python -m pytest tests/test_admin_api.py -q`

预期：页面控件断言和既有管理页面测试全部通过。

### 任务 3：FreeLLM 模型库与整体验证

**涉及文件：** `freellm_gateway/templates/admin.html`、现有 FreeLLM 目录接口及测试

- [x] **步骤 1：补充模型库行为断言**

断言目录接口只返回模型/API 条目；页面保留搜索、注册链接和“选择并填写”入口，已存在的模型显示已配置状态。

- [x] **步骤 2：运行完整测试**

运行：`python -m pytest -q`

预期：全套测试通过。

- [x] **步骤 3：静态与安全验证**

运行：`python -m compileall freellm_gateway`；`rg -n "temporary-key|API_KEY|Bearer " freellm_gateway tests --glob '!*.pyc'`

预期：编译成功；源码和测试中不存在真实密钥，Key 只出现在测试输入或受保护请求体中，页面不会渲染 Key。

- [ ] **步骤 4：提交**

运行：`git status -sb`、`git diff --check`；提交信息：`feat: add provider model picker to admin console`。

## 质量门控

- [ ] 每个新接口行为先有正确原因导致的失败测试，再写生产实现。
- [ ] Key 不写入响应、日志、目录导出或页面文本。
- [ ] 现有未提交改动保持不被覆盖。
- [ ] 完整测试、编译检查和 diff 空白检查通过。
