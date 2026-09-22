import json

import httpx
import pytest
from fastapi.testclient import TestClient

from freellm_gateway.adapters.base import ProviderAdapter, ProviderError
from freellm_gateway.adapters.gemini import GeminiNativeAdapter
from freellm_gateway.api import create_app
from freellm_gateway.contracts import ChatMessage, ChatRequest, TextPart, TokenUsage
from freellm_gateway.db import Database
from freellm_gateway.models import ModelRoute, Provider
from freellm_gateway.repository import Repository
from freellm_gateway.service import ModelGateway


@pytest.mark.asyncio
async def test_gemini_native_chat_maps_system_image_tools_and_usage():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["key"] = request.headers["x-goog-api-key"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "responseId": "gemini-response-1",
                "modelVersion": "gemini-3.8-flash",
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": "pong"}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 7,
                    "candidatesTokenCount": 2,
                    "totalTokenCount": 9,
                    "thoughtsTokenCount": 1,
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = GeminiNativeAdapter(
        "https://generativelanguage.googleapis.com/v1beta",
        "secret",
        client,
        provider_id="google",
    )
    request = ChatRequest.from_openai_payload(
        {
            "model": "gemini-3.8-flash",
            "messages": [
                {"role": "system", "content": "Be concise."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What is in this image?"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64,AAAA"},
                        },
                    ],
                },
            ],
            "temperature": 0.2,
            "max_tokens": 128,
            "response_format": {"type": "json_object"},
            "tool_choice": "required",
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "description": "Look something up",
                        "parameters": {
                            "type": "object",
                            "properties": {"q": {"type": "string"}},
                            "required": ["q"],
                        },
                    },
                }
            ],
        }
    )

    assert isinstance(adapter, ProviderAdapter)
    response = await adapter.chat(request)

    assert captured["url"].endswith("/models/gemini-3.8-flash:generateContent")
    assert captured["key"] == "secret"
    assert captured["body"]["systemInstruction"] == {
        "parts": [{"text": "Be concise."}]
    }
    assert captured["body"]["contents"][0]["parts"][1] == {
        "inlineData": {"mimeType": "image/png", "data": "AAAA"}
    }
    assert captured["body"]["generationConfig"]["maxOutputTokens"] == 128
    assert captured["body"]["generationConfig"]["temperature"] == 0.2
    assert captured["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert captured["body"]["tools"][0]["functionDeclarations"][0]["name"] == "lookup"
    assert captured["body"]["toolConfig"]["functionCallingConfig"]["mode"] == "ANY"
    assert response.id == "gemini-response-1"
    assert response.message.content == (TextPart("pong"),)
    assert response.finish_reason == "stop"
    assert response.usage == TokenUsage(
        7,
        2,
        9,
        extra={"thoughtsTokenCount": 1},
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_gemini_native_maps_function_calls_and_tool_results():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "functionCall": {
                                        "id": "call-weather",
                                        "name": "get_weather",
                                        "args": {"city": "Tokyo"},
                                    }
                                }
                            ]
                        },
                        "finishReason": "STOP",
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = GeminiNativeAdapter("https://example.test/v1beta", "secret", client)
    request = ChatRequest.from_openai_payload(
        {
            "model": "gemini-test",
            "messages": [
                {"role": "user", "content": "Weather?"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-weather",
                            "type": "function",
                            "function": {
                                "name": "get_weather",
                                "arguments": "{\"city\":\"Tokyo\"}",
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call-weather",
                    "content": "{\"temperature\":25}",
                },
            ],
        }
    )

    response = await adapter.chat(request)

    assistant_parts = captured["body"]["contents"][1]["parts"]
    assert assistant_parts[0]["functionCall"]["name"] == "get_weather"
    tool_parts = captured["body"]["contents"][2]["parts"]
    assert tool_parts[0]["functionResponse"] == {
        "name": "get_weather",
        "response": {"temperature": 25},
        "id": "call-weather",
    }
    assert response.finish_reason == "tool_calls"
    assert response.message.tool_calls[0]["id"] == "call-weather"
    assert response.message.tool_calls[0]["function"]["name"] == "get_weather"
    await client.aclose()


@pytest.mark.asyncio
async def test_gemini_native_classifies_quota_error():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                429,
                json={"error": {"message": "Resource exhausted: quota exceeded"}},
            )
        )
    )
    adapter = GeminiNativeAdapter("https://example.test/v1beta", "secret", client)

    with pytest.raises(ProviderError) as error:
        await adapter.chat(
            ChatRequest(
                model="gemini-test",
                messages=(ChatMessage(role="user", content=(TextPart("hi"),)),),
            )
        )

    assert error.value.kind == "quota_exhausted"
    await client.aclose()


