import json

import pytest
from fastapi.testclient import TestClient

from freellm_gateway.adapters.openai import OpenAICompatibleAdapter
from freellm_gateway.api import create_app
from freellm_gateway.db import Database
from freellm_gateway.models import ModelRoute, Provider
from freellm_gateway.repository import Repository
from freellm_gateway.service import ModelGateway
from scripts.mock_model_service import start_mock_server


class FakeSecrets:
    def __init__(self, values):
        self.values = dict(values)

    def get(self, reference):
        return self.values.get(reference)

    def save(self, name, value):
        reference = f"memory://{name}"
        self.values[reference] = value
        return reference


@pytest.fixture(scope="module")
def mock_model_service():
    server, thread = start_mock_server()
    host, port = server.server_address
    base_url = f"http://{host}:{port}"
    try:
        yield server, base_url
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.fixture
def e2e_client(tmp_path, mock_model_service):
    server, base_url = mock_model_service
    server.records.clear()

    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    repository.initialize()
    repository.save_provider(
        Provider(
            id="mock-openai",
            name="Mock OpenAI",
            protocol="openai",
            base_url=f"{base_url}/openai/v1",
            official_url=base_url,
        )
    )
    repository.save_provider(
        Provider(
            id="mock-gemini",
            name="Mock Gemini",
            protocol="gemini",
            base_url=f"{base_url}/gemini/v1beta",
            official_url=base_url,
        )
    )

    openai_ref = "memory://mock-openai"
    gemini_ref = "memory://mock-gemini"
    routes = [
        ModelRoute(
            id="openai-fast",
            provider_id="mock-openai",
            remote_model="mock-chat",
            priority=1,
            capabilities=frozenset({"chat", "stream", "json"}),
            credential_ref=openai_ref,
            context_window=32768,
            max_output_tokens=4096,
            input_price_per_million=0.10,
            output_price_per_million=0.30,
        ),
        ModelRoute(
            id="openai-vision",
            provider_id="mock-openai",
            remote_model="mock-vision",
            priority=2,
            capabilities=frozenset({"chat", "vision", "tools", "stream", "json"}),
            credential_ref=openai_ref,
            context_window=128000,
            max_output_tokens=8192,
            input_price_per_million=0.20,
            output_price_per_million=0.80,
        ),
        ModelRoute(
            id="openai-long",
            provider_id="mock-openai",
            remote_model="mock-long",
            priority=3,
            capabilities=frozenset({"chat", "long_context"}),
            credential_ref=openai_ref,
            context_window=1000000,
            max_output_tokens=16384,
            input_price_per_million=0.40,
            output_price_per_million=1.20,
        ),
        ModelRoute(
            id="openai-embedding",
            provider_id="mock-openai",
            remote_model="mock-embedding",
            priority=4,
            capabilities=frozenset({"embedding"}),
            credential_ref=openai_ref,
            input_price_per_million=0.02,
            output_price_per_million=0.0,
        ),
        ModelRoute(
            id="openai-image",
            provider_id="mock-openai",
            remote_model="mock-image",
            priority=5,
            capabilities=frozenset({"image_generation"}),
            credential_ref=openai_ref,
            endpoint=f"{base_url}/openai/v1/images/generations",
        ),
        ModelRoute(
            id="gemini-native",
            provider_id="mock-gemini",
            remote_model="gemini-mock",
            priority=6,
            capabilities=frozenset({"chat", "vision", "tools", "stream", "json"}),
            credential_ref=gemini_ref,
            context_window=1048576,
            max_output_tokens=8192,
            input_price_per_million=0.15,
            output_price_per_million=0.60,
        ),
    ]
    for route in routes:
        repository.save_route(route)

    secrets = FakeSecrets(
        {
            openai_ref: "openai-secret",
            gemini_ref: "gemini-secret",
        }
    )
    app = create_app(
        repository=repository,
        secrets=secrets,
        api_token="api-token",
        admin_token="admin-token",
    )
    with TestClient(app) as client:
        yield client, server, base_url


def api_headers():
    return {"Authorization": "Bearer api-token"}


