import base64
import json
import time
from collections.abc import AsyncIterator
from urllib.parse import quote, unquote

import httpx

from ..failures import classify_failure, parse_retry_after
from .base import ProviderError


class GeminiAdapter:
    """Translate the gateway's OpenAI-shaped contract to Gemini REST."""

    def __init__(self, base_url: str, api_key: str, client: httpx.AsyncClient | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))

    def _headers(self) -> dict[str, str]:
        return {
            "x-goog-api-key": self.api_key,
            "content-type": "application/json",
        }

    async def complete(self, payload: dict) -> dict:
        endpoint = gemini_generate_endpoint(self.base_url, payload.get("model", ""))
        try:
            response = await self.client.post(
                endpoint,
                headers=self._headers(),
                json=to_gemini_request(payload),
            )
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", 504, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("network_error", 502, str(exc)) from exc
        _raise_for_error(response)
        try:
            return from_gemini_response(response.json(), payload.get("model", ""))
        except (TypeError, ValueError, KeyError) as exc:
            raise ProviderError("provider_protocol_error", 502, str(exc), retriable=False) from exc

    async def stream(self, payload: dict) -> AsyncIterator[bytes]:
        requested_model = payload.get("model", "")
        state = {"id": "", "model": requested_model, "role_emitted": False}
        try:
            async with self.client.stream(
                "POST",
                gemini_generate_endpoint(self.base_url, requested_model, streaming=True),
                headers=self._headers(),
                json=to_gemini_request(payload),
            ) as response:
                if response.is_error:
                    await response.aread()
                    _raise_for_error(response)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data:
                        continue
                    try:
                        event = json.loads(data)
                    except (TypeError, ValueError) as exc:
                        raise ProviderError(
                            "provider_protocol_error",
                            502,
                            f"invalid Gemini SSE event: {exc}",
                            retriable=False,
                        ) from exc
                    if not isinstance(event, dict):
                        raise ProviderError(
                            "provider_protocol_error",
                            502,
                            "Gemini SSE event must be an object",
                            retriable=False,
                        )
                    for chunk in openai_stream_chunks(event, requested_model, state):
                        yield _sse(chunk)
                if not state.get("role_emitted"):
                    raise ProviderError(
                        "empty_output", 502, "Gemini returned an empty stream", retriable=False
                    )
                yield b"data: [DONE]\n\n"
        except ProviderError:
            raise
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", 504, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("network_error", 502, str(exc)) from exc

    async def list_models(self) -> list[str]:
        result = []
        page_token = None
        seen_tokens = set()
        while True:
            params = {"pageToken": page_token} if page_token else None
            try:
                response = await self.client.get(
                    f"{self.base_url}/models",
                    headers=self._headers(),
                    params=params,
                )
            except httpx.TimeoutException as exc:
                raise ProviderError("timeout", 504, str(exc)) from exc
            except httpx.HTTPError as exc:
                raise ProviderError("network_error", 502, str(exc)) from exc
            _raise_for_error(response)
            try:
                body = response.json()
                models = body.get("models", [])
                next_page_token = body.get("nextPageToken")
            except (TypeError, ValueError, AttributeError) as exc:
                raise ProviderError("provider_protocol_error", 502, str(exc), retriable=False) from exc
            if not isinstance(models, list):
                raise ProviderError(
                    "provider_protocol_error", 502, "Gemini models response must contain a list", retriable=False
                )
            for model in models:
                if not isinstance(model, dict):
                    continue
                methods = model.get("supportedGenerationMethods") or model.get("supported_generation_methods") or []
                model_id = model.get("baseModelId") or model.get("base_model_id")
                if isinstance(methods, list) and "generateContent" in methods and isinstance(model_id, str) and model_id:
                    normalized_id = model_id.removeprefix("models/")
                    if normalized_id not in result:
                        result.append(normalized_id)
            if not isinstance(next_page_token, str) or not next_page_token:
                return result
            if next_page_token in seen_tokens:
                raise ProviderError(
                    "provider_protocol_error", 502, "Gemini models pagination repeated a page token", retriable=False
                )
            seen_tokens.add(next_page_token)
            page_token = next_page_token

    async def aclose(self) -> None:
        await self.client.aclose()


def gemini_generate_endpoint(base_url: str, model: str, streaming: bool = False) -> str:
    base = base_url.rstrip("/")
    model_name = str(model).removeprefix("models/")
    method = "streamGenerateContent" if streaming else "generateContent"
    endpoint = f"{base}/models/{quote(model_name, safe='-_.~')}:{method}"
    return endpoint + ("?alt=sse" if streaming else "")


