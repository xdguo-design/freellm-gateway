import json

from fastapi.testclient import TestClient

from freellm_gateway.api import create_app
from freellm_gateway.db import Database
from freellm_gateway.models import ModelRoute, Provider
from freellm_gateway.repository import Repository
from freellm_gateway.service import ModelGateway


class ProbeAdapter:
    def __init__(self, response=None):
        self.response = response or {"id": "probe", "choices": []}
        self.calls = []

    async def complete(self, payload):
        self.calls.append(payload)
        return self.response


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


def test_admin_overview_and_health_are_available_with_admin_token():
    client, _ = make_client()
    headers = {"Authorization": "Bearer admin"}

    overview = client.get("/api/admin/overview", headers=headers)
    health = client.get("/api/admin/health", headers=headers)

    assert overview.status_code == 200
    assert overview.json()["data"]["configured"] == 1
    assert health.status_code == 200
    assert health.json()["data"][0]["id"] == "first"


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
