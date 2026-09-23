from fastapi.testclient import TestClient

from freellm_gateway.api import create_app
from freellm_gateway.db import Database
from freellm_gateway.models import ModelRoute
from freellm_gateway.repository import Repository
from freellm_gateway.service import ModelGateway


class BulkSecrets:
    def save(self, name, value):
        return f"memory://{name}"


class OneTimeModelsAdapter:
    instances = []

    def __init__(self, endpoint, api_key):
        self.endpoint = endpoint
        self.api_key = api_key
        self.closed = False
        type(self).instances.append(self)

    async def list_models(self):
        return ["model-a", "model-b"]

    async def aclose(self):
        self.closed = True


def test_admin_can_reorder_routes_and_non_admin_is_rejected():
    routes = [
        ModelRoute(id="first", provider_id="p", remote_model="m1", priority=1),
        ModelRoute(id="second", provider_id="p", remote_model="m2", priority=2),
    ]
    app = create_app(ModelGateway(routes, {}), api_token="api", admin_token="admin")
    client = TestClient(app)

    denied = client.post("/api/admin/routes/reorder", json={"ids": ["second", "first"]})
    response = client.post(
        "/api/admin/routes/reorder",
        headers={"Authorization": "Bearer admin"},
        json={"ids": ["second", "first"]},
    )

    assert denied.status_code == 401
    assert response.status_code == 200
    assert [route.id for route in app.state.gateway.routes] == ["second", "first"]
    assert [route.priority for route in app.state.gateway.routes] == [1, 2]


def test_admin_can_update_route_reasoning_effort():
    route = ModelRoute(id="route-1", provider_id="p", remote_model="openai/gpt-oss-120b", priority=1)
    app = create_app(ModelGateway([route], {}), api_token="api", admin_token="admin")
    client = TestClient(app)

    response = client.patch(
        "/api/admin/routes/route-1",
        headers={"Authorization": "Bearer admin"},
        json={"reasoning_effort": "medium"},
    )

    assert response.status_code == 200
    assert response.json()["reasoning_effort"] == "medium"
    assert app.state.gateway.route("route-1").reasoning_effort == "medium"

    invalid = client.patch(
        "/api/admin/routes/route-1",
        headers={"Authorization": "Bearer admin"},
        json={"reasoning_effort": ""},
    )
    assert invalid.status_code == 422


def test_admin_normalizes_duplicate_priorities_when_loading_routes():
    routes = [
        ModelRoute(id="first", provider_id="p", remote_model="m1", priority=1),
        ModelRoute(id="second", provider_id="p", remote_model="m2", priority=3),
        ModelRoute(id="third", provider_id="p", remote_model="m3", priority=3),
    ]

    app = create_app(ModelGateway(routes, {}), api_token="api", admin_token="admin")

    assert [(route.id, route.priority) for route in app.state.gateway.routes] == [
        ("first", 1),
        ("second", 2),
        ("third", 3),
    ]


def test_admin_update_moves_route_and_shifts_conflicting_priorities():
    routes = [
        ModelRoute(id="first", provider_id="p", remote_model="m1", priority=1),
        ModelRoute(id="second", provider_id="p", remote_model="m2", priority=2),
        ModelRoute(id="third", provider_id="p", remote_model="m3", priority=3),
    ]
    app = create_app(ModelGateway(routes, {}), api_token="api", admin_token="admin")
    client = TestClient(app)

    response = client.patch(
        "/api/admin/routes/third",
        headers={"Authorization": "Bearer admin"},
        json={"priority": 2},
    )

    assert response.status_code == 200
    assert [(route.id, route.priority) for route in app.state.gateway.routes] == [
        ("first", 1),
        ("third", 2),
        ("second", 3),
    ]


