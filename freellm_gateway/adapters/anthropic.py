import base64
import json
import time
from collections.abc import AsyncIterator
from urllib.parse import unquote, urlparse

import httpx

from ..failures import classify_failure, parse_retry_after
from .base import ProviderError


class AnthropicAdapter:
    """Translate the gateway's OpenAI-shaped contract to Anthropic Messages."""

    def __init__(self, endpoint: str, api_key: str, client: httpx.AsyncClient | None = None):
        self.endpoint = endpoint
        self.api_key = api_key
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))

    def _headers(self, stream: bool = False) -> dict[str, str]:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        if stream:
            headers["accept"] = "text/event-stream"
        return headers

    async def complete(self, payload: dict) -> dict:
        try:
            response = await self.client.post(
                self.endpoint,
                headers=self._headers(),
                json=to_anthropic_request(payload),
            )
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", 504, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("network_error", 502, str(exc)) from exc
        self._raise_for_error(response)
        try:
            return from_anthropic_response(response.json())
        except (TypeError, ValueError, KeyError) as exc:
            raise ProviderError("provider_protocol_error", 502, str(exc), retriable=False) from exc

    async def stream(self, payload: dict) -> AsyncIterator[bytes]:
        emitted_done = False
        stream_state = {"id": "", "model": payload.get("model", ""), "input_tokens": None}
        try:
            async with self.client.stream(
                "POST",
                self.endpoint,
                headers=self._headers(stream=True),
                json=to_anthropic_request(payload),
            ) as response:
                if response.is_error:
                    await response.aread()
                    self._raise_for_error(response)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data:
                        continue
                    try:
                        event = json.loads(data)
                    except (TypeError, ValueError):
                        continue
                    chunk = openai_stream_chunk(event, payload.get("model", ""), stream_state)
                    if chunk is not None:
                        yield _sse(chunk)
                    if event.get("type") == "message_stop":
                        emitted_done = True
                        yield b"data: [DONE]\n\n"
                if not emitted_done:
                    yield b"data: [DONE]\n\n"
        except ProviderError:
            raise
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", 504, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("network_error", 502, str(exc)) from exc

    async def list_models(self) -> list[str]:
        models_endpoint = self.endpoint.rsplit("/messages", 1)[0] + "/models"
        try:
            response = await self.client.get(models_endpoint, headers=self._headers())
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", 504, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("network_error", 502, str(exc)) from exc
        self._raise_for_error(response)
        data = response.json().get("data", [])
        return [item["id"] for item in data if isinstance(item, dict) and isinstance(item.get("id"), str)]

    def _raise_for_error(self, response: httpx.Response) -> None:
        if not response.is_error:
            return
        failure = classify_failure(
            status_code=response.status_code,
            message=response.text,
            retry_after=parse_retry_after(response.headers.get("retry-after")),
        )
        raise ProviderError(
            failure.type,
            response.status_code,
            response.text,
            retriable=failure.retryable,
            retry_after=failure.retry_after,
        )

    async def aclose(self) -> None:
        await self.client.aclose()


def to_anthropic_request(payload: dict) -> dict:
    messages = []
    system_parts = []
    for message in payload.get("messages", []):
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content", "")
        if role == "system":
            system_parts.append(_content_to_text(content))
        elif role in {"user", "assistant"}:
            messages.append({"role": role, "content": _content_blocks(content)})

    request = {
        "model": payload.get("model", ""),
        "max_tokens": payload.get("max_tokens", payload.get("max_completion_tokens", 1024)),
        "messages": messages,
    }
    if system_parts:
        request["system"] = "\n\n".join(part for part in system_parts if part)
    for source, target in (("temperature", "temperature"), ("top_p", "top_p"), ("stream", "stream")):
        if source in payload:
            request[target] = payload[source]
    if "stop" in payload:
        request["stop_sequences"] = payload["stop"] if isinstance(payload["stop"], list) else [payload["stop"]]
    return request


def anthropic_messages_endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base + "/messages" if base.endswith("/v1") else base + "/v1/messages"


def _content_to_text(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(
        block.get("text", "")
        for block in (content if isinstance(content, list) else [])
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    )


def _content_blocks(content):
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    blocks = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            blocks.append({"type": "text", "text": block.get("text", "")})
        elif block.get("type") == "image_url":
            image = block.get("image_url") or {}
            source = _image_source(image.get("url")) if isinstance(image, dict) else None
            if source:
                blocks.append({"type": "image", "source": source})
    return blocks


def _image_source(url: object) -> dict | None:
    if not isinstance(url, str):
        return None
    if url.startswith("data:"):
        header, _, data = url.partition(",")
        media_type = header[5:].split(";", 1)[0] or "application/octet-stream"
        if ";base64" in header:
            return {"type": "base64", "media_type": media_type, "data": data}
        return {"type": "base64", "media_type": media_type, "data": base64.b64encode(unquote(data).encode()).decode()}
    if urlparse(url).scheme in {"http", "https"}:
        return {"type": "url", "url": url}
    return None


def from_anthropic_response(response: dict) -> dict:
    content = response.get("content") or []
    text = "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
    )
    tool_calls = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tool_calls.append({
                "id": block.get("id"),
                "type": "function",
                "function": {
                    "name": block.get("name", ""),
                    "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                },
            })
    message = {"role": "assistant", "content": text}
    if tool_calls:
        message["tool_calls"] = tool_calls
    usage = response.get("usage") or {}
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    result = {
        "id": response.get("id", ""),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": response.get("model", ""),
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": _finish_reason(response.get("stop_reason")),
        }],
    }
    if isinstance(input_tokens, int) or isinstance(output_tokens, int):
        result["usage"] = {
            "prompt_tokens": input_tokens or 0,
            "completion_tokens": output_tokens or 0,
            "total_tokens": (input_tokens or 0) + (output_tokens or 0),
        }
    return result


def openai_stream_chunk(event: dict, requested_model: str, stream_state: dict | None = None) -> dict | None:
    stream_state = stream_state if stream_state is not None else {}
    event_type = event.get("type")
    message = event.get("message") or {}
    if event_type == "message_start":
        stream_state["id"] = message.get("id") or stream_state.get("id", "")
        stream_state["model"] = message.get("model") or requested_model
        stream_state["input_tokens"] = (message.get("usage") or {}).get("input_tokens")
    model = stream_state.get("model") or message.get("model") or requested_model
    identifier = stream_state.get("id") or message.get("id") or ""
    if event_type == "message_start":
        return {
            "id": identifier,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
        }
    if event_type == "content_block_delta":
        delta = event.get("delta") or {}
        if delta.get("type") != "text_delta" or not isinstance(delta.get("text"), str):
            return None
        return {
            "id": identifier,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "delta": {"content": delta["text"]}, "finish_reason": None}],
        }
    if event_type == "message_delta":
        delta = event.get("delta") or {}
        usage = event.get("usage") or {}
        chunk = {
            "id": identifier,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": _finish_reason(delta.get("stop_reason"))}],
        }
        output_tokens = usage.get("output_tokens")
        input_tokens = stream_state.get("input_tokens")
        if isinstance(input_tokens, int) or isinstance(output_tokens, int):
            prompt_tokens = input_tokens if isinstance(input_tokens, int) else 0
            completion_tokens = output_tokens if isinstance(output_tokens, int) else 0
            chunk["usage"] = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            }
        return chunk
    return None


def _finish_reason(value: object) -> str | None:
    return {
        "end_turn": "stop",
        "stop_sequence": "stop",
        "max_tokens": "length",
        "tool_use": "tool_calls",
    }.get(value)


def _sse(payload: dict) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n".encode("utf-8")
