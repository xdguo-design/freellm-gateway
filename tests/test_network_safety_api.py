from fastapi.testclient import TestClient

from freellm_gateway.api import create_app
from freellm_gateway.db import Database
from freellm_gateway.models import ModelRoute, Provider
from freellm_gateway.repository import Repository
from freellm_gateway.runtime import adapter_for_route


class FakeSecrets:
    def __init__(self):
        self.values = {}

    def save(self, name, value):
        reference = f"memory://{name}"
        self.values[reference] = value
        return reference

    def get(self, reference):
        return self.values.get(reference) or "secret"


def make_client(tmp_path):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    secrets = FakeSecrets()
    app = create_app(
        repository=repository,
        secrets=secrets,
        api_token="api",
        admin_token="admin",
    )
    return TestClient(app), repository, secrets


def test_admin_rejects_metadata_and_private_provider_targets(tmp_path):
    client, _, _ = make_client(tmp_path)

    for target in (
        "https://169.254.169.254/latest/meta-data",
        "https://10.0.0.8/v1",
        "https://127.0.0.1/v1",
        "https://[::1]/v1",
    ):
        response = client.post(
            "/api/admin/providers",
            json={
                "id": "unsafe",
                "name": "Unsafe",
                "protocol": "openai",
                "base_url": target,
                "official_url": "https://example.com",
            },
        )
        assert response.status_code == 422
        assert "non-public" in response.json()["detail"]


def test_admin_allows_explicit_loopback_http_for_local_development(tmp_path):
    client, _, _ = make_client(tmp_path)

    response = client.post(
        "/api/admin/providers",
        json={
            "id": "local",
            "name": "Local",
            "protocol": "openai",
            "base_url": "http://127.0.0.1:8080/v1",
            "official_url": "https://example.com",
        },
    )

    assert response.status_code == 201


def test_admin_rejects_private_route_endpoint_override(tmp_path):
    client, _, _ = make_client(tmp_path)
    provider = client.post(
        "/api/admin/providers",
        json={
            "id": "local",
            "name": "Local",
            "protocol": "openai",
            "base_url": "http://127.0.0.1:8080/v1",
            "official_url": "https://example.com",
        },
    )
    assert provider.status_code == 201

    route = client.post(
        "/api/admin/routes",
        json={
            "id": "route",
            "provider_id": "local",
            "remote_model": "model",
            "endpoint": "https://169.254.169.254/v1/chat/completions",
        },
    )

    assert route.status_code == 422
    assert "non-public" in route.json()["detail"]


def test_legacy_unsafe_provider_does_not_build_runtime_adapter():
    provider = Provider(
        "unsafe",
        "Unsafe",
        "openai",
        "https://169.254.169.254/v1",
        "https://example.com",
    )
    route = ModelRoute(
        id="unsafe-route",
        provider_id="unsafe",
        remote_model="model",
        priority=1,
        credential_ref="memory://unsafe",
    )

    assert adapter_for_route(route, provider, FakeSecrets()) is None