def test_admin_create_route_shifts_existing_priority():
    routes = [
        ModelRoute(id="first", provider_id="p", remote_model="m1", priority=1),
        ModelRoute(id="second", provider_id="p", remote_model="m2", priority=2),
    ]
    app = create_app(ModelGateway(routes, {}), api_token="api", admin_token="admin")
    client = TestClient(app)

    response = client.post(
        "/api/admin/routes",
        headers={"Authorization": "Bearer admin"},
        json={"id": "inserted", "provider_id": "p", "remote_model": "m3", "priority": 2},
    )

    assert response.status_code == 201
    assert [(route.id, route.priority) for route in app.state.gateway.routes] == [
        ("first", 1),
        ("inserted", 2),
        ("second", 3),
    ]


def test_admin_can_create_route_with_public_metadata():
    app = create_app(ModelGateway([], {}), api_token="api", admin_token="admin")
    client = TestClient(app)

    response = client.post(
        "/api/admin/routes",
        headers={"Authorization": "Bearer admin"},
        json={
            "id": "new-route", "provider_id": "p", "remote_model": "remote",
            "priority": 1, "public_url": "https://provider.example/register",
        },
    )

    assert response.status_code == 201
    assert response.json()["id"] == "new-route"
    assert app.state.gateway.routes[0].remote_model == "remote"


def test_admin_page_loads_before_admin_api_authentication():
    app = create_app(ModelGateway([], {}), api_token="api", admin_token="admin")
    client = TestClient(app)

    response = client.get("/admin/legacy")
    denied = client.get("/api/admin/routes")

    assert response.status_code == 200
    assert "Model Pool" in response.text
    assert 'id="auth-form"' not in response.text
    assert "Request Routing" in response.text
    assert 'data-action="probe"' in response.text
    assert denied.status_code == 401


def test_admin_api_allows_loopback_without_token_but_rejects_remote_clients():
    app = create_app(ModelGateway([], {}), api_token="api", admin_token="admin")
    local = TestClient(app, client=("127.0.0.1", 50000))
    remote = TestClient(app, client=("192.0.2.10", 50000))

    assert local.get("/api/admin/overview").status_code == 200
    assert remote.get("/api/admin/overview").status_code == 401


def test_admin_page_exposes_model_fetch_key_and_registration_controls():
    app = create_app(ModelGateway([], {}), api_token="api", admin_token="admin")
    response = TestClient(app).get("/admin/legacy")

    assert response.status_code == 200
    assert 'name="credential"' in response.text
    assert "API Key /" in response.text
    assert 'data-action="fetch-models"' in response.text
    assert 'data-action="register-provider"' in response.text
    assert 'id="route-public-link"' in response.text
    assert 'id="route-docs-link"' in response.text
    assert 'id="api-token"' in response.text
    assert 'data-action="copy-api-token"' in response.text
    assert 'id="default-model">auto</code>' in response.text
    assert '<input name="public_url" data-i18n-ph=' not in response.text
    assert '<input name="public_docs_url" data-i18n-ph=' not in response.text
    assert '.link-field { display:flex; align-items:baseline;' in response.text


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
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    app = create_app(repository=repository, api_token="api", admin_token="admin")
    response = TestClient(app).get("/admin/legacy", headers={"Authorization": "Bearer admin"})

    assert response.status_code == 200
    assert "AtomGit CodingPlan" in response.text
    assert "http://127.0.0.1:8080/v1" in response.text
    assert "/api/admin/routes/bulk-connections" in response.text


def test_admin_catalog_contract_keeps_same_provider_on_multiple_base_urls(tmp_path):
    app = create_app(repository=Repository(Database(tmp_path / "gateway.sqlite3")), api_token="api", admin_token="admin")
    response = TestClient(app).get("/admin/legacy", headers={"Authorization": "Bearer admin"})

    assert "normalizeConnectionKey" in response.text
    assert "provider + base_url" in response.text
    assert "catalogProviderFor(offer)" in response.text


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


def test_admin_page_exposes_connection_and_model_selection_controls(tmp_path):
    app = create_app(repository=Repository(Database(tmp_path / "gateway.sqlite3")), api_token="api", admin_token="admin")
    response = TestClient(app).get("/admin/legacy", headers={"Authorization": "Bearer admin"})

    assert response.status_code == 200
    for marker in ("connection-candidates", "selected_models", "validate-connection", "bulk-connections"):
        assert marker in response.text
    assert "credential_ref" not in response.text


