import json

import httpx
import pytest

from freellm_gateway.adapters.base import ProviderAdapter
from freellm_gateway.adapters.openai import OpenAICompatibleAdapter
from freellm_gateway.contracts import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ImagePart,
    TextPart,
    TokenUsage,
)
from freellm_gateway.models import ModelRoute
from freellm_gateway.service import ModelGateway


def test_chat_request_round_trips_openai_payload_without_losing_provider_options():
    payload = {
        "model": "demo",
        "messages": [
            {"role": "system", "content": "Be concise."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "https://example.test/image.png", "detail": "low"},
                    },
                ],
            },
        ],
        "temperature": 0.2,
        "max_tokens": 128,
        "response_format": {"type": "json_object"},
    }

    request = ChatRequest.from_openai_payload(payload)

    assert request.model == "demo"
    assert request.messages[1].content == (
        TextPart("Describe this"),
        ImagePart("https://example.test/image.png", "low"),
    )
    assert request.to_openai_payload() == payload


def test_chat_response_maps_usage_to_gateway_token_names_and_back():
    response = ChatResponse.from_openai_response(
        {
            "id": "chat-1",
            "object": "chat.completion",
            "model": "demo",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "hello"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 3,
                "completion_tokens": 2,
                "total_tokens": 5,
            },
        }
    )

    assert response.usage == TokenUsage(3, 2, 5)
    assert response.message == ChatMessage(role="assistant", content=(TextPart("hello"),))
    assert response.to_openai_dict()["choices"][0]["message"]["content"] == "hello"


@pytest.mark.asyncio
async def test_openai_adapter_implements_normalized_provider_contract():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "chat-1",
                "model": "remote-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "pong"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAICompatibleAdapter(
        "https://example.test/v1/chat/completions",
        "secret",
        client,
        provider_id="example",
    )

    assert isinstance(adapter, ProviderAdapter)
    response = await adapter.chat(
        ChatRequest(
            model="remote-model",
            messages=(ChatMessage(role="user", content=(TextPart("ping"),)),),
        )
    )

    assert captured["payload"]["messages"] == [{"role": "user", "content": "ping"}]
    assert response.message.content == (TextPart("pong"),)
    await client.aclose()


@pytest.mark.asyncio
async def test_gateway_prefers_normalized_chat_contract_when_adapter_supports_it():
    class NativeAdapter:
        provider_id = "native"
        capabilities = frozenset({"chat"})

        def __init__(self):
            self.requests = []

        async def chat(self, request):
            self.requests.append(request)
            return ChatResponse(
                id="native-1",
                model=request.model,
                message=ChatMessage(role="assistant", content=(TextPart("ok"),)),
                finish_reason="stop",
            )

    adapter = NativeAdapter()
    route = ModelRoute(
        id="native-route",
        provider_id="native",
        remote_model="native-model",
        priority=1,
    )
    gateway = ModelGateway([route], {"native-route": adapter})

    result = await gateway.complete(
        {"model": "auto", "messages": [{"role": "user", "content": "hello"}]}
    )

    assert isinstance(adapter.requests[0], ChatRequest)
    assert adapter.requests[0].model == "native-model"
    assert result["model"] == "native-model"
    assert result["choices"][0]["message"]["content"] == "ok"
