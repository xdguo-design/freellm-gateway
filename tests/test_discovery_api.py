import pytest
from fastapi.testclient import TestClient

from freellm_gateway.api import create_app
from freellm_gateway.db import Database
from freellm_gateway.models import ModelRoute, Provider
from freellm_gateway.repository import Repository
from freellm_gateway.service import ModelGateway


class FakeSecrets:
    def get(self, reference):
        return "secret"


class DiscoveryAdapter:
    async def list_models(self):
        return ["existing", "new-model"]


def test_admin_discovery_persists_new_draft_route(tmp_path):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    repository.initialize()
    provider = Provider("p", "Provider", "openai", "https://api.example/v1", "https://provider.example")
    route = ModelRoute("existing-route", "p", "existing", 1, credential_ref="memory://existing")
    repository.save_provider(provider)
    repository.save_route(route)
    app = create_app(ModelGateway([route], {route.id: DiscoveryAdapter()}), repository=repository, secrets=FakeSecrets(), api_token="api", admin_token="admin")

    response = TestClient(app).post(
        "/api/admin/providers/p/discover",
        headers={"Authorization": "Bearer admin"},
    )

    assert response.status_code == 200
    assert response.json()["data"][0]["remote_model"] == "new-model"
    assert repository.list_routes()[-1].catalog_status == "draft"
