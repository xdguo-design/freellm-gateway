import json

import httpx
import pytest

from freellm_gateway.adapters.gemini import GeminiAdapter
from freellm_gateway.adapters.base import ProviderError


@pytest.mark.asyncio
async def test_gemini_adapter_translates_complete_request_and_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent"
        )
        assert request.headers["x-goog-api-key"] == "secret"
        assert "key" not in request.url.params
        assert json.loads(request.content) == {
            "systemInstruction": {"parts": [{"text": "You are concise."}]},
            "contents": [
                {"role": "user", "parts": [{"text": "Hello"}]},
                {"role": "model", "parts": [{"text": "Hi"}]},
                {"role": "user", "parts": [{"text": "How are you?"}]},
            ],
            "generationConfig": {
                "temperature": 0.2,
                "topP": 0.8,
                "maxOutputTokens": 64,
                "stopSequences": ["END"],
            },
        }
        return httpx.Response(
            200,
            json={
                "responseId": "response-1",
                "modelVersion": "gemini-3.8-flash",
                "candidates": [{
                    "content": {"role": "model", "parts": [{"text": "I am fine."}]},
                    "finishReason": "STOP",
                }],
                "usageMetadata": {
                    "promptTokenCount": 10,
                    "candidatesTokenCount": 4,
                    "totalTokenCount": 14,
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = GeminiAdapter(
        "https://generativelanguage.googleapis.com/v1beta", "secret", client
    )

    result = await adapter.complete({
        "model": "gemini-3.8-flash",
        "messages": [
            {"role": "system", "content": "You are concise."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "How are you?"},
        ],
        "temperature": 0.2,
        "top_p": 0.8,
        "max_tokens": 64,
        "stop": "END",
    })

    assert result["id"] == "response-1"
    assert result["model"] == "gemini-3.8-flash"
    assert result["choices"][0] == {
        "index": 0,
        "message": {"role": "assistant", "content": "I am fine."},
        "finish_reason": "stop",
    }
    assert result["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 4,
        "total_tokens": 14,
    }
    await adapter.aclose()


@pytest.mark.asyncio
async def test_gemini_adapter_translates_streaming_sse():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:streamGenerateContent?alt=sse"
        )
        assert request.headers["x-goog-api-key"] == "secret"
        body = b"".join([
            b'data: {"responseId":"response-1","modelVersion":"gemini-3.8-flash","candidates":[{"content":{"role":"model","parts":[{"text":"Hello"}]}}]}\n\n',
            b'data: {"candidates":[{"content":{"parts":[{"text":" world"}]},"finishReason":"STOP"}],"usageMetadata":{"promptTokenCount":3,"candidatesTokenCount":2,"totalTokenCount":5}}\n\n',
        ])
        return httpx.Response(200, content=body)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = GeminiAdapter(
        "https://generativelanguage.googleapis.com/v1beta", "secret", client
    )

    chunks = [chunk async for chunk in adapter.stream({
        "model": "gemini-3.8-flash",
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": True,
    })]

    events = [
        json.loads(line[6:])
        for chunk in chunks
        for line in chunk.decode().splitlines()
        if line.startswith("data: {")
    ]
    assert events[0]["choices"][0]["delta"] == {"role": "assistant"}
    assert events[1]["choices"][0]["delta"] == {"content": "Hello"}
    assert events[2]["choices"][0]["delta"] == {"content": " world"}
    assert events[2]["choices"][0]["finish_reason"] == "stop"
    assert events[2]["usage"] == {
        "prompt_tokens": 3,
        "completion_tokens": 2,
        "total_tokens": 5,
    }
    assert chunks[-1] == b"data: [DONE]\n\n"
    await adapter.aclose()


@pytest.mark.asyncio
async def test_gemini_adapter_lists_only_generate_content_models():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url == httpx.URL(
            "https://generativelanguage.googleapis.com/v1beta/models"
        )
        assert request.headers["x-goog-api-key"] == "secret"
        return httpx.Response(200, json={
            "models": [
                {
                    "name": "models/gemini-3.8-flash",
                    "baseModelId": "gemini-3.8-flash",
                    "supportedGenerationMethods": ["generateContent"],
                },
                {
                    "name": "models/embedding-001",
                    "baseModelId": "embedding-001",
                    "supportedGenerationMethods": ["embedContent"],
                },
                {
                    "name": "models/missing-id",
                    "supportedGenerationMethods": ["generateContent"],
                },
            ]
        })

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = GeminiAdapter(
        "https://generativelanguage.googleapis.com/v1beta", "secret", client
    )

    assert await adapter.list_models() == ["gemini-3.8-flash"]
    await adapter.aclose()


@pytest.mark.asyncio
async def test_gemini_adapter_lists_generate_content_models_across_pages():
    requested_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.params.get("pageToken") == "next-page":
            return httpx.Response(200, json={
                "models": [{
                    "name": "models/gemini-2.5-flash",
                    "baseModelId": "gemini-2.5-flash",
                    "supportedGenerationMethods": ["generateContent"],
                }]
            })
        return httpx.Response(200, json={
            "models": [{
                "name": "models/gemini-3.8-flash",
                "baseModelId": "gemini-3.8-flash",
                "supportedGenerationMethods": ["generateContent"],
            }],
            "nextPageToken": "next-page",
        })

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = GeminiAdapter(
        "https://generativelanguage.googleapis.com/v1beta", "secret", client
    )

    assert await adapter.list_models() == ["gemini-3.8-flash", "gemini-2.5-flash"]
    assert requested_urls == [
        "https://generativelanguage.googleapis.com/v1beta/models",
        "https://generativelanguage.googleapis.com/v1beta/models?pageToken=next-page",
    ]
    await adapter.aclose()


@pytest.mark.asyncio
async def test_gemini_adapter_classifies_authentication_error():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(401, json={"error": {"message": "invalid key"}})
        )
    )
    adapter = GeminiAdapter(
        "https://generativelanguage.googleapis.com/v1beta", "secret", client
    )

    with pytest.raises(ProviderError) as error:
        await adapter.complete({"model": "gemini-3.8-flash", "messages": []})

    assert error.value.kind == "authentication_error"
    assert error.value.retriable is False
    await adapter.aclose()


