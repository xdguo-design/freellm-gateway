import json

from fastapi.testclient import TestClient

from freellm_gateway.api import create_app
from freellm_gateway.connection_log import ConnectionLogger
from freellm_gateway.models import ModelRoute
from freellm_gateway.service import ModelGateway


def test_connection_logger_appends_records_and_reads_newest_first(tmp_path):
    path = tmp_path / "gateway-connections.jsonl"
    logger = ConnectionLogger(path)

    logger.append({"request_id": "first", "status": "success", "prompt": "do not persist", "api_key": "secret", "response": {"private": True}})
    logger.append({"request_id": "second", "status": "failed"})

    assert [item["request_id"] for item in logger.read()] == ["second", "first"]
    assert all("timestamp" in item for item in logger.read())
    assert all(not any(key in item for key in ("prompt", "api_key", "response")) for item in logger.read())
    assert all(isinstance(json.loads(line), dict) for line in path.read_text(encoding="utf-8").splitlines())


def test_admin_connections_requires_admin_token_and_exposes_usage(tmp_path):
    class Adapter:
        async def complete(self, payload):
            return {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            }

    route = ModelRoute(id="route", provider_id="provider", remote_model="remote-model", priority=1)
    gateway = ModelGateway([route], {route.id: Adapter()})
    app = create_app(
        gateway=gateway,
        api_token="api-token",
        admin_token="admin-token",
        logs_path=tmp_path / "gateway.log",
    )
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer api-token"},
        json={"model": "auto", "messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 200
    assert client.get("/api/admin/connections").status_code == 401
    records = client.get(
        "/api/admin/connections",
        headers={"Authorization": "Bearer admin-token"},
    ).json()["data"]
    assert records[0]["remote_model"] == "remote-model"
    assert records[0]["usage"] == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
