import json
from collections.abc import AsyncIterator

import httpx

from ..contracts import ChatChunk, ChatRequest, ChatResponse, ModelInfo
from ..failures import classify_failure, parse_retry_after
from .base import ProviderError


class OpenAICompatibleAdapter:
    """Adapter for providers exposing the OpenAI Chat Completions wire protocol.

    The gateway-facing contract is the normalized ``ProviderAdapter`` API
    (``chat`` / ``stream_chat`` / ``models``). ``complete`` and ``stream`` are
    kept as compatibility shims while the rest of the gateway migrates away
    from raw OpenAI-shaped dictionaries.
    """

    capabilities = frozenset({"chat", "stream", "models", "embedding"})

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        client: httpx.AsyncClient | None = None,
        *,
        provider_id: str = "openai-compatible",
    ):
        self.endpoint = endpoint
        self.api_key = api_key
        self.provider_id = provider_id
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def _post_json(self, url: str, payload: dict) -> dict:
        try:
            response = await self.client.post(url, headers=self._headers, json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", 504, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("network_error", 502, str(exc)) from exc

        self._raise_for_error(response)
        try:
            value = response.json()
        except ValueError as exc:
            raise ProviderError(
                "invalid_response",
                502,
                "provider returned a non-JSON response",
                retriable=False,
            ) from exc
        if not isinstance(value, dict):
            raise ProviderError(
                "invalid_response",
                502,
                "provider returned a non-object JSON response",
                retriable=False,
            )
        return value

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

    async def chat(self, request: ChatRequest) -> ChatResponse:
        payload = await self._post_json(self.endpoint, request.to_openai_payload())
        return ChatResponse.from_openai_response(payload)

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        payload = request.to_openai_payload()
        payload["stream"] = True
        async for line in self._stream_lines(payload):
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data:
                continue
            if data == "[DONE]":
                yield ChatChunk(done=True)
                return
            try:
                event = json.loads(data)
            except json.JSONDecodeError as exc:
                raise ProviderError(
                    "invalid_response",
                    502,
                    "provider returned an invalid SSE JSON event",
                    retriable=False,
                ) from exc
            if isinstance(event, dict):
                yield ChatChunk.from_openai_event(event)

    async def models(self) -> list[ModelInfo]:
        return [
            ModelInfo(id=model_id, provider_id=self.provider_id)
            for model_id in await self.list_models()
        ]

    async def complete(self, payload: dict) -> dict:
        """Backward-compatible raw OpenAI request/response path."""
        return await self._post_json(self.endpoint, payload)

    async def _stream_lines(self, payload: dict) -> AsyncIterator[str]:
        try:
            async with self.client.stream(
                "POST",
                self.endpoint,
                headers=self._headers,
                json=payload,
            ) as response:
                self._raise_for_error(response)
                async for line in response.aiter_lines():
                    if line:
                        yield line
        except ProviderError:
            raise
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", 504, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("network_error", 502, str(exc)) from exc

    async def stream(self, payload: dict) -> AsyncIterator[bytes]:
        """Backward-compatible raw SSE path."""
        async for line in self._stream_lines(payload):
            yield (line + "\n").encode("utf-8")

    def _base_url(self) -> str:
        """Derive OpenAI-compatible API base from chat completions endpoint."""
        endpoint = self.endpoint.rstrip("/")
        if endpoint.endswith("/chat/completions"):
            return endpoint[: -len("/chat/completions")]
        if endpoint.endswith("/completions"):
            return endpoint[: -len("/completions")]
        return endpoint

    async def list_models(self) -> list[str]:
        models_endpoint = self._base_url() + "/models"
        try:
            response = await self.client.get(models_endpoint, headers=self._headers)
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", 504, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("network_error", 502, str(exc)) from exc
        self._raise_for_error(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError(
                "invalid_response",
                502,
                "provider returned a non-JSON model list",
                retriable=False,
            ) from exc
        data = payload.get("data", []) if isinstance(payload, dict) else []
        return [
            item["id"]
            for item in data
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]

    async def embed(self, payload: dict) -> dict:
        """OpenAI-compatible POST /embeddings. payload: model, input (str|list[str])."""
        return await self._post_json(self._base_url() + "/embeddings", payload)

    async def aclose(self) -> None:
        await self.client.aclose()
