import httpx
import pytest

from freellm_gateway.adapters.openai import OpenAICompatibleAdapter, ProviderError


@pytest.mark.asyncio
async def test_openai_adapter_posts_bearer_request_and_returns_json():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://example.test/v1/chat/completions")
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(200, json={"id": "ok", "choices": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAICompatibleAdapter(
        endpoint="https://example.test/v1/chat/completions", api_key="secret", client=client
    )

    result = await adapter.complete({"model": "demo", "messages": []})

    assert result["id"] == "ok"
    await client.aclose()


@pytest.mark.asyncio
async def test_openai_adapter_classifies_rate_limit_error():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(429, json={"error": {"message": "quota exceeded"}}))
    )
    adapter = OpenAICompatibleAdapter("https://example.test/v1/chat/completions", "secret", client)

    with pytest.raises(ProviderError) as error:
        await adapter.complete({"model": "demo", "messages": []})

    assert error.value.kind == "quota_exhausted"
    await client.aclose()


@pytest.mark.asyncio
async def test_openai_adapter_streams_server_sent_events():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"data: one\n\ndata: two\n\n"))
    )
    adapter = OpenAICompatibleAdapter("https://example.test/v1/chat/completions", "secret", client)

    chunks = [chunk async for chunk in adapter.stream({"model": "demo", "messages": [], "stream": True})]

    assert b"data: one" in b"".join(chunks)
    await client.aclose()