def admin_headers():
    return {"Authorization": "Bearer admin-token"}


def test_real_http_model_discovery_and_capability_matrix(e2e_client):
    client, server, _ = e2e_client

    models = client.get("/v1/models", headers=api_headers())
    detail = client.get("/v1/models/openai-vision", headers=api_headers())
    matrix = client.get(
        "/api/admin/models/capability-matrix",
        headers=admin_headers(),
    )
    openai_discovery = client.post(
        "/api/admin/providers/mock-openai/models",
        headers=admin_headers(),
        json={"credential": "openai-secret"},
    )
    gemini_discovery = client.post(
        "/api/admin/providers/mock-gemini/models",
        headers=admin_headers(),
        json={"credential": "gemini-secret"},
    )

    assert models.status_code == 200
    assert {item["id"] for item in models.json()["data"]} == {
        "auto",
        "openai-fast",
        "openai-vision",
        "openai-long",
        "openai-embedding",
        "openai-image",
        "gemini-native",
    }
    assert detail.status_code == 200
    assert detail.json()["capabilities"]["matrix"]["vision"] is True
    assert detail.json()["capabilities"]["matrix"]["function_calling"] is True
    assert detail.json()["capabilities"]["matrix"]["streaming"] is True
    assert detail.json()["pricing"]["input_per_million"] == 0.2
    assert matrix.status_code == 200
    assert len(matrix.json()["data"]) == 6
    assert openai_discovery.json()["data"] == [
        "mock-chat",
        "mock-vision",
        "mock-long",
        "mock-embedding",
        "mock-image",
        "mock-fail",
    ]
    assert gemini_discovery.json()["data"] == ["gemini-mock"]
    assert any(record["path"] == "/openai/v1/models" for record in server.records)
    assert any(record["path"] == "/gemini/v1beta/models" for record in server.records)


def test_real_http_openai_chat_json_vision_tools_and_stream(e2e_client):
    client, server, _ = e2e_client

    json_response = client.post(
        "/v1/chat/completions",
        headers=api_headers(),
        json={
            "model": "openai-fast",
            "messages": [{"role": "user", "content": "return json"}],
            "response_format": {"type": "json_object"},
        },
    )
    vision_response = client.post(
        "/v1/chat/completions",
        headers=api_headers(),
        json={
            "model": "openai-vision",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "what is this?"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "https://example.test/image.png"},
                        },
                    ],
                }
            ],
        },
    )
    tool_response = client.post(
        "/v1/chat/completions",
        headers=api_headers(),
        json={
            "model": "openai-vision",
            "messages": [{"role": "user", "content": "look it up"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "parameters": {
                            "type": "object",
                            "properties": {"q": {"type": "string"}},
                        },
                    },
                }
            ],
        },
    )
    stream_response = client.post(
        "/v1/chat/completions",
        headers=api_headers(),
        json={
            "model": "openai-fast",
            "messages": [{"role": "user", "content": "stream"}],
            "stream": True,
        },
    )

    assert json_response.status_code == 200
    assert json.loads(json_response.json()["choices"][0]["message"]["content"])["ok"] is True
    assert vision_response.status_code == 200
    assert vision_response.json()["choices"][0]["message"]["content"] == "vision-ok"
    assert tool_response.status_code == 200
    assert tool_response.json()["choices"][0]["finish_reason"] == "tool_calls"
    assert tool_response.json()["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "lookup"
    assert stream_response.status_code == 200
    assert '"content":"hello "' in stream_response.text
    assert '"content":"world"' in stream_response.text
    assert "data: [DONE]" in stream_response.text

    chat_records = [
        record for record in server.records
        if record["path"] == "/openai/v1/chat/completions"
    ]
    assert all(record["authorization"] == "Bearer openai-secret" for record in chat_records)
    assert any(record["body"].get("response_format") for record in chat_records)
    assert any(record["body"].get("tools") for record in chat_records)


def test_real_http_long_context_embeddings_and_image_generation(e2e_client):
    client, server, _ = e2e_client

    long_response = client.post(
        "/v1/chat/completions",
        headers=api_headers(),
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "x" * 40000}],
        },
    )
    embedding_response = client.post(
        "/v1/embeddings",
        headers=api_headers(),
        json={"model": "openai-embedding", "input": "hello embedding"},
    )
    image_response = client.post(
        "/v1/images/generations",
        headers=api_headers(),
        json={"model": "openai-image", "prompt": "a blue robot"},
    )

    assert long_response.status_code == 200
    assert long_response.json()["model"] == "mock-long"
    assert embedding_response.status_code == 200
    assert embedding_response.json()["data"][0]["embedding"] == [0.1, 0.2, 0.3, 0.4]
    assert image_response.status_code == 200
    assert image_response.json()["model"] == "mock-image"
    assert image_response.json()["data"][0]["url"] == "https://example.test/mock-image.png"
    assert any(record["path"] == "/openai/v1/embeddings" for record in server.records)
    assert any(record["path"] == "/openai/v1/images/generations" for record in server.records)


