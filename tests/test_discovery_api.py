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


class BulkSecrets(FakeSecrets):
    def __init__(self):
        self.saved = []

    def save(self, name, value):
        self.saved.append((name, value))
        return f"memory://{name}"


class DiscoveryAdapter:
    async def list_models(self):
        return ["existing", "new-model"]


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


class OneTimeAnthropicModelsAdapter(OneTimeModelsAdapter):
    instances = []


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


def test_admin_can_fetch_provider_models_with_one_time_key(tmp_path, monkeypatch):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    repository.initialize()
    repository.save_provider(Provider("p", "Provider", "openai", "https://api.example/v1", "https://provider.example"))
    app = create_app(ModelGateway([], {}), repository=repository, api_token="api", admin_token="admin")
    monkeypatch.setattr("freellm_gateway.api.OpenAICompatibleAdapter", OneTimeModelsAdapter, raising=False)

    response = TestClient(app).post(
        "/api/admin/providers/p/models",
        headers={"Authorization": "Bearer admin"},
        json={"credential": "temporary-key"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == ["model-a", "model-b"]
    assert "temporary-key" not in response.text
    assert OneTimeModelsAdapter.instances[-1].endpoint == "https://api.example/v1/chat/completions"
    assert OneTimeModelsAdapter.instances[-1].api_key == "temporary-key"
    assert OneTimeModelsAdapter.instances[-1].closed is True


def test_admin_can_fetch_anthropic_provider_models_with_one_time_key(tmp_path, monkeypatch):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    repository.initialize()
    repository.save_provider(Provider(
        "anthropic", "Anthropic", "anthropic", "https://api.anthropic.com/v1", "https://anthropic.com",
    ))
    app = create_app(ModelGateway([], {}), repository=repository, api_token="api", admin_token="admin")

    def make_adapter(endpoint, credential):
        return OneTimeAnthropicModelsAdapter(endpoint, credential)

    monkeypatch.setattr("freellm_gateway.api.AnthropicAdapter", make_adapter, raising=False)
    response = TestClient(app).post(
        "/api/admin/providers/anthropic/models",
        headers={"Authorization": "Bearer admin"},
        json={"credential": "temporary-key"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == ["model-a", "model-b"]
    assert OneTimeAnthropicModelsAdapter.instances[-1].endpoint == "https://api.anthropic.com/v1/messages"
    assert OneTimeAnthropicModelsAdapter.instances[-1].closed is True


def test_admin_can_fetch_gemini_provider_models_with_one_time_key(tmp_path, monkeypatch):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    repository.initialize()
    repository.save_provider(Provider(
        "gemini", "Gemini", "gemini", "https://generativelanguage.googleapis.com/v1beta", "https://ai.google.dev",
    ))
    app = create_app(ModelGateway([], {}), repository=repository, api_token="api", admin_token="admin")
    monkeypatch.setattr("freellm_gateway.api.GeminiAdapter", OneTimeModelsAdapter, raising=False)

    response = TestClient(app).post(
        "/api/admin/providers/gemini/models",
        headers={"Authorization": "Bearer admin"},
        json={"credential": "temporary-key"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == ["model-a", "model-b"]
    assert OneTimeModelsAdapter.instances[-1].endpoint == "https://generativelanguage.googleapis.com/v1beta"
    assert OneTimeModelsAdapter.instances[-1].api_key == "temporary-key"
    assert OneTimeModelsAdapter.instances[-1].closed is True


def test_admin_provider_create_accepts_anthropic_and_rejects_unknown_protocol(tmp_path):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    app = create_app(repository=repository, secrets=BulkSecrets(), api_token="api", admin_token="admin")
    client = TestClient(app)
    headers = {"Authorization": "Bearer admin"}
    base = {
        "id": "anthropic", "name": "Anthropic", "base_url": "https://api.anthropic.com",
        "official_url": "https://anthropic.com",
    }

    accepted = client.post("/api/admin/providers", headers=headers, json={**base, "protocol": "anthropic"})
    rejected = client.post("/api/admin/providers", headers=headers, json={**base, "id": "unknown", "protocol": "custom"})

    assert accepted.status_code == 201
    assert accepted.json()["protocol"] == "anthropic"
    assert rejected.status_code == 422


def test_admin_provider_create_accepts_gemini(tmp_path):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    app = create_app(repository=repository, secrets=BulkSecrets(), api_token="api", admin_token="admin")
    response = TestClient(app).post(
        "/api/admin/providers",
        headers={"Authorization": "Bearer admin"},
        json={
            "id": "gemini", "name": "Gemini", "protocol": "gemini",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "official_url": "https://ai.google.dev",
        },
    )

    assert response.status_code == 201
    assert response.json()["protocol"] == "gemini"


def test_admin_bulk_import_accepts_anthropic_provider(tmp_path):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    secrets = BulkSecrets()
    app = create_app(ModelGateway([], {}), repository=repository, secrets=secrets, api_token="api", admin_token="admin")

    response = TestClient(app).post(
        "/api/admin/routes/bulk",
        headers={"Authorization": "Bearer admin"},
        json={
            "provider": {
                "id": "anthropic", "name": "Anthropic", "protocol": "anthropic",
                "base_url": "https://api.anthropic.com", "official_url": "https://anthropic.com",
            },
            "models": [{"remote_model": "claude-demo"}],
            "credential": "anthropic-key",
        },
    )

    assert response.status_code == 200
    assert repository.list_providers()[0].protocol == "anthropic"


def test_admin_model_fetch_requires_a_key_and_known_provider(tmp_path):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    repository.initialize()
    repository.save_provider(Provider("p", "Provider", "openai", "https://api.example/v1", "https://provider.example"))
    app = create_app(ModelGateway([], {}), repository=repository, api_token="api", admin_token="admin")
    client = TestClient(app)
    headers = {"Authorization": "Bearer admin"}

    missing_key = client.post("/api/admin/providers/p/models", headers=headers, json={})
    unknown_provider = client.post(
        "/api/admin/providers/missing/models",
        headers=headers,
        json={"credential": "temporary-key"},
    )

    assert missing_key.status_code == 422
    assert unknown_provider.status_code == 404


def test_admin_can_bulk_import_provider_models(tmp_path):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    repository.initialize()
    secrets = BulkSecrets()
    app = create_app(ModelGateway([], {}), repository=repository, secrets=secrets, api_token="api", admin_token="admin")

    response = TestClient(app).post(
        "/api/admin/routes/bulk",
        headers={"Authorization": "Bearer admin"},
        json={
            "provider": {
                "id": "openrouter",
                "name": "OpenRouter",
                "protocol": "openai",
                "base_url": "https://openrouter.ai/api/v1",
                "official_url": "https://openrouter.ai/",
            },
            "models": [
                {"remote_model": "qwen/qwen3-30b-a3b:free", "enabled": True},
                {"remote_model": "deepseek/deepseek-chat:free", "enabled": False},
            ],
            "credential": "bulk-secret",
        },
    )

    assert response.status_code == 200
    assert len(response.json()["data"]["created"]) == 2
    assert response.json()["data"]["skipped"] == []
    assert [route.remote_model for route in repository.list_routes()] == [
        "qwen/qwen3-30b-a3b:free",
        "deepseek/deepseek-chat:free",
    ]
    assert [route.enabled for route in repository.list_routes()] == [True, False]
    assert repository.list_providers()[0].name == "OpenRouter"
    assert [value for _, value in secrets.saved] == ["bulk-secret", "bulk-secret"]
    assert "bulk-secret" not in response.text


def test_admin_bulk_import_is_idempotent_and_validates_models(tmp_path):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    repository.initialize()
    secrets = BulkSecrets()
    app = create_app(ModelGateway([], {}), repository=repository, secrets=secrets, api_token="api", admin_token="admin")
    client = TestClient(app)
    headers = {"Authorization": "Bearer admin"}
    payload = {
        "provider": {
            "id": "p",
            "name": "Provider",
            "protocol": "openai",
            "base_url": "https://api.example/v1",
            "official_url": "https://provider.example/",
        },
        "models": [{"remote_model": "model-a"}],
        "credential": "bulk-secret",
    }

    first = client.post("/api/admin/routes/bulk", headers=headers, json=payload)
    second = client.post("/api/admin/routes/bulk", headers=headers, json=payload)
    empty = client.post("/api/admin/routes/bulk", headers=headers, json={**payload, "models": []})
    invalid = client.post("/api/admin/routes/bulk", headers=headers, json={**payload, "models": [{"remote_model": 3}]})

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["data"]["created"] == []
    assert second.json()["data"]["skipped"] == [{"remote_model": "model-a"}]
    assert len(repository.list_routes()) == 1
    assert empty.status_code == 422
    assert invalid.status_code == 422


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
        ]},
    )

    assert response.status_code == 200
    assert len(response.json()["data"]["created"]) == 2
    assert response.json()["data"]["skipped"] == []
    assert response.json()["data"]["failed"] == []
    assert {(route.provider_id, route.remote_model) for route in repository.list_routes()} == {
        ("p-us", "us-model"), ("p-eu", "eu-model"),
    }
    assert [value for _, value in secrets.saved] == ["us-key", "eu-key"]
    assert "us-key" not in response.text and "eu-key" not in response.text


def test_admin_bulk_connections_is_idempotent_and_reports_one_connection_failure(tmp_path):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    secrets = BulkSecrets()
    app = create_app(ModelGateway([], {}), repository=repository, secrets=secrets, api_token="api", admin_token="admin")
    client = TestClient(app)
    headers = {"Authorization": "Bearer admin"}
    payload = {"connections": [
        {"provider": {"id": "good", "name": "Good", "protocol": "openai", "base_url": "https://good.example/v1", "official_url": "https://good.example"}, "credential": "good-key", "models": [{"remote_model": "model"}]},
        {"provider": {"id": "bad", "name": "Bad", "protocol": "openai", "base_url": "http://bad.example/v1", "official_url": "https://bad.example"}, "credential": "bad-key", "models": [{"remote_model": "model"}]},
    ]}

    first = client.post("/api/admin/routes/bulk-connections", headers=headers, json=payload)
    second = client.post("/api/admin/routes/bulk-connections", headers=headers, json={"connections": [payload["connections"][0]]})

    assert first.status_code == 200
    assert first.json()["data"]["failed"][0]["error_type"] == "validation_error"
    assert second.json()["data"]["created"] == []
    assert second.json()["data"]["skipped"] == [{"provider_id": "good", "remote_model": "model"}]
