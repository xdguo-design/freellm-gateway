from fastapi.testclient import TestClient

from freellm_gateway.api import create_app
from freellm_gateway.db import Database
from freellm_gateway.models import ModelRoute
from freellm_gateway.repository import Repository
from freellm_gateway.service import ModelGateway


class UsageAdapter:
    async def complete(self, payload):
        return {
            "id": "usage-complete",
            "model": payload["model"],
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 5,
                "total_tokens": 17,
            },
        }


class StreamingUsageAdapter:
    async def stream(self, payload):
        yield (
            b'data: {"id":"usage-stream","model":"remote-model","choices":'
            b'[{"index":0,"delta":{"role":"assistant","content":"ok"},'
            b'"finish_reason":"stop"}],"usage":{"prompt_tokens":7,'
            b'"completion_tokens":3,"total_tokens":10}}\n\n'
        )
        yield b"data: [DONE]\n\n"


def make_usage_client(tmp_path, adapter):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    route = ModelRoute(
        id="route",
        provider_id="provider",
        remote_model="remote-model",
        priority=1,
    )
    gateway = ModelGateway([route], {"route": adapter})
    app = create_app(
        gateway=gateway,
        repository=repository,
        api_token="api-token",
        admin_token="admin-token",
        logs_path=tmp_path / "gateway.log",
    )
    return TestClient(app), repository


def test_repository_aggregates_usage_by_model_and_day(tmp_path):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    repository.initialize()

    repository.save_usage_from_connection(
        {
            "request_id": "r1",
            "provider_id": "p1",
            "remote_model": "m1",
            "status": "success",
            "elapsed_ms": 100,
            "stream": False,
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 4,
                "total_tokens": 14,
            },
        }
    )
    repository.save_usage_from_connection(
        {
            "request_id": "r2",
            "provider_id": "p1",
            "remote_model": "m1",
            "status": "success",
            "elapsed_ms": 200,
            "stream": True,
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 6,
                "total_tokens": 26,
            },
        }
    )

    summary = repository.usage_summary(7)

    assert summary["calls"] == 2
    assert summary["prompt_tokens"] == 30
    assert summary["completion_tokens"] == 10
    assert summary["total_tokens"] == 40
    assert summary["avg_latency_ms"] == 150.0
    assert summary["by_model"][0]["remote_model"] == "m1"
    assert summary["by_model"][0]["total_tokens"] == 40
    assert summary["by_day"][0]["total_tokens"] == 40


def test_non_stream_chat_persists_usage_and_admin_api_exposes_it(tmp_path):
    client, _ = make_usage_client(tmp_path, UsageAdapter())

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer api-token"},
        json={
            "model": "remote-model",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    usage = client.get(
        "/api/admin/usage?days=7",
        headers={"Authorization": "Bearer admin-token"},
    )

    assert response.status_code == 200
    assert usage.status_code == 200
    data = usage.json()["data"]
    assert data["calls"] == 1
    assert data["prompt_tokens"] == 12
    assert data["completion_tokens"] == 5
    assert data["total_tokens"] == 17
    assert data["by_model"][0]["provider_id"] == "provider"
    assert data["by_model"][0]["remote_model"] == "remote-model"


def test_stream_chat_persists_usage_from_sse_chunk(tmp_path):
    client, _ = make_usage_client(tmp_path, StreamingUsageAdapter())

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer api-token"},
        json={
            "model": "remote-model",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        },
    )
    usage = client.get(
        "/api/admin/usage?days=1",
        headers={"Authorization": "Bearer admin-token"},
    )

    assert response.status_code == 200
    assert "data: [DONE]" in response.text
    data = usage.json()["data"]
    assert data["calls"] == 1
    assert data["prompt_tokens"] == 7
    assert data["completion_tokens"] == 3
    assert data["total_tokens"] == 10


def test_admin_page_contains_token_usage_dashboard(tmp_path):
    client, _ = make_usage_client(tmp_path, UsageAdapter())

    response = client.get("/admin")

    assert response.status_code == 200
    assert 'data-view="usage"' in response.text
    assert 'id="view-usage"' in response.text
    assert "/api/admin/usage?days=" in response.text
    assert 'id="usage-total"' in response.text
