"""Runtime boundary for external AI gateway implementations.

FreeLLM owns governance and policy decisions. Concrete runtimes own HTTP proxying,
provider protocol translation, retries, circuit breaking, and upstream health.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class RuntimeRoute:
    id: str
    provider_id: str
    model: str
    endpoint: str | None = None
    enabled: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimePolicy:
    id: str
    routes: tuple[str, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeHealth:
    status: str
    detail: Mapping[str, Any] = field(default_factory=dict)


class GatewayBackend(ABC):
    """Control-plane contract implemented by LiteLLM/Higress/APISIX adapters."""

    @abstractmethod
    async def create_route(self, route: RuntimeRoute) -> None:
        raise NotImplementedError

    @abstractmethod
    async def update_route(self, route: RuntimeRoute) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete_route(self, route_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def apply_policy(self, policy: RuntimePolicy) -> None:
        raise NotImplementedError

    @abstractmethod
    async def query_usage(self, *, tenant_id: str | None = None, application_id: str | None = None) -> Mapping[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def health(self) -> RuntimeHealth:
        raise NotImplementedError
