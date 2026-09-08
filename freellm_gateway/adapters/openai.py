import httpx
from collections.abc import AsyncIterator

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
            raise ProviderError(
                _classify_error(response), response.status_code, response.text, response.status_code != 401
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
                    raise ProviderError(
                        _classify_error(response), response.status_code, response.text, response.status_code != 401
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
            raise ProviderError(_classify_error(response), response.status_code, response.text, response.status_code != 401)
        data = response.json().get("data", [])
        return [item["id"] for item in data if isinstance(item, dict) and isinstance(item.get("id"), str)]

    async def aclose(self) -> None:
        await self.client.aclose()


def _classify_error(response: httpx.Response) -> str:
    body = response.text.lower()
    if response.status_code == 429:
        if any(word in body for word in ("quota", "insufficient", "exhaust")):
            return "quota_exhausted"
        return "rate_limited"
    if response.status_code in {401, 403}:
        return "authentication_error"
    if response.status_code >= 500:
        return "server_error"
    return "request_error"
