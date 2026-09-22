from fastapi.testclient import TestClient

from freellm_gateway.api import create_app
from freellm_gateway.db import Database
from freellm_gateway.models import ModelRoute, Provider
from freellm_gateway.repository import Repository
from freellm_gateway.service import ModelGateway


class Adapter:
    def __init__(self, answer: str):
        self.answer = answer

    async def complete(self, payload):
        return {
            "model": payload["model"],
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": self.answer,
                    }
                }
            ],
        }


def make_client(tmp_path):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    repository.initialize()
    provider = Provider(
        id="provider-1",
        name="Provider One",
        protocol="openai",
        base_url="https://example.test/v1",
        official_url="https://example.test",
    )
    repository.save_provider(provider)
    routes = [
        ModelRoute(
            id="route-a",
            provider_id=provider.id,
            remote_model="model-a",
            priority=1,
        ),
        ModelRoute(
            id="route-b",
            provider_id=provider.id,
            remote_model="model-b",
            priority=2,
        ),
    ]
    for route in routes:
        repository.save_route(route)
    gateway = ModelGateway(
        routes,
        {
            "route-a": Adapter("answer-a"),
            "route-b": Adapter("answer-b"),
        },
    )
    client = TestClient(
        create_app(
            gateway=gateway,
            repository=repository,
            api_token="api-token",
            admin_token="admin-token",
        )
    )
    return client, repository


def test_admin_can_configure_parallel_group_and_execute_it(tmp_path):
    client, repository = make_client(tmp_path)
    admin_headers = {"Authorization": "Bearer admin-token"}
    api_headers = {"Authorization": "Bearer api-token"}

    policy_response = client.post(
        "/api/admin/execution-policies",
        headers=admin_headers,
        json={
            "id": "parallel-policy",
            "name": "Parallel answers",
            "strategy": "parallel",
            "timeout_ms": 5000,
            "max_concurrency": 2,
        },
    )
    assert policy_response.status_code == 201

    group_response = client.post(
        "/api/admin/model-groups",
        headers=admin_headers,
        json={
            "id": "answer-team",
            "name": "Answer team",
            "policy_id": "parallel-policy",
            "members": ["route-a", "route-b"],
        },
    )
    assert group_response.status_code == 201
    assert [member["route_id"] for member in group_response.json()["members"]] == [
        "route-a",
        "route-b",
    ]

    response = client.post(
        "/v1/model-groups/answer-team/chat/completions",
        headers=api_headers,
        json={"messages": [{"role": "user", "content": "give me an answer"}]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "multi_model.chat.completion"
    assert body["strategy"] == "parallel"
    assert body["status"] == "succeeded"
    assert body["success_count"] == 2
    assert [item["route_id"] for item in body["results"]] == ["route-a", "route-b"]
    assert [
        item["response"]["choices"][0]["message"]["content"]
        for item in body["results"]
    ] == ["answer-a", "answer-b"]

    runs = repository.list_model_runs(group_id="answer-team")
    assert len(runs) == 1
    assert runs[0].status == "succeeded"
    assert runs[0].results_json is not None


def test_group_execution_rejects_streaming(tmp_path):
    client, _ = make_client(tmp_path)
    admin_headers = {"Authorization": "Bearer admin-token"}
    api_headers = {"Authorization": "Bearer api-token"}

    client.post(
        "/api/admin/execution-policies",
        headers=admin_headers,
        json={
            "id": "single-policy",
            "name": "Single",
            "strategy": "single",
        },
    )
    client.post(
        "/api/admin/model-groups",
        headers=admin_headers,
        json={
            "id": "single-group",
            "name": "Single group",
            "policy_id": "single-policy",
            "members": ["route-a"],
        },
    )

    response = client.post(
        "/v1/model-groups/single-group/chat/completions",
        headers=api_headers,
        json={
            "stream": True,
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 422
    assert "streaming" in response.json()["detail"]
