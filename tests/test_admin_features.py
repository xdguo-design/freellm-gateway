import json

from fastapi.testclient import TestClient

from freellm_gateway.api import create_app
from freellm_gateway.db import Database
from freellm_gateway.models import ModelRoute, Provider
from freellm_gateway.repository import Repository
from freellm_gateway.service import ModelGateway


class ProbeAdapter:
    def __init__(self, response=None):
        self.response = response or {"id": "probe", "choices": [{"message": {"content": "128464"}}]}
        self.calls = []

    async def complete(self, payload):
        self.calls.append(payload)
        return self.response


class FakeSecrets:
    def __init__(self):
        self.values = {}

    def save(self, name, value):
        reference = f"memory://{name}"
        self.values[reference] = value
        return reference

    def get(self, reference):
        return self.values.get(reference)


def make_client(routes=None, adapters=None, **kwargs):
    routes = routes or [ModelRoute(id="first", provider_id="p", remote_model="m1", priority=1)]
    gateway = ModelGateway(routes, adapters or {})
    return TestClient(create_app(gateway=gateway, api_token="api", admin_token="admin", **kwargs)), gateway


def test_public_root_describes_openai_compatible_api():
    client, _ = make_client()

    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["api_base"] == "/v1"
    assert response.json()["endpoints"]["chat_completions"] == "/v1/chat/completions"


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


def test_bulk_route_creation_preserves_explicit_catalog_status(tmp_path):
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
        "id": "catalog-provider",
        "name": "Catalog Provider",
        "protocol": "openai",
        "base_url": "https://catalog.example/v1",
        "official_url": "https://catalog.example",
    }

    published = client.post(
        "/api/admin/routes/bulk",
        headers=headers,
        json={
            "provider": provider,
            "models": [{"remote_model": "published-model"}],
            "catalog_status": "published",
        },
    )
    draft = client.post(
        "/api/admin/routes/bulk",
        headers=headers,
        json={
            "provider": provider,
            "models": [{"remote_model": "draft-model"}],
        },
    )

    assert published.status_code == 200
    assert draft.status_code == 200
    routes = {route.remote_model: route for route in repository.list_routes()}
    assert routes["published-model"].catalog_status == "published"
    assert routes["draft-model"].catalog_status == "draft"


def test_admin_overview_and_health_are_available_with_admin_token():
    client, _ = make_client()
    headers = {"Authorization": "Bearer admin"}

    overview = client.get("/api/admin/overview", headers=headers)
    health = client.get("/api/admin/health", headers=headers)

    assert overview.status_code == 200
    assert overview.json()["data"]["configured"] == 1
    assert overview.json()["data"]["api_token"] == "api"
    assert health.status_code == 200
    assert health.json()["data"][0]["id"] == "first"


def test_admin_persists_normalized_priorities_when_loading_repository(tmp_path):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    repository.initialize()
    repository.save_provider(Provider("p", "Provider", "openai", "https://api.example/v1", "https://example.com"))
    routes = [
        ModelRoute(id="first", provider_id="p", remote_model="m1", priority=1),
        ModelRoute(id="second", provider_id="p", remote_model="m2", priority=3),
        ModelRoute(id="third", provider_id="p", remote_model="m3", priority=3),
    ]
    for route in routes:
        repository.save_route(route)

    create_app(ModelGateway(routes, {}), repository=repository, api_token="api", admin_token="admin")

    assert [(route.id, route.priority) for route in repository.list_routes()] == [
        ("first", 1),
        ("second", 2),
        ("third", 3),
    ]


def test_admin_can_update_probe_and_delete_a_route():
    adapter = ProbeAdapter()
    client, gateway = make_client(adapters={"first": adapter})
    headers = {"Authorization": "Bearer admin"}

    updated = client.patch(
        "/api/admin/routes/first",
        headers=headers,
        json={"display_name": "Updated", "enabled": False, "capabilities": ["chat", "vision"]},
    )
    assert updated.status_code == 200
    assert gateway.route("first").display_name == "Updated"
    assert gateway.route("first").enabled is False

    gateway.routes[0] = gateway.route("first").__class__(**{**gateway.route("first").__dict__, "enabled": True})
    probed = client.post("/api/admin/routes/first/probe", headers=headers)
    assert probed.status_code == 200
    assert probed.json()["health"] == "healthy"
    assert adapter.calls[0]["model"] == "m1"

    deleted = client.delete("/api/admin/routes/first", headers=headers)
    assert deleted.status_code == 204
    assert gateway.routes == []


