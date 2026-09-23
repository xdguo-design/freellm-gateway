import sqlite3

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


def admin_headers():
    return {"Authorization": "Bearer admin-token"}


def save_usage(
    repository,
    *,
    request_id,
    tenant_id,
    application_id,
    provider_id,
    remote_model,
    prompt,
    completion,
    elapsed_ms=100,
):
    repository.save_usage_from_connection(
        {
            "request_id": request_id,
            "tenant_id": tenant_id,
            "application_id": application_id,
            "provider_id": provider_id,
            "remote_model": remote_model,
            "status": "success",
            "elapsed_ms": elapsed_ms,
            "stream": False,
            "usage": {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": prompt + completion,
            },
        }
    )


def test_repository_aggregates_usage_by_tenant_application_model_and_day(tmp_path):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    repository.initialize()
    repository.create_tenant("tenant-a", "Tenant A")
    repository.create_application("app-a", "tenant-a", "App A")

    save_usage(
        repository,
        request_id="r1",
        tenant_id="tenant-a",
        application_id="app-a",
        provider_id="p1",
        remote_model="m1",
        prompt=10,
        completion=4,
        elapsed_ms=100,
    )
    save_usage(
        repository,
        request_id="r2",
        tenant_id="tenant-a",
        application_id="app-a",
        provider_id="p1",
        remote_model="m1",
        prompt=20,
        completion=6,
        elapsed_ms=200,
    )

    summary = repository.usage_summary(7)

    assert summary["calls"] == 2
    assert summary["prompt_tokens"] == 30
    assert summary["completion_tokens"] == 10
    assert summary["total_tokens"] == 40
    assert summary["avg_latency_ms"] == 150.0
    assert summary["by_tenant"][0]["tenant_id"] == "tenant-a"
    assert summary["by_tenant"][0]["tenant_name"] == "Tenant A"
    assert summary["by_application"][0]["application_id"] == "app-a"
    assert summary["by_application"][0]["application_name"] == "App A"
    assert summary["by_model"][0]["remote_model"] == "m1"
    assert summary["by_day"][0]["total_tokens"] == 40


def test_usage_filters_are_parameterized_and_composable(tmp_path):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    repository.initialize()
    repository.create_tenant("tenant-a", "Tenant A")
    repository.create_tenant("tenant-b", "Tenant B")
    repository.create_application("app-a", "tenant-a", "App A")
    repository.create_application("app-b", "tenant-b", "App B")

    save_usage(
        repository,
        request_id="r1",
        tenant_id="tenant-a",
        application_id="app-a",
        provider_id="p1",
        remote_model="m1",
        prompt=10,
        completion=5,
    )
    save_usage(
        repository,
        request_id="r2",
        tenant_id="tenant-b",
        application_id="app-b",
        provider_id="p2",
        remote_model="m2",
        prompt=30,
        completion=10,
    )

    only_a = repository.usage_summary(7, tenant_id="tenant-a")
    exact_b = repository.usage_summary(
        7,
        tenant_id="tenant-b",
        application_id="app-b",
        provider_id="p2",
        remote_model="m2",
    )

    assert only_a["calls"] == 1
    assert only_a["total_tokens"] == 15
    assert only_a["filters"] == {"tenant_id": "tenant-a"}
    assert exact_b["calls"] == 1
    assert exact_b["total_tokens"] == 40
    assert exact_b["filters"] == {
        "tenant_id": "tenant-b",
        "application_id": "app-b",
        "provider_id": "p2",
        "remote_model": "m2",
    }
    assert {item["id"] for item in exact_b["filter_options"]["tenants"]} == {
        "tenant-a",
        "tenant-b",
    }
    assert {item["id"] for item in exact_b["filter_options"]["applications"]} == {
        "app-a",
        "app-b",
    }


def test_application_key_auth_attributes_usage_without_storing_plaintext_key(tmp_path):
    client, repository = make_usage_client(tmp_path, UsageAdapter())

    tenant = client.post(
        "/api/admin/tenants",
        headers=admin_headers(),
        json={"id": "tenant-a", "name": "Tenant A"},
    )
    application = client.post(
        "/api/admin/applications",
        headers=admin_headers(),
        json={"id": "app-a", "tenant_id": "tenant-a", "name": "App A"},
    )

    assert tenant.status_code == 201
    assert application.status_code == 201
    key = application.json()["api_key"]
    assert key.startswith("flm-app.app-a.")

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "remote-model",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    usage = client.get(
        "/api/admin/usage?days=7&tenant_id=tenant-a&application_id=app-a",
        headers=admin_headers(),
    )

    assert response.status_code == 200
    assert usage.status_code == 200
    data = usage.json()["data"]
    assert data["calls"] == 1
    assert data["total_tokens"] == 17
    assert data["by_tenant"][0]["tenant_id"] == "tenant-a"
    assert data["by_application"][0]["application_id"] == "app-a"

    listed = client.get("/api/admin/applications", headers=admin_headers())
    assert listed.status_code == 200
    assert listed.json()["data"][0]["id"] == "app-a"
    assert "key_hash" not in listed.text
    assert "key_salt" not in listed.text
    assert key not in listed.text

    with repository.database.connect() as connection:
        stored = connection.execute(
            "SELECT key_prefix, key_salt, key_hash FROM applications WHERE id = ?",
            ("app-a",),
        ).fetchone()
    assert stored["key_prefix"] in key
    assert stored["key_hash"] not in key
    assert stored["key_salt"] not in key