def test_admin_rejects_credentials_in_loopback_base_url(tmp_path):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    app = create_app(repository=repository, api_token="api", admin_token="admin")
    response = TestClient(app).post(
        "/api/admin/providers",
        headers={"Authorization": "Bearer admin"},
        json={
            "id": "x", "name": "X", "protocol": "openai",
            "base_url": "http://user:pass@127.0.0.1:8080/v1",
            "official_url": "https://example.test",
        },
    )

    assert response.status_code == 422
    assert "pass" not in response.text


def test_admin_page_uses_distinct_color_class_for_disabled_status():
    app = create_app(ModelGateway([], {}), api_token="api", admin_token="admin")

    response = TestClient(app).get("/admin/legacy")

    assert ".disabled { color:" in response.text
    assert "routeStatusClass=(health,enabled)=>enabled?(health==='healthy'?'ok'" in response.text
    assert "routeStatusClass(route.health,route.enabled)" in response.text


def test_admin_catalog_registration_controls_use_stable_vertical_layout():
    response = TestClient(create_app(ModelGateway([], {}), api_token="api", admin_token="admin")).get("/admin/legacy")

    assert response.status_code == 200
    assert ".catalog-register { display:flex; flex-direction:column;" in response.text
    assert 'class="catalog-register"' in response.text


def test_admin_provider_grid_adapts_to_narrow_panels():
    app = create_app(ModelGateway([], {}), api_token="api", admin_token="admin")
    response = TestClient(app).get("/admin/legacy")

    assert response.status_code == 200
    assert ".provider-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr)); gap:12px; }" in response.text
    assert ".stats, .endpoint-grid, .form-grid { grid-template-columns:1fr 1fr; }" in response.text


def test_admin_page_exposes_bulk_model_controls():
    app = create_app(ModelGateway([], {}), api_token="api", admin_token="admin")
    response = TestClient(app).get("/admin/legacy")

    assert response.status_code == 200
    assert 'id="bulk-models"' in response.text
    assert 'data-action="select-all-models"' in response.text
    assert 'data-action="bulk-save-models"' in response.text
    assert "/api/admin/routes/bulk" in response.text


def test_admin_page_exposes_provider_protocol_selector():
    app = create_app(ModelGateway([], {}), api_token="api", admin_token="admin")

    response = TestClient(app).get("/admin/legacy")

    assert response.status_code == 200
    assert '<select name="protocol"' in response.text
    assert 'protocolChat' in response.text
    assert 'protocolGoogle' in response.text
    assert 'protocolAnthropic' in response.text
    assert 'https://generativelanguage.googleapis.com/v1beta' in response.text
    assert 'providerOptionLabel' in response.text
    assert 'protocolLabel(provider.protocol)' in response.text


def test_admin_page_exposes_provider_model_list_markup():
    response = TestClient(create_app(ModelGateway([], {}), api_token="api", admin_token="admin")).get("/admin/legacy")

    assert response.status_code == 200
    assert 'id="providers"' in response.text
    assert "provider-model-list" in response.text
    assert "noProviderModels" in response.text


def test_admin_page_matches_catalog_provider_by_name_for_every_offer():
    response = TestClient(create_app(ModelGateway([], {}), api_token="api", admin_token="admin")).get("/admin/legacy")

    assert "catalogProviderFor" in response.text
    assert "catalogProviderFor(offer)" in response.text


def test_admin_catalog_offer_without_endpoint_does_not_fall_back_to_another_provider():
    response = TestClient(create_app(ModelGateway([], {}), api_token="api", admin_token="admin")).get("/admin/legacy")

    assert "const offerProviderId=offer?(matched?.id||catalogMatch?.id||CUSTOM_PROVIDER_ID)" in response.text
    assert "custom_provider_name" in response.text
    assert "offerProviderId===CUSTOM_PROVIDER_ID" in response.text
    assert "if(!/^https?:\\/\\/[^\\s]+$/.test(baseUrl))return" in response.text


