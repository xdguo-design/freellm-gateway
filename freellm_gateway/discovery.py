import re

from .models import ModelRoute, Provider


async def discover_new_routes(provider: Provider, adapter, existing: list[ModelRoute]) -> list[ModelRoute]:
    remote_models = await adapter.list_models()
    known = {route.remote_model for route in existing if route.provider_id == provider.id}
    next_priority = max((route.priority for route in existing), default=0) + 1
    routes = []
    for remote_model in remote_models:
        if remote_model in known:
            continue
        routes.append(ModelRoute(
            id=_route_id(provider.id, remote_model),
            provider_id=provider.id,
            remote_model=remote_model,
            priority=next_priority,
            public_url=provider.official_url,
            catalog_status="draft",
        ))
        next_priority += 1
    return routes


def _route_id(provider_id: str, remote_model: str) -> str:
    suffix = re.sub(r"[^a-z0-9]+", "-", remote_model.lower()).strip("-") or "model"
    return f"{provider_id}-{suffix}"
