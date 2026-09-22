from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .models import ModelRoute


CAPABILITY_ALIASES: dict[str, frozenset[str]] = {
    "chat": frozenset({"chat"}),
    "vision": frozenset({"vision"}),
    "image_generation": frozenset({"image_generation"}),
    "embedding": frozenset({"embedding"}),
    "audio": frozenset({"audio"}),
    "function_calling": frozenset({"function_calling", "tools"}),
    "json_mode": frozenset({"json_mode", "json"}),
    "streaming": frozenset({"streaming", "stream"}),
    "long_context": frozenset({"long_context"}),
}


@dataclass(frozen=True)
class ModelProfile:
    id: str
    provider_id: str
    remote_model: str
    display_name: str
    declared_capabilities: frozenset[str]
    priority: int
    enabled: bool
    health: str
    context_window: int | None
    max_output_tokens: int | None
    input_price_per_million: float | None
    output_price_per_million: float | None
    pricing_currency: str

    @classmethod
    def from_route(cls, route: ModelRoute) -> "ModelProfile":
        return cls(
            id=route.id,
            provider_id=route.provider_id,
            remote_model=route.remote_model,
            display_name=route.display_name or route.remote_model,
            declared_capabilities=route.capabilities,
            priority=route.priority,
            enabled=route.enabled,
            health=route.health.value,
            context_window=route.context_window,
            max_output_tokens=route.max_output_tokens,
            input_price_per_million=route.input_price_per_million,
            output_price_per_million=route.output_price_per_million,
            pricing_currency=route.pricing_currency,
        )

    def supports(self, capability: str) -> bool:
        accepted = CAPABILITY_ALIASES.get(capability, frozenset({capability}))
        return bool(self.declared_capabilities.intersection(accepted))

    def capability_matrix(self) -> dict[str, bool]:
        return {name: self.supports(name) for name in CAPABILITY_ALIASES}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "provider_id": self.provider_id,
            "remote_model": self.remote_model,
            "display_name": self.display_name,
            "priority": self.priority,
            "enabled": self.enabled,
            "health": self.health,
            "capabilities": {
                "declared": sorted(self.declared_capabilities),
                "matrix": self.capability_matrix(),
            },
            "limits": {
                "context_window": self.context_window,
                "max_output_tokens": self.max_output_tokens,
            },
            "pricing": {
                "currency": self.pricing_currency,
                "input_per_million": self.input_price_per_million,
                "output_per_million": self.output_price_per_million,
            },
        }


class ModelRegistry:
    """Runtime index over persisted model routes for routing strategies."""

    def __init__(self, routes: Sequence[ModelRoute] = ()):
        self._routes: dict[str, ModelRoute] = {}
        self.replace_all(routes)

    def replace_all(self, routes: Sequence[ModelRoute]) -> None:
        self._routes = {route.id: route for route in routes}

    def register(self, route: ModelRoute) -> None:
        if route.id in self._routes:
            raise ValueError(f"model already registered: {route.id}")
        self._routes[route.id] = route

    def replace(self, route: ModelRoute) -> None:
        if route.id not in self._routes:
            raise KeyError(route.id)
        self._routes[route.id] = route

    def remove(self, route_id: str) -> None:
        if route_id not in self._routes:
            raise KeyError(route_id)
        del self._routes[route_id]

    def get(self, route_id: str) -> ModelRoute:
        try:
            return self._routes[route_id]
        except KeyError as error:
            raise KeyError(route_id) from error

    def list(self, *, include_disabled: bool = True) -> list[ModelRoute]:
        routes = list(self._routes.values())
        if not include_disabled:
            routes = [route for route in routes if route.enabled]
        return sorted(routes, key=lambda route: (route.priority, route.id))

    def profile(self, route_id: str) -> ModelProfile:
        return ModelProfile.from_route(self.get(route_id))

    def profiles(self, *, include_disabled: bool = True) -> list[ModelProfile]:
        return [ModelProfile.from_route(route) for route in self.list(include_disabled=include_disabled)]

    def find(
        self,
        *,
        required_capabilities: Iterable[str] = (),
        provider_id: str | None = None,
        min_context_window: int | None = None,
        include_disabled: bool = False,
    ) -> list[ModelRoute]:
        required = tuple(required_capabilities)
        matches: list[ModelRoute] = []
        for route in self.list(include_disabled=include_disabled):
            profile = ModelProfile.from_route(route)
            if provider_id is not None and route.provider_id != provider_id:
                continue
            if any(not profile.supports(capability) for capability in required):
                continue
            if min_context_window is not None and (
                route.context_window is None or route.context_window < min_context_window
            ):
                continue
            matches.append(route)
        return matches