def test_admin_can_export_catalog_to_configured_output(tmp_path):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    repository.initialize()
    repository.save_provider(Provider("p", "Provider", "openai", "https://api.example/v1", "https://example.com"))
    route = ModelRoute(
        id="first", provider_id="p", remote_model="m1", priority=1,
        public_url="https://example.com/register", catalog_status="published",
    )
    repository.save_route(route)
    output = tmp_path / "catalog-export.json"
    client, _ = make_client(routes=[route], repository=repository, secrets=None, catalog_output=output)

    response = client.post("/api/admin/catalog/export", headers={"Authorization": "Bearer admin"})

    assert response.status_code == 200
    assert output.exists()
    assert response.json()["data"]["published"][0]["model"] == "m1"


def test_admin_can_sync_export_to_configured_site_repo(tmp_path):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    repository.initialize()
    repository.save_provider(Provider("p", "Provider", "openai", "https://api.example/v1", "https://example.com"))
    route = ModelRoute(
        id="first", provider_id="p", remote_model="m1", priority=1,
        public_url="https://example.com/register", catalog_status="published",
    )
    repository.save_route(route)
    site_repo = tmp_path / "site"
    (site_repo / "data").mkdir(parents=True)
    (site_repo / "data" / "offers.json").write_text("[]\n", encoding="utf-8")
    client, _ = make_client(routes=[route], repository=repository, site_repo=site_repo)

    response = client.post("/api/admin/catalog/sync", headers={"Authorization": "Bearer admin"})

    assert response.status_code == 200
    assert json.loads((site_repo / "data" / "offers.json").read_text(encoding="utf-8"))[0]["id"] == "first"


def test_admin_can_read_the_freellm_discovery_catalog(monkeypatch):
    client, _ = make_client(catalog_source="https://freellm.top/data/offers.json")

    async def fake_fetch(source):
        return [{"id": "groq-free", "productType": "api", "name": "Groq free plan"}]

    monkeypatch.setattr("freellm_gateway.api.fetch_public_catalog", fake_fetch)
    response = client.get(
        "/api/admin/catalog/source?scope=models",
        headers={"Authorization": "Bearer admin"},
    )

    assert response.status_code == 200
    assert response.json()["data"][0]["id"] == "groq-free"


def test_admin_catalog_marks_exact_enabled_disabled_and_unmatched_pool_status(tmp_path, monkeypatch):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    repository.initialize()
    repository.save_provider(Provider("groq", "Groq", "openai", "https://api.groq.com/v1", "https://groq.com"))
    routes = [
        ModelRoute(id="groq-enabled", provider_id="groq", remote_model="llama-3", priority=1),
        ModelRoute(id="groq-disabled", provider_id="groq", remote_model="qwen-2", priority=2, enabled=False),
    ]
    for route in routes:
        repository.save_route(route)
    client, _ = make_client(routes=routes, repository=repository, catalog_source="https://freellm.top/data/offers.json")

    async def fake_fetch(source):
        return [
            {"id": "llama-offer", "provider": "Groq", "model": "llama-3", "productType": "api"},
            {"id": "qwen-offer", "provider": "Groq", "model": "qwen-2", "productType": "api"},
            {"id": "other-offer", "provider": "Other", "model": "other", "productType": "api"},
        ]

    monkeypatch.setattr("freellm_gateway.api.fetch_public_catalog", fake_fetch)
    response = client.get("/api/admin/catalog/source?scope=models", headers={"Authorization": "Bearer admin"})

    assert response.status_code == 200
    statuses = {item["id"]: item["pool_status"] for item in response.json()["data"]}
    assert statuses["llama-offer"] == {
        "state": "enabled", "exact": True, "route_id": "groq-enabled", "enabled_count": 1, "disabled_count": 0,
    }
    assert statuses["qwen-offer"]["state"] == "disabled"
    assert statuses["qwen-offer"]["exact"] is True
    assert statuses["other-offer"] == {
        "state": "not_added", "exact": False, "route_id": None, "enabled_count": 0, "disabled_count": 0,
    }
    assert "credential_ref" not in response.text
    assert "keyring" not in response.text


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
