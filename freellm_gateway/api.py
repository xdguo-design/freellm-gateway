from dataclasses import replace
from secrets import token_urlsafe
import sqlite3
from urllib.parse import urlparse
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.responses import HTMLResponse
from pathlib import Path

from .adapters.base import ProviderError
from .discovery import discover_new_routes
from .models import Provider
from .repository import Repository
from .runtime import build_gateway
from .runtime import adapter_for_route
from .service import ModelGateway


def create_app(
    gateway: ModelGateway | None = None,
    repository: Repository | None = None,
    secrets=None,
    api_token: str | None = None,
    admin_token: str | None = None,
) -> FastAPI:
    api_token = api_token or token_urlsafe(32)
    admin_token = admin_token or token_urlsafe(32)
    if repository:
        repository.initialize()
    if gateway is None and repository is not None:
        gateway = build_gateway(repository, secrets) if secrets is not None else ModelGateway(repository.list_routes(), {})
    gateway = gateway or ModelGateway([], {})
    app = FastAPI(title="FreeLLM Gateway")
    app.state.gateway = gateway
    app.state.repository = repository
    app.state.secrets = secrets

    def require_token(
        authorization: Annotated[str | None, Header()] = None,
        expected: str = api_token,
    ) -> None:
        if authorization != f"Bearer {expected}":
            raise HTTPException(status_code=401, detail="invalid bearer token")

    def require_admin(authorization: str | None) -> None:
        if authorization != f"Bearer {admin_token}":
            raise HTTPException(status_code=401, detail="invalid admin token")

    def route_json(route):
        return {
            "id": route.id,
            "provider_id": route.provider_id,
            "remote_model": route.remote_model,
            "display_name": route.display_name,
            "priority": route.priority,
            "capabilities": sorted(route.capabilities),
            "enabled": route.enabled,
            "health": route.health.value,
            "public_url": route.public_url,
            "public_docs_url": route.public_docs_url,
            "free_summary": route.free_summary,
            "catalog_status": route.catalog_status,
        }

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/admin", response_class=HTMLResponse)
    def admin_page():
        # The browser must be able to load the shell before JavaScript can
        # prompt for the admin token. The data and mutation endpoints below
        # remain protected by require_admin.
        template = Path(__file__).with_name("templates").joinpath("admin.html")
        return HTMLResponse(template.read_text(encoding="utf-8"))

    @app.get("/v1/models")
    def list_models(authorization: Annotated[str | None, Header()] = None) -> dict:
        require_token(authorization)
        data = [
            {
                "id": route.id,
                "object": "model",
                "owned_by": route.provider_id,
                "display_name": route.display_name or route.remote_model,
            }
            for route in gateway.routes
            if route.enabled
        ]
        data.insert(0, {"id": "auto", "object": "model", "owned_by": "freellm-gateway"})
        return {"object": "list", "data": data}

    @app.post("/v1/chat/completions")
    async def chat_completions(payload: dict, authorization: Annotated[str | None, Header()] = None):
        require_token(authorization)
        if payload.get("stream"):
            return StreamingResponse(gateway.stream(payload), media_type="text/event-stream")
        try:
            return await gateway.complete(payload)
        except ProviderError as error:
            raise HTTPException(status_code=error.status_code, detail=error.kind) from error

    @app.post("/v1/images/generations")
    async def image_generations(payload: dict, authorization: Annotated[str | None, Header()] = None):
        require_token(authorization)
        payload = {**payload, "task": "image_generation"}
        try:
            return await gateway.complete(payload, capability="image_generation")
        except ProviderError as error:
            raise HTTPException(status_code=error.status_code, detail=error.kind) from error

    @app.get("/api/admin/routes")
    def admin_list_routes(authorization: Annotated[str | None, Header()] = None):
        require_admin(authorization)
        return {"data": [route_json(route) for route in gateway.routes]}

    @app.get("/api/admin/providers")
    def admin_list_providers(authorization: Annotated[str | None, Header()] = None):
        require_admin(authorization)
        providers = repository.list_providers() if repository else []
        return {"data": [provider.__dict__ for provider in providers]}

    @app.post("/api/admin/providers", status_code=201)
    def admin_create_provider(payload: dict, authorization: Annotated[str | None, Header()] = None):
        require_admin(authorization)
        if repository is None:
            raise HTTPException(status_code=503, detail="persistence is not configured")
        required = ("id", "name", "protocol", "base_url", "official_url")
        if any(not isinstance(payload.get(field), str) or not payload[field] for field in required):
            raise HTTPException(status_code=422, detail="provider fields are required")
        provider = Provider(*(payload[field] for field in required))
        _require_public_url(provider.base_url, "base_url")
        _require_public_url(provider.official_url, "official_url")
        repository.save_provider(provider)
        return provider.__dict__

    @app.post("/api/admin/providers/{provider_id}/discover")
    async def admin_discover_provider(provider_id: str, authorization: Annotated[str | None, Header()] = None):
        require_admin(authorization)
        if repository is None:
            raise HTTPException(status_code=503, detail="persistence is not configured")
        provider = next((item for item in repository.list_providers() if item.id == provider_id), None)
        if provider is None:
            raise HTTPException(status_code=404, detail="provider not found")
        adapter = next((gateway.adapters.get(route.id) for route in gateway.routes if route.provider_id == provider_id), None)
        if adapter is None or not hasattr(adapter, "list_models"):
            raise HTTPException(status_code=501, detail="provider model discovery is not supported")
        new_routes = await discover_new_routes(provider, adapter, gateway.routes)
        for route in new_routes:
            repository.save_route(route)
            gateway.add_route(route)
        return {"data": [route_json(route) for route in new_routes]}

    @app.post("/api/admin/routes", status_code=201)
    def admin_create_route(payload: dict, authorization: Annotated[str | None, Header()] = None):
        require_admin(authorization)
        required = ("id", "provider_id", "remote_model")
        if any(not isinstance(payload.get(field), str) or not payload[field] for field in required):
            raise HTTPException(status_code=422, detail="id, provider_id and remote_model are required")
        if any(route.id == payload["id"] for route in gateway.routes):
            raise HTTPException(status_code=409, detail="route already exists")
        route = _route_from_payload(payload, priority=len(gateway.routes) + 1)
        if repository and not any(provider.id == route.provider_id for provider in repository.list_providers()):
            raise HTTPException(status_code=422, detail="provider must exist before adding a route")
        if route.endpoint:
            _require_public_url(route.endpoint, "endpoint")
        if route.public_url:
            _require_public_url(route.public_url, "public_url")
        if route.public_docs_url:
            _require_public_url(route.public_docs_url, "public_docs_url")
        credential = payload.get("credential")
        if credential is not None:
            if not isinstance(credential, str) or not credential:
                raise HTTPException(status_code=422, detail="credential must be a non-empty string")
            if app.state.secrets is None:
                raise HTTPException(status_code=503, detail="secret storage is not configured")
            route = replace(route, credential_ref=app.state.secrets.save(route.id, credential))
        if repository:
            try:
                repository.save_route(route)
            except sqlite3.IntegrityError as error:
                raise HTTPException(status_code=422, detail="provider must exist before adding a route") from error
        adapter = None
        if repository and app.state.secrets:
            provider = next(provider for provider in repository.list_providers() if provider.id == route.provider_id)
            adapter = adapter_for_route(route, provider, app.state.secrets)
        gateway.add_route(route, adapter)
        return route_json(route)

    @app.post("/api/admin/routes/reorder")
    def admin_reorder_routes(payload: dict, authorization: Annotated[str | None, Header()] = None):
        require_admin(authorization)
        ids = payload.get("ids")
        current = {route.id: route for route in gateway.routes}
        if not isinstance(ids, list) or set(ids) != set(current) or len(ids) != len(current):
            raise HTTPException(status_code=422, detail="ids must contain every route exactly once")
        gateway.routes = [replace(current[route_id], priority=index) for index, route_id in enumerate(ids, 1)]
        if repository:
            for route in gateway.routes:
                repository.save_route(route)
        return {"data": [route_json(route) for route in gateway.routes]}

    app.state.admin_token = admin_token
    return app


def _route_from_payload(payload: dict, priority: int):
    from .models import ModelRoute

    return ModelRoute(
        id=payload["id"],
        provider_id=payload["provider_id"],
        remote_model=payload["remote_model"],
        priority=int(payload.get("priority", priority)),
        capabilities=frozenset(payload.get("capabilities", ["chat"])),
        display_name=payload.get("display_name"),
        public_url=payload.get("public_url"),
        public_docs_url=payload.get("public_docs_url"),
        free_summary=payload.get("free_summary"),
        catalog_status=payload.get("catalog_status", "draft"),
    )


def _require_public_url(value: str, field: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail=f"{field} must be an https URL without credentials")
