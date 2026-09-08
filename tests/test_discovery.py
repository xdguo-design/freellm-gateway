import httpx
import pytest

from freellm_gateway.adapters.openai import OpenAICompatibleAdapter
from freellm_gateway.discovery import discover_new_routes
from freellm_gateway.models import ModelRoute, Provider


@pytest.mark.asyncio
async def test_openai_adapter_lists_remote_models():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"data": [{"id": "new-model"}]}))
    )
    adapter = OpenAICompatibleAdapter("https://example.test/v1/chat/completions", "secret", client)

    models = await adapter.list_models()

    assert models == ["new-model"]
    await client.aclose()


@pytest.mark.asyncio
async def test_discovery_returns_only_new_draft_routes():
    provider = Provider("groq", "Groq", "openai", "https://api.groq.com/openai/v1", "https://groq.com")
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"data": [{"id": "old"}, {"id": "new"}]}))
    )
    adapter = OpenAICompatibleAdapter("https://example.test/v1/chat/completions", "secret", client)
    existing = [ModelRoute("old-route", "groq", "old", 1)]

    routes = await discover_new_routes(provider, adapter, existing)

    assert len(routes) == 1
    assert routes[0].remote_model == "new"
    assert routes[0].catalog_status == "draft"
    await client.aclose()