def test_admin_page_exposes_settings_runtime_details_and_copy_controls():
    response = TestClient(create_app(ModelGateway([], {}), api_token="api", admin_token="admin")).get("/admin/legacy")

    assert response.status_code == 200
    for marker in ("settings-chat", "settings-images", "settings-db", "settings-catalog", "settings-logs"):
        assert f'id="{marker}"' in response.text
    assert "copyText" in response.text
    assert 'data-action="copy-text"' in response.text
    assert 'id="settings-stats"' in response.text


def test_admin_page_exposes_manual_reasoning_effort_control():
    response = TestClient(create_app(ModelGateway([], {}), api_token="api", admin_token="admin")).get("/admin/legacy")

    assert response.status_code == 200
    assert "reasoning_effort" in response.text
    assert "ensureReasoningField" in response.text
    assert "formGrid.insertBefore(label,credentialLabel)" in response.text
    assert "fReasoningPh" in response.text
    assert "GPT-OSS: medium / high / low" in response.text


def test_admin_page_prefills_groq_gpt_oss_model():
    response = TestClient(create_app(ModelGateway([], {}), api_token="api", admin_token="admin")).get("/admin/legacy")

    assert response.status_code == 200
    assert "openai/gpt-oss-120b" in response.text
    assert "applyModelPreset" in response.text


def test_admin_page_combines_health_monitoring_into_model_pool():
    response = TestClient(create_app(ModelGateway([], {}), api_token="api", admin_token="admin")).get("/admin/legacy")

    assert 'data-view="health"' not in response.text
    assert 'id="view-health"' not in response.text
    models_section = response.text.split('id="view-models"', 1)[1].split('id="connection-log"', 1)[0]
    for marker in ("thModel", "thProvider", "thStatus", "thActions", "probe-all"):
        assert marker in models_section
    assert "thLastLatency" not in models_section
    assert "thFailures" not in models_section
    assert "thLastError" not in models_section


def test_admin_page_exposes_connection_log_panel_in_model_pool():
    response = TestClient(create_app(ModelGateway([], {}), api_token="api", admin_token="admin")).get("/admin/legacy")

    assert response.status_code == 200
    for marker in ("connection-log", "connection-log-rows", "connectionLogTitle", "loadConnections", "thConnectionRoute", "thConnectionResult"):
        assert marker in response.text


def test_admin_page_exposes_custom_provider_fields_in_add_model_form():
    response = TestClient(create_app(ModelGateway([], {}), api_token="api", admin_token="admin")).get("/admin/legacy")

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
    ):
        assert marker in response.text


def test_admin_page_uses_unsaved_connection_discovery_for_custom_provider():
    response = TestClient(create_app(ModelGateway([], {}), api_token="api", admin_token="admin")).get("/admin/legacy")

    assert response.status_code == 200
    assert "const custom=form.elements.provider_id.value===CUSTOM_PROVIDER_ID" in response.text
    assert "body:JSON.stringify({provider,credential})" in response.text


def test_admin_page_validates_custom_provider_before_discovery_or_save():
    response = TestClient(create_app(ModelGateway([], {}), api_token="api", admin_token="admin")).get("/admin/legacy")

    assert response.status_code == 200
    assert "customProviderValid" in response.text
    assert "customProviderRequired" in response.text



def test_admin_prefers_react_bundle_when_built(tmp_path, monkeypatch):
    dist = tmp_path / "admin"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><html><head><title>React Admin</title></head><body><div id='root'>react-shell</div></body></html>",
        encoding="utf-8",
    )
    (assets / "app.js").write_text("window.__react_admin__ = true;", encoding="utf-8")
    monkeypatch.setenv("FREELLM_GATEWAY_ADMIN_DIST", str(dist))

    client = TestClient(create_app(ModelGateway([], {}), api_token="api", admin_token="admin"))

    response = client.get("/admin")
    asset = client.get("/admin/assets/app.js")
    legacy = client.get("/admin/legacy")

    assert response.status_code == 200
    assert "react-shell" in response.text
    assert asset.status_code == 200
    assert "__react_admin__" in asset.text
    assert "Model Pool" in legacy.text
