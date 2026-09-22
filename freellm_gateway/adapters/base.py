from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..contracts import ChatChunk, ChatRequest, ChatResponse, ModelInfo


@dataclass
class ProviderError(Exception):
    kind: str
    status_code: int
    detail: str = ""
    retriable: bool = True
    retry_after: float | None = None

    def __str__(self) -> str:
        return self.detail or self.kind


@runtime_checkable
class ProviderAdapter(Protocol):
    """Native provider contract used by the gateway core.

    Adapters translate between these normalized types and each provider's
    native wire protocol. Compatibility methods such as ``complete`` may
    remain during migration, but new provider implementations should target
    this interface.
    """

    provider_id: str
    capabilities: frozenset[str]

    async def chat(self, request: ChatRequest) -> ChatResponse:
        ...

    def stream_chat(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        ...

    async def models(self) -> list[ModelInfo]:
        ...

    async def aclose(self) -> None:
        ...
