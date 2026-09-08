import time
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import replace

from .adapters.base import ProviderError
from .health import HealthState, ProbeResult, RoutePolicy, effective_status, is_eligible, record_probe
from .models import ModelRoute
from .routing import select_candidates


class ModelGateway:
    def __init__(
        self,
        routes: Sequence[ModelRoute],
        adapters: Mapping[str, object],
        policies: Mapping[str, RoutePolicy] | None = None,
    ):
        self.routes = list(routes)
        self.adapters = adapters
        self.policies = dict(policies or {})
        self.health_states = {
            route.id: HealthState(status=route.health) for route in self.routes
        }

    def route(self, route_id: str) -> ModelRoute:
        return next(route for route in self.routes if route.id == route_id)

    def add_route(self, route: ModelRoute, adapter=None) -> None:
        if any(existing.id == route.id for existing in self.routes):
            raise ValueError(f"route already exists: {route.id}")
        self.routes.append(route)
        self.health_states[route.id] = HealthState(status=route.health)
        if adapter is not None:
            self.adapters[route.id] = adapter

    def replace_route(self, route: ModelRoute, adapter=None) -> None:
        if not any(existing.id == route.id for existing in self.routes):
            raise KeyError(route.id)
        self.routes = [route if existing.id == route.id else existing for existing in self.routes]
        self.health_states.setdefault(route.id, HealthState(status=route.health))
        if adapter is not None:
            self.adapters[route.id] = adapter

    def remove_route(self, route_id: str) -> None:
        if not any(route.id == route_id for route in self.routes):
            raise KeyError(route_id)
        self.routes = [route for route in self.routes if route.id != route_id]
        self.adapters.pop(route_id, None)
        self.health_states.pop(route_id, None)

    async def probe(self, route_id: str) -> dict:
        route = self.route(route_id)
        adapter = self.adapters.get(route.id)
        if adapter is None:
            error = ProviderError("missing_adapter", 503, route.id, retriable=False)
            self._record_error(route, error)
            raise error
        started = time.monotonic()
        try:
            result = await adapter.complete({
                "model": route.remote_model,
                "messages": [{"role": "user", "content": "Reply with OK"}],
                "max_tokens": 1,
            })
        except ProviderError as error:
            self._record_error(route, error)
            raise
        elapsed = (time.monotonic() - started) * 1000
        self._record_success(route, elapsed)
        return result

    async def complete(self, payload: dict, capability: str | None = None) -> dict:
        requested_model = payload.get("model", "auto")
        capability = capability or infer_capability(payload)
        candidates = self._candidates(requested_model, capability)
        if not candidates:
            raise ProviderError("no_available_model", 503, "no eligible model route", retriable=False)

        errors: list[ProviderError] = []
        for route in candidates:
            adapter = self.adapters.get(route.id)
            if adapter is None:
                errors.append(ProviderError("missing_adapter", 500, route.id, retriable=False))
                continue
            request = dict(payload)
            request["model"] = route.remote_model
            started = time.monotonic()
            try:
                response = await adapter.complete(request)
                self._record_success(route, (time.monotonic() - started) * 1000)
                return response
            except ProviderError as error:
                self._record_error(route, error)
                errors.append(error)
        raise ProviderError("all_providers_failed", 503, "; ".join(str(error) for error in errors), retriable=False)

    async def stream(self, payload: dict) -> AsyncIterator[bytes]:
        candidates = self._candidates(payload.get("model", "auto"), infer_capability(payload))
        if not candidates:
            raise ProviderError("no_available_model", 503, "no eligible model route", retriable=False)
        errors: list[ProviderError] = []
        for route in candidates:
            adapter = self.adapters.get(route.id)
            if adapter is None or not hasattr(adapter, "stream"):
                errors.append(ProviderError("stream_not_supported", 501, route.id, retriable=False))
                continue
            request = dict(payload)
            request["model"] = route.remote_model
            emitted = False
            try:
                async for chunk in adapter.stream(request):
                    emitted = True
                    yield chunk
                self._record_success(route, 0)
                return
            except ProviderError as error:
                self._record_error(route, error)
                if emitted:
                    raise
                errors.append(error)
        raise ProviderError("all_providers_failed", 503, "; ".join(str(error) for error in errors), retriable=False)

    def _candidates(self, requested_model: str, capability: str) -> list[ModelRoute]:
        now = time.monotonic()
        eligible = [
            replace(route, health=effective_status(self.health_states[route.id], now))
            for route in self.routes
            if is_eligible(self.health_states[route.id], now)
        ]
        return select_candidates(eligible, requested_model, capability)

    def _record_success(self, route: ModelRoute, total_ms: float) -> None:
        state = self.health_states[route.id]
        self.health_states[route.id] = record_probe(
            state, ProbeResult(ok=True, total_ms=int(total_ms)), time.monotonic(), self.policies.get(route.id, RoutePolicy())
        )
        self._sync_route_health(route.id)

    def _record_error(self, route: ModelRoute, error: ProviderError) -> None:
        state = self.health_states[route.id]
        self.health_states[route.id] = record_probe(
            state, ProbeResult(ok=False, error_kind=error.kind), time.monotonic(), self.policies.get(route.id, RoutePolicy())
        )
        self._sync_route_health(route.id)

    def _sync_route_health(self, route_id: str) -> None:
        status = self.health_states[route_id].status
        self.routes = [replace(route, health=status) if route.id == route_id else route for route in self.routes]


def infer_capability(payload: dict) -> str:
    if payload.get("task") == "image_generation":
        return "image_generation"
    if _contains_image(payload.get("messages", [])):
        return "vision"
    estimated_tokens = len(str(payload.get("messages", ""))) // 4
    if estimated_tokens > 8192:
        return "long_context"
    return "chat"


def _contains_image(value) -> bool:
    if isinstance(value, dict):
        if value.get("type") in {"image_url", "input_image"}:
            return True
        return any(_contains_image(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_image(item) for item in value)
    return False
