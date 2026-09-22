from fastapi.testclient import TestClient

from freellm_gateway.api import create_app
from freellm_gateway.db import Database
from freellm_gateway.repository import Repository


class FakeSecrets:
    def __init__(self):
        self.values = {}

    def save(self, name, value):
        reference = f"memory://{name}"
        self.values[reference] = value
        return reference

    def get(self, reference):
        return self.values.get(reference)


def test_admin_provider_and_route_changes_survive_reload(tmp_path):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    secrets = FakeSecrets()
    app = create_app(repository=repository, secrets=secrets, api_token="api", admin_token="admin")
    client = TestClient(app)
    headers = {"Authorization": "Bearer admin"}

    provider_response = client.post(
        "/api/admin/providers",
        headers=headers,
        json={
            "id": "groq", "name": "Groq", "protocol": "openai",
            "base_url": "https://api.groq.com/openai/v1", "official_url": "https://groq.com",
        },
    )
    route_response = client.post(
        "/api/admin/routes",
        headers=headers,
        json={
            "id": "groq-llama", "provider_id": "groq", "remote_model": "llama",
            "credential": "secret", "public_url": "https://console.groq.com",
            "capabilities": ["chat", "tools", "stream"],
            "context_window": 131072,
            "max_output_tokens": 8192,
            "input_price_per_million": 0.2,
            "output_price_per_million": 0.8,
            "pricing_currency": "usd",
        },
    )

    assert provider_response.status_code == 201
    assert route_response.status_code == 201
    assert repository.list_routes()[0].credential_ref.startswith("memory://")

    reloaded = create_app(repository=repository, secrets=secrets, api_token="api", admin_token="admin")
    assert [route.id for route in reloaded.state.gateway.routes] == ["groq-llama"]
    loaded = reloaded.state.gateway.route("groq-llama")
    assert loaded.context_window == 131072
    assert loaded.max_output_tokens == 8192
    assert loaded.input_price_per_million == 0.2
    assert loaded.output_price_per_million == 0.8
    assert loaded.pricing_currency == "USD"
    assert reloaded.state.gateway.registry.profile("groq-llama").supports("function_calling")
