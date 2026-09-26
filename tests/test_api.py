from fastapi.testclient import TestClient

from freellm_gateway.api import create_app
from freellm_gateway.models import ModelRoute
from freellm_gateway.service import ModelGateway


class Adapter:
    def __init__(self):
        self.complete_payloads = []
        self.stream_payloads = []

    async def complete(self, payload):
        self.complete_payloads.append(payload)
        return {"id": "ok", "model": payload["model"], "choices": [{"message": {"content": "ok"}}]}

    async def stream(self, payload):
        self.stream_payloads.append(payload)
        yield b"data: {\"id\":\"ok\"}\n\n"


def client_for(routes):
    gateway = ModelGateway(routes, {route.id: Adapter() for route in routes})
    return TestClient(create_app(gateway=gateway, api_token="api-token", admin_token="admin-token"))


def test_models_endpoint_requires_token_and_hides_provider_secrets():
    route = ModelRoute(
        id="groq-llama", provider_id="groq", remote_model="llama", priority=1,
        display_name="Llama via Groq", credential_ref="keyring://secret",
    )
    client = client_for([route])

    assert client.get("/v1/models").status_code == 401
    response = client.get("/v1/models", headers={"Authorization": "Bearer api-token"})

    assert response.status_code == 200
    assert {item["id"] for item in response.json()["data"]} == {"auto", "llama"}
    assert "keyring" not in response.text


def test_models_endpoint_accepts_workbuddy_proxy_token_header():
    route = ModelRoute(
        id="groq-llama", provider_id="groq", remote_model="llama", priority=1,
    )
    client = client_for([route])

    response = client.get(
        "/v1/models",
        headers={
            "Authorization": "Bearer proxy-owned-value",
            "X-Free-LLM-Token": "api-token",
        },
    )

    assert response.status_code == 200
    assert {item["id"] for item in response.json()["data"]} == {"auto", "llama"}


def test_cors_allows_workbuddy_proxy_token_header():
    client = client_for([])

    response = client.options(
        "/v1/models",
        headers={
            "Origin": "http://localhost",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Free-LLM-Token",
        },
    )

    assert response.status_code == 200
    assert "x-free-llm-token" in response.headers["access-control-allow-headers"].lower()


def test_chat_completions_accepts_the_upstream_model_name():
    route = ModelRoute(id="google-gemini-route", provider_id="google-gemini", remote_model="gemini-3.8-flash", priority=1)
    client = client_for([route])

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer api-token"},
        json={"model": "gemini-3.8-flash", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert response.json()["model"] == "gemini-3.8-flash"


def test_chat_completions_routes_auto_request_to_remote_model():
    route = ModelRoute(id="route-1", provider_id="p1", remote_model="remote-name", priority=1)
    client = client_for([route])

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer api-token"},
        json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert response.json()["model"] == "remote-name"


def test_chat_returns_503_when_no_route_is_available():
    client = client_for([])

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer api-token"},
        json={"model": "auto", "messages": []},
    )

    assert response.status_code == 503


def test_chat_returns_404_for_unknown_explicit_model():
    route = ModelRoute(id="route-1", provider_id="p1", remote_model="remote-name", priority=1)
    client = client_for([route])

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer api-token"},
        json={"model": "missing-route", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 404


def test_chat_stream_returns_server_sent_events():
    route = ModelRoute(id="route-1", provider_id="p1", remote_model="remote-name", priority=1)
    client = client_for([route])

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer api-token"},
        json={"model": "auto", "messages": [], "stream": True},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "data:" in response.text


def test_route_reasoning_effort_is_used_as_default_and_client_can_override_it():
    route = ModelRoute(
        id="route-1", provider_id="groq", remote_model="openai/gpt-oss-120b", priority=1,
        reasoning_effort="medium",
    )
    adapter = Adapter()
    client = TestClient(create_app(ModelGateway([route], {route.id: adapter}), api_token="api-token", admin_token="admin-token"))

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer api-token"},
        json={"model": "openai/gpt-oss-120b", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 200
    assert adapter.complete_payloads[-1]["reasoning_effort"] == "medium"

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer api-token"},
        json={
            "model": "openai/gpt-oss-120b",
            "messages": [{"role": "user", "content": "hi"}],
            "reasoning_effort": "high",
        },
    )
    assert response.status_code == 200
    assert adapter.complete_payloads[-1]["reasoning_effort"] == "high"


def test_route_reasoning_effort_is_applied_to_streaming_requests():
    route = ModelRoute(
        id="route-1", provider_id="groq", remote_model="openai/gpt-oss-120b", priority=1,
        reasoning_effort="medium",
    )
    adapter = Adapter()
    client = TestClient(create_app(ModelGateway([route], {route.id: adapter}), api_token="api-token", admin_token="admin-token"))

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer api-token"},
        json={"model": "openai/gpt-oss-120b", "messages": [], "stream": True},
    )

    assert response.status_code == 200
    assert adapter.stream_payloads[-1]["reasoning_effort"] == "medium"
