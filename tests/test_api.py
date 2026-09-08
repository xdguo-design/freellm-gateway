from fastapi.testclient import TestClient

from freellm_gateway.api import create_app
from freellm_gateway.models import ModelRoute
from freellm_gateway.service import ModelGateway


class Adapter:
    async def complete(self, payload):
        return {"id": "ok", "model": payload["model"], "choices": []}

    async def stream(self, payload):
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
    assert {item["id"] for item in response.json()["data"]} == {"auto", "groq-llama"}
    assert "keyring" not in response.text


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