def test_real_http_gemini_native_vision_tools_json_and_stream(e2e_client):
    client, server, _ = e2e_client

    response = client.post(
        "/v1/chat/completions",
        headers=api_headers(),
        json={
            "model": "gemini-native",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "inspect"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64,AAAA"},
                        },
                    ],
                }
            ],
            "response_format": {"type": "json_object"},
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "description": "lookup data",
                        "parameters": {
                            "type": "object",
                            "properties": {"q": {"type": "string"}},
                        },
                    },
                }
            ],
        },
    )
    stream_response = client.post(
        "/v1/chat/completions",
        headers=api_headers(),
        json={
            "model": "gemini-native",
            "messages": [{"role": "user", "content": "stream"}],
            "stream": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "gemini-ok"
    assert stream_response.status_code == 200
    assert '"content":"gemini "' in stream_response.text
    assert '"content":"stream"' in stream_response.text
    assert "data: [DONE]" in stream_response.text

    request_record = next(
        record for record in server.records
        if record["path"].endswith(":generateContent")
    )
    assert request_record["gemini_key"] == "gemini-secret"
    parts = request_record["body"]["contents"][0]["parts"]
    assert parts[1] == {"inlineData": {"mimeType": "image/png", "data": "AAAA"}}
    assert request_record["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert request_record["body"]["tools"][0]["functionDeclarations"][0]["name"] == "lookup"


def test_real_http_probe_and_failover(e2e_client, mock_model_service):
    client, server, base_url = e2e_client

    probe = client.post(
        "/api/admin/routes/openai-fast/probe",
        headers=admin_headers(),
    )
    assert probe.status_code == 200
    assert probe.json()["health"] == "healthy"

    server.records.clear()
    endpoint = f"{base_url}/openai/v1/chat/completions"
    failing = OpenAICompatibleAdapter(
        endpoint,
        "openai-secret",
        provider_id="mock-openai",
    )
    fallback = OpenAICompatibleAdapter(
        endpoint,
        "openai-secret",
        provider_id="mock-openai",
    )
    gateway = ModelGateway(
        [
            ModelRoute(
                id="fail-first",
                provider_id="mock-openai",
                remote_model="mock-fail",
                priority=1,
            ),
            ModelRoute(
                id="fallback",
                provider_id="mock-openai",
                remote_model="mock-chat",
                priority=2,
            ),
        ],
        {"fail-first": failing, "fallback": fallback},
    )
    failover_client = TestClient(
        create_app(
            gateway=gateway,
            api_token="api-token",
            admin_token="admin-token",
        )
    )

    result = failover_client.post(
        "/v1/chat/completions",
        headers=api_headers(),
        json={"model": "auto", "messages": [{"role": "user", "content": "hello"}]},
    )

    assert result.status_code == 200
    assert result.json()["model"] == "mock-chat"
    attempted_models = [
        record["body"]["model"]
        for record in server.records
        if record["path"] == "/openai/v1/chat/completions"
    ]
    assert attempted_models[:2] == ["mock-fail", "mock-chat"]