def test_invalid_application_key_is_rejected(tmp_path):
    client, _ = make_usage_client(tmp_path, UsageAdapter())
    client.post(
        "/api/admin/tenants",
        headers=admin_headers(),
        json={"id": "tenant-a", "name": "Tenant A"},
    )
    application = client.post(
        "/api/admin/applications",
        headers=admin_headers(),
        json={"id": "app-a", "tenant_id": "tenant-a", "name": "App A"},
    ).json()
    bad_key = application["api_key"][:-1] + ("A" if application["api_key"][-1] != "A" else "B")

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {bad_key}"},
        json={"model": "remote-model", "messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 401


def test_legacy_global_token_is_attributed_to_system_application(tmp_path):
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
        "/api/admin/usage?days=7&tenant_id=system&application_id=legacy-global",
        headers=admin_headers(),
    )

    assert response.status_code == 200
    assert usage.status_code == 200
    data = usage.json()["data"]
    assert data["calls"] == 1
    assert data["total_tokens"] == 17
    assert data["by_tenant"][0]["tenant_id"] == "system"
    assert data["by_application"][0]["application_id"] == "legacy-global"


def test_stream_chat_persists_authenticated_tenant_application_usage(tmp_path):
    client, _ = make_usage_client(tmp_path, StreamingUsageAdapter())
    client.post(
        "/api/admin/tenants",
        headers=admin_headers(),
        json={"id": "tenant-stream", "name": "Stream Tenant"},
    )
    key = client.post(
        "/api/admin/applications",
        headers=admin_headers(),
        json={
            "id": "app-stream",
            "tenant_id": "tenant-stream",
            "name": "Stream App",
        },
    ).json()["api_key"]

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "remote-model",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        },
    )
    usage = client.get(
        "/api/admin/usage?days=1&tenant_id=tenant-stream&application_id=app-stream",
        headers=admin_headers(),
    )

    assert response.status_code == 200
    assert "data: [DONE]" in response.text
    data = usage.json()["data"]
    assert data["calls"] == 1
    assert data["prompt_tokens"] == 7
    assert data["completion_tokens"] == 3
    assert data["total_tokens"] == 10


def test_existing_usage_database_is_migrated_with_identity_defaults(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE usage_records (
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             request_id TEXT NOT NULL,
             provider_id TEXT,
             remote_model TEXT,
             prompt_tokens INTEGER NOT NULL DEFAULT 0,
             completion_tokens INTEGER NOT NULL DEFAULT 0,
             total_tokens INTEGER NOT NULL DEFAULT 0,
             elapsed_ms INTEGER NOT NULL DEFAULT 0,
             stream INTEGER NOT NULL DEFAULT 0,
             status TEXT NOT NULL,
             created_at TEXT NOT NULL
        )"""
    )
    connection.execute(
        """INSERT INTO usage_records(
             request_id, provider_id, remote_model, prompt_tokens, completion_tokens,
             total_tokens, elapsed_ms, stream, status, created_at)
           VALUES ('legacy', 'p', 'm', 3, 2, 5, 10, 0, 'success', datetime('now'))"""
    )
    connection.commit()
    connection.close()

    database = Database(path)
    database.initialize()

    with database.connect() as migrated:
        columns = {row["name"] for row in migrated.execute("PRAGMA table_info(usage_records)")}
        row = migrated.execute(
            "SELECT tenant_id, application_id FROM usage_records WHERE request_id = 'legacy'"
        ).fetchone()

    assert {"tenant_id", "application_id"}.issubset(columns)
    assert row["tenant_id"] == "system"
    assert row["application_id"] == "legacy-global"


def test_admin_page_contains_usage_dimension_filters_and_summaries(tmp_path):
    client, _ = make_usage_client(tmp_path, UsageAdapter())

    response = client.get("/admin")

    assert response.status_code == 200
    assert 'data-view="usage"' in response.text
    assert 'id="usage-filter-tenant"' in response.text
    assert 'id="usage-filter-application"' in response.text
    assert 'id="usage-filter-provider"' in response.text
    assert 'id="usage-filter-model"' in response.text
    assert 'id="usage-tenant-rows"' in response.text
    assert 'id="usage-application-rows"' in response.text
    assert "/api/admin/usage?" in response.text