def to_gemini_request(payload: dict) -> dict:
    contents: list[dict] = []
    system_parts: list[dict] = []
    for message in payload.get("messages", []):
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        parts = _content_parts(message.get("content", ""))
        if role == "system":
            system_parts.extend(parts)
        elif role in {"user", "assistant"} and parts:
            gemini_role = "model" if role == "assistant" else "user"
            if contents and contents[-1]["role"] == gemini_role:
                contents[-1]["parts"].extend(parts)
            else:
                contents.append({"role": gemini_role, "parts": parts})

    request: dict = {"contents": contents}
    if system_parts:
        request["systemInstruction"] = {"parts": system_parts}

    generation_config: dict = {}
    for source, target in (("temperature", "temperature"), ("top_p", "topP")):
        if source in payload:
            generation_config[target] = payload[source]
    max_tokens = payload.get("max_tokens", payload.get("max_completion_tokens"))
    if max_tokens is not None:
        generation_config["maxOutputTokens"] = max_tokens
    if "stop" in payload:
        stop = payload["stop"]
        generation_config["stopSequences"] = stop if isinstance(stop, list) else [stop]
    if generation_config:
        request["generationConfig"] = generation_config
    return request


def _content_parts(content: object) -> list[dict]:
    if isinstance(content, str):
        return [{"text": content}]
    if not isinstance(content, list):
        return []
    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append({"text": block["text"]})
        elif block.get("type") == "image_url":
            image = block.get("image_url") or {}
            if isinstance(image, dict):
                inline_data = _inline_image_data(image.get("url"))
                if inline_data:
                    parts.append({"inlineData": inline_data})
    return parts


def _inline_image_data(url: object) -> dict | None:
    if not isinstance(url, str) or not url.startswith("data:"):
        return None
    header, _, data = url.partition(",")
    mime_type = header[5:].split(";", 1)[0] or "application/octet-stream"
    if ";base64" not in header:
        data = base64.b64encode(unquote(data).encode("utf-8")).decode("ascii")
    return {"mimeType": mime_type, "data": data}


def from_gemini_response(response: dict, requested_model: str) -> dict:
    if not isinstance(response, dict):
        raise ValueError("Gemini completion response must be an object")
    candidates = response.get("candidates") or []
    if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
        raise ValueError("Gemini completion response must contain a candidate")
    candidate = candidates[0]
    content = candidate.get("content")
    if not isinstance(content, dict):
        raise ValueError("Gemini candidate must contain content")
    parts = content.get("parts")
    if not isinstance(parts, list):
        raise ValueError("Gemini candidate content must contain parts")
    text = "".join(
        part.get("text", "")
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    )
    usage = response.get("usageMetadata") or response.get("usage_metadata") or {}
    result = {
        "id": response.get("responseId", ""),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": response.get("modelVersion") or response.get("model") or requested_model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": _finish_reason(candidate.get("finishReason")),
        }],
    }
    usage_result = _usage(usage)
    if usage_result:
        result["usage"] = usage_result
    return result


def _usage(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    prompt = value.get("promptTokenCount", value.get("prompt_token_count"))
    completion = value.get("candidatesTokenCount", value.get("candidates_token_count"))
    total = value.get("totalTokenCount", value.get("total_token_count"))
    result = {}
    if isinstance(prompt, int):
        result["prompt_tokens"] = prompt
    if isinstance(completion, int):
        result["completion_tokens"] = completion
    if isinstance(total, int):
        result["total_tokens"] = total
    return result or None


def _finish_reason(value: object) -> str | None:
    return {
        "STOP": "stop",
        "MAX_TOKENS": "length",
        "SAFETY": "content_filter",
        "RECITATION": "content_filter",
        "MALFORMED_FUNCTION_CALL": "tool_calls",
    }.get(value)


def openai_stream_chunks(event: dict, requested_model: str, state: dict) -> list[dict]:
    if not isinstance(event, dict):
        return []
    state["id"] = event.get("responseId") or state.get("id", "")
    state["model"] = event.get("modelVersion") or state.get("model") or requested_model
    candidates = event.get("candidates") or []
    candidate = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
    content = candidate.get("content") or {}
    parts = content.get("parts") or []
    text = "".join(
        part.get("text", "")
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    )
    chunks = []
    if not state.get("role_emitted") and (candidate or state.get("id")):
        chunks.append({
            "id": state.get("id", ""),
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": state.get("model", requested_model),
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
        })
        state["role_emitted"] = True
    usage = _usage(event.get("usageMetadata") or event.get("usage_metadata"))
    finish_reason = _finish_reason(candidate.get("finishReason"))
    if text or finish_reason or usage:
        delta = {"content": text} if text else {}
        chunk = {
            "id": state.get("id", ""),
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": state.get("model", requested_model),
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }
        if usage:
            chunk["usage"] = usage
        chunks.append(chunk)
    return chunks


def _sse(payload: dict) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n".encode("utf-8")


def _raise_for_error(response: httpx.Response) -> None:
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
