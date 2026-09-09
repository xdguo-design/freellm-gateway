import httpx
from collections.abc import AsyncIterator

from ..failures import classify_failure, parse_retry_after
from .base import ProviderError


class OpenAICompatibleAdapter:
    def __init__(self, endpoint: str, api_key: str, client: httpx.AsyncClient | None = None):
        self.endpoint = endpoint
        self.api_key = api_key
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))

    async def complete(self, payload: dict) -> dict:
        try:
            response = await self.client.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", 504, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("network_error", 502, str(exc)) from exc

        if response.is_error:
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
        return response.json()

    async def stream(self, payload: dict) -> AsyncIterator[bytes]:
        try:
            async with self.client.stream(
                "POST",
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            ) as response:
                if response.is_error:
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
                async for line in response.aiter_lines():
                    if line:
                        yield (line + "\n").encode("utf-8")
        except ProviderError:
            raise
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", 504, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("network_error", 502, str(exc)) from exc

    async def list_models(self) -> list[str]:
        models_endpoint = self.endpoint.rsplit("/chat/completions", 1)[0] + "/models"
        try:
            response = await self.client.get(
                models_endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", 504, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("network_error", 502, str(exc)) from exc
        if response.is_error:
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
        data = response.json().get("data", [])
        return [item["id"] for item in data if isinstance(item, dict) and isinstance(item.get("id"), str)]

    async def aclose(self) -> None:
        await self.client.aclose()