@pytest.mark.asyncio
async def test_gemini_adapter_rejects_malformed_completion_response():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"not-json"))
    )
    adapter = GeminiAdapter(
        "https://generativelanguage.googleapis.com/v1beta", "secret", client
    )

    with pytest.raises(ProviderError) as error:
        await adapter.complete({"model": "gemini-3.8-flash", "messages": []})

    assert error.value.kind == "provider_protocol_error"
    assert error.value.retriable is False
    await adapter.aclose()


@pytest.mark.asyncio
async def test_gemini_adapter_rejects_malformed_model_list():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"models": {"invalid": True}}))
    )
    adapter = GeminiAdapter(
        "https://generativelanguage.googleapis.com/v1beta", "secret", client
    )

    with pytest.raises(ProviderError) as error:
        await adapter.list_models()

    assert error.value.kind == "provider_protocol_error"
    assert error.value.retriable is False
    await adapter.aclose()


@pytest.mark.asyncio
async def test_gemini_adapter_rejects_empty_stream():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b""))
    )
    adapter = GeminiAdapter(
        "https://generativelanguage.googleapis.com/v1beta", "secret", client
    )

    with pytest.raises(ProviderError) as error:
        [chunk async for chunk in adapter.stream({
            "model": "gemini-3.8-flash",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        })]

    assert error.value.kind == "empty_output"
    assert error.value.retriable is False
    await adapter.aclose()


@pytest.mark.asyncio
async def test_gemini_adapter_rejects_completion_without_candidates():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"responseId": "empty"}))
    )
    adapter = GeminiAdapter(
        "https://generativelanguage.googleapis.com/v1beta", "secret", client
    )

    with pytest.raises(ProviderError) as error:
        await adapter.complete({"model": "gemini-3.8-flash", "messages": []})

    assert error.value.kind == "provider_protocol_error"
    assert error.value.retriable is False
    await adapter.aclose()


@pytest.mark.asyncio
async def test_gemini_adapter_rejects_malformed_stream_event():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"data: {not-json}\n\n")
        )
    )
    adapter = GeminiAdapter(
        "https://generativelanguage.googleapis.com/v1beta", "secret", client
    )

    with pytest.raises(ProviderError) as error:
        [chunk async for chunk in adapter.stream({
            "model": "gemini-3.8-flash",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        })]

    assert error.value.kind == "provider_protocol_error"
    assert error.value.retriable is False
    await adapter.aclose()