@pytest.mark.asyncio
async def test_gemini_native_lists_generate_content_models_only():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1beta/models"
        assert request.url.params["pageSize"] == "1000"
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "name": "models/gemini-3.8-flash",
                        "displayName": "Gemini 3.8 Flash",
                        "inputTokenLimit": 1048576,
                        "supportedGenerationMethods": ["generateContent", "countTokens"],
                    },
                    {
                        "name": "models/gemini-embedding-001",
                        "supportedGenerationMethods": ["embedContent"],
                    },
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = GeminiNativeAdapter(
        "https://example.test/v1beta",
        "secret",
        client,
        provider_id="google",
    )

    models = await adapter.models()

    assert [model.id for model in models] == ["gemini-3.8-flash"]
    assert models[0].provider_id == "google"
    assert models[0].context_window == 1048576
    await client.aclose()


@pytest.mark.asyncio
async def test_gateway_streams_gemini_native_chunks_as_openai_sse():
    stream = (
        b'data: {"responseId":"r1","modelVersion":"gemini-test","candidates":'
        b'[{"content":{"parts":[{"text":"hel"}]}}]}\n\n'
        b'data: {"responseId":"r1","modelVersion":"gemini-test","candidates":'
        b'[{"content":{"parts":[{"text":"lo"}]},"finishReason":"STOP"}],'
        b'"usageMetadata":{"promptTokenCount":1,"candidatesTokenCount":2,"totalTokenCount":3}}\n\n'
    )
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=stream)
        )
    )
    adapter = GeminiNativeAdapter("https://example.test/v1beta", "secret", client)
    route = ModelRoute(
        id="gemini",
        provider_id="google",
        remote_model="gemini-test",
        priority=1,
    )
    gateway = ModelGateway([route], {"gemini": adapter})

    body = b"".join(
        [
            chunk
            async for chunk in gateway.stream(
                {
                    "model": "auto",
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": True,
                }
            )
        ]
    )

    assert b'"content":"hel"' in body
    assert b'"content":"lo"' in body
    assert b'"finish_reason":"stop"' in body
    assert body.endswith(b"data: [DONE]\n\n")
    await client.aclose()


def test_admin_can_list_models_for_gemini_provider(monkeypatch, tmp_path):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    repository.initialize()
    repository.save_provider(
        Provider(
            "google",
            "Google Gemini",
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta",
            "https://ai.google.dev",
        )
    )

    created = {}

    class FakeGeminiAdapter:
        def __init__(self, base_url, api_key, *, provider_id):
            created["base_url"] = base_url
            created["api_key"] = api_key
            created["provider_id"] = provider_id

        async def list_models(self):
            return ["gemini-3.8-flash"]

        async def aclose(self):
            created["closed"] = True

    monkeypatch.setattr(
        "freellm_gateway.api.GeminiNativeAdapter",
        FakeGeminiAdapter,
    )

    app = create_app(
        ModelGateway([], {}),
        repository=repository,
        api_token="api",
        admin_token="admin",
    )
    client = TestClient(app)
    response = client.post(
        "/api/admin/providers/google/models",
        headers={"Authorization": "Bearer admin"},
        json={"credential": "gemini-secret"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == ["gemini-3.8-flash"]
    assert created == {
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "api_key": "gemini-secret",
        "provider_id": "google",
        "closed": True,
    }
