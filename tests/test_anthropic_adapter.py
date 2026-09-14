import json

import httpx
import pytest

from freellm_gateway.adapters.anthropic import AnthropicAdapter
from freellm_gateway.adapters.base import ProviderError


@pytest.mark.asyncio
async def test_anthropic_adapter_translates_messages_and_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://example.test/v1/messages")
        assert request.headers["x-api-key"] == "secret"
        assert request.headers["anthropic-version"] == "2023-06-01"
        payload = json.loads(request.content)
        assert payload == {
            "model": "claude-demo",
            "max_tokens": 64,
            "system": "Be concise.",
            "messages": [{"role": "user", "content": "Hello"}],
            "stop_sequences": ["END"],
        }
        return httpx.Response(
            200,
            json={
                "id": "msg_123",
                "type": "message",
                "role": "assistant",
                "model": "claude-demo",
                "content": [{"type": "text", "text": "Hi there"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 7, "output_tokens": 2},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = AnthropicAdapter("https://example.test/v1/messages", "secret", client)

    result = await adapter.complete({
        "model": "claude-demo",
        "system": "ignored by OpenAI clients",
        "messages": [
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "Hello"},
        ],
        "max_tokens": 64,
        "stop": ["END"],
    })

    assert result["id"] == "msg_123"
    assert result["choices"] == [{
        "index": 0,
        "message": {"role": "assistant", "content": "Hi there"},
        "finish_reason": "stop",
    }]
    assert result["usage"] == {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9}
    await adapter.aclose()


@pytest.mark.asyncio
async def test_anthropic_adapter_lists_models_and_classifies_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            assert request.headers["x-api-key"] == "secret"
            return httpx.Response(200, json={"data": [{"id": "claude-a"}, {"id": "claude-b"}]})
        return httpx.Response(401, json={"error": {"message": "invalid key"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = AnthropicAdapter("https://example.test/v1/messages", "secret", client)

    assert await adapter.list_models() == ["claude-a", "claude-b"]
    with pytest.raises(ProviderError) as error:
        await adapter.complete({"model": "claude-a", "messages": []})
    assert error.value.kind == "authentication_error"
    await adapter.aclose()


@pytest.mark.asyncio
async def test_anthropic_adapter_translates_text_stream_and_ends_with_done():
    body = b"".join([
        b'event: message_start\ndata: {"type":"message_start","message":{"id":"msg_1","model":"claude-demo","usage":{"input_tokens":3}}}\n\n',
        b'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello"}}\n\n',
        b'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":1}}\n\n',
        b'event: message_stop\ndata: {"type":"message_stop"}\n\n',
    ])
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    )
    adapter = AnthropicAdapter("https://example.test/v1/messages", "secret", client)

    chunks = [chunk async for chunk in adapter.stream({"model": "claude-demo", "messages": [], "stream": True})]
    text = b"".join(chunks).decode()

    assert '"content":"Hello"' in text
    assert '"finish_reason":"stop"' in text
    assert "data: [DONE]" in text
    events = [
        json.loads(line[6:])
        for line in text.splitlines()
        if line.startswith("data: {")
    ]
    assert {event["id"] for event in events} == {"msg_1"}
    assert {event["model"] for event in events} == {"claude-demo"}
    assert events[-1]["usage"] == {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4}
    await adapter.aclose()


def test_anthropic_messages_endpoint_accepts_base_url_with_or_without_v1():
    from freellm_gateway.adapters.anthropic import anthropic_messages_endpoint

    assert anthropic_messages_endpoint("https://api.anthropic.com") == "https://api.anthropic.com/v1/messages"
    assert anthropic_messages_endpoint("https://api.anthropic.com/v1") == "https://api.anthropic.com/v1/messages"
