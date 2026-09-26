from dataclasses import replace
from datetime import datetime, timezone
import json
from hashlib import sha1
from ipaddress import ip_address
import os
from secrets import token_urlsafe
import re
import sqlite3
from urllib.parse import urlparse
from typing import Annotated

import httpx

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from .adapters.anthropic import AnthropicAdapter, anthropic_messages_endpoint
from .adapters.base import ProviderError
from .adapters.gemini import GeminiAdapter
from .adapters.openai import OpenAICompatibleAdapter
from .catalog import export_catalog, sync_catalog_to_site
from .connection_log import ConnectionLogger
from .discovery import discover_new_routes
from .models import Provider, RequestIdentity, SUPPORTED_CATALOG_STATUSES, SUPPORTED_PROVIDER_PROTOCOLS
from .network_safety import UnsafeProviderTarget, validate_provider_target
from .repository import Repository
from .runtime import build_gateway
from .runtime import adapter_for_route
from .service import ModelGateway, infer_capability
from .site_catalog import fetch_public_catalog, model_offers


def _resequence_routes(
    gateway: ModelGateway,
    repository: Repository | None,
    selected_route_id: str | None = None,
    selected_priority: int | None = None,
) -> list:
    routes = list(gateway.routes)
    if selected_route_id is None:
        ordered = sorted(routes, key=lambda route: (route.priority, route.id))
    else:
        selected = next(route for route in routes if route.id == selected_route_id)
        remaining = sorted(
            (route for route in routes if route.id != selected_route_id),
            key=lambda route: (route.priority, route.id),
        )
        position = max(0, min((selected_priority or 1) - 1, len(remaining)))
        ordered = remaining[:position] + [selected] + remaining[position:]

    normalized = [replace(route, priority=index) for index, route in enumerate(ordered, 1)]
    gateway.routes = normalized
    if repository and normalized != routes:
        for route in normalized:
            repository.save_route(route)
    return normalized


def create_app(
    gateway: ModelGateway | None = None,
    repository: Repository | None = None,
    secrets=None,
    api_token: str | None = None,
    admin_token: str | None = None,
    catalog_output: str | Path | None = None,
    site_repo: str | Path | None = None,
    catalog_source: str = "https://freellm.top/data/offers.json",
    logs_path: str | Path | None = None,
) -> FastAPI:
    api_token = api_token or token_urlsafe(32)
    admin_token = admin_token or token_urlsafe(32)
    if repository:
        repository.initialize()
    if gateway is None and repository is not None:
        gateway = build_gateway(repository, secrets) if secrets is not None else ModelGateway(repository.list_routes(), {})
    gateway = gateway or ModelGateway([], {})
    if repository is not None:
        gateway.on_route_changed = repository.save_route
    _resequence_routes(gateway, repository)
    app = FastAPI(title="FreeLLM Gateway")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://tauri.localhost",
            "https://tauri.localhost",
            "tauri://localhost",
            "http://localhost",
            "http://127.0.0.1",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.state.gateway = gateway
    app.state.repository = repository
    app.state.secrets = secrets
    app.state.catalog_output = Path(catalog_output or "data/catalog-export.json")
    app.state.site_repo = Path(site_repo) if site_repo else None
    app.state.catalog_source = catalog_source
    app.state.database_path = repository.database.path if repository else None
    app.state.logs_path = Path(logs_path or os.getenv("FREELLM_GATEWAY_LOG", "data/gateway-uvicorn.log"))
    app.state.connection_log = ConnectionLogger(
        os.getenv(
            "FREELLM_GATEWAY_CONNECTION_LOG",
            str(app.state.logs_path.with_name("gateway-connections.jsonl")),
        )
    )
    admin_dist_override = os.getenv("FREELLM_GATEWAY_ADMIN_DIST")
    app.state.admin_dist = (
        Path(admin_dist_override)
        if admin_dist_override
        else Path(__file__).with_name("static").joinpath("admin")
    )
    app.state.admin_index = app.state.admin_dist.joinpath("index.html")
    admin_assets = app.state.admin_dist.joinpath("assets")
    if admin_assets.is_dir():
        app.mount(
            "/admin/assets",
            StaticFiles(directory=admin_assets),
            name="admin-assets",
        )
    def persist_connection(entry: dict) -> None:
        app.state.connection_log.append(entry)
        if repository is not None:
            repository.save_usage_from_connection(entry)

    gateway.on_connection_logged = persist_connection

    def require_token(
        authorization: Annotated[str | None, Header()] = None,
        expected: str = api_token,
    ) -> RequestIdentity:
        if authorization == f"Bearer {expected}":
            return RequestIdentity("system", "legacy-global", "global_token")
        if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="invalid bearer token")
        if repository is not None:
            application = repository.verify_application_key(authorization[7:])
            if application is not None:
                return RequestIdentity(application.tenant_id, application.id, "application_key")
        raise HTTPException(status_code=401, detail="invalid bearer token")

    def require_admin(request: Request, authorization: str | None) -> None:
        host = request.client.host if request.client else None
        if host:
            try:
                if ip_address(host).is_loopback:
                    return
            except ValueError:
                pass
        if authorization != f"Bearer {admin_token}":
            raise HTTPException(status_code=401, detail="invalid admin token")

    def route_json(route):
        provider = None
        if repository:
            provider = next((item for item in repository.list_providers() if item.id == route.provider_id), None)
        state = gateway.health_states.get(route.id)
        return {
            "id": route.id,
            "provider_id": route.provider_id,
            "provider_name": provider.name if provider else route.provider_id,
            "remote_model": route.remote_model,
            "display_name": route.display_name,
            "priority": route.priority,
            "capabilities": sorted(route.capabilities),
            "enabled": route.enabled,
            "health": route.health.value,
            "reasoning_effort": route.reasoning_effort,
            "pricing": {
                "currency": route.pricing_currency,
                "input_per_million": route.input_price_per_million,
                "output_per_million": route.output_price_per_million,
            },
            "public_url": route.public_url,
            "public_docs_url": route.public_docs_url,
            "free_summary": route.free_summary,
            "catalog_status": route.catalog_status,
            "health_detail": {
                "consecutive_failures": state.consecutive_failures if state else 0,
                "cooldown_until": state.cooldown_until if state else None,
                "last_first_token_ms": state.last_first_token_ms if state else None,
                "last_total_ms": state.last_total_ms if state else None,
                "last_error_kind": state.last_error_kind if state else None,
                "last_error_retryable": state.last_error_retryable if state else None,
                "last_is_quota": state.last_is_quota if state else False,
                "last_is_transient": state.last_is_transient if state else False,
                "last_retry_after": state.last_retry_after if state else None,
            },
        }

    async def refresh_provider_adapters(provider: Provider) -> None:
        for route in list(gateway.routes):
            if route.provider_id != provider.id:
                continue
            previous = gateway.adapters.pop(route.id, None)
            if previous is not None and hasattr(previous, "aclose"):
                await previous.aclose()
            if app.state.secrets is not None:
                adapter = adapter_for_route(route, provider, app.state.secrets)
                if adapter is not None:
                    gateway.adapters[route.id] = adapter

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    def readiness() -> dict[str, str]:
        if repository is None:
            raise HTTPException(status_code=503, detail="persistence is not configured")
        if secrets is None:
            raise HTTPException(status_code=503, detail="secret storage is not configured")
        try:
            with repository.database.connect() as connection:
                connection.execute("SELECT 1").fetchone()
        except sqlite3.Error as error:
            raise HTTPException(status_code=503, detail="database is not ready") from error
        if hasattr(secrets, "check_ready"):
            try:
                secrets.check_ready()
            except (OSError, RuntimeError) as error:
                raise HTTPException(status_code=503, detail="secret storage is not ready") from error
        return {"status": "ok", "database": "ok", "secret_storage": "ok"}

    @app.get("/")
    def service_info() -> dict:
        return {
            "service": "FreeLLM Gateway",
            "status": "ok",
            "api_base": "/v1",
            "docs_url": "/docs",
            "endpoints": {
                "models": "/v1/models",
                "chat_completions": "/v1/chat/completions",
                "image_generations": "/v1/images/generations",
            },
        }

    def legacy_admin_html() -> HTMLResponse:
        template = Path(__file__).with_name("templates").joinpath("admin.html")
        return HTMLResponse(template.read_text(encoding="utf-8"))

    @app.get("/admin/legacy", response_class=HTMLResponse)
    def legacy_admin_page():
        return legacy_admin_html()

    @app.get("/admin")
    def admin_page():
        # Keep Python-only development usable before the React bundle is built.
        # Production/release builds place the Vite output in static/admin.
        if app.state.admin_index.is_file():
            return RedirectResponse(url="/admin/", status_code=307)
        return legacy_admin_html()

    @app.get("/admin/")
    def admin_react_index():
        if app.state.admin_index.is_file():
            return FileResponse(app.state.admin_index)
        return legacy_admin_html()

    @app.get("/admin/{path:path}")
    def admin_react_route(path: str):
        if app.state.admin_index.is_file():
            return FileResponse(app.state.admin_index)
        return legacy_admin_html()

    @app.get("/api/admin/overview")
    def admin_overview(request: Request, authorization: Annotated[str | None, Header()] = None):
        require_admin(request, authorization)
        routes = gateway.routes
        return {"data": {
            "configured": len(routes),
            "enabled": sum(route.enabled for route in routes),
            "healthy": sum(route.health.value == "healthy" for route in routes),
            "capabilities": sorted({capability for route in routes for capability in route.capabilities}),
            "api_base": "/v1",
            "admin_base": "/api/admin",
            "docs_url": "/docs",
            "api_token": api_token,
            "images_url": "/v1/images/generations",
            "chat_url": "/v1/chat/completions",
            "models_url": "/v1/models",
            "health_url": "/health",
            "database_path": str(app.state.database_path) if app.state.database_path else None,
            "catalog_output_path": str(app.state.catalog_output),
            "logs_path": str(app.state.logs_path),
            "connection_log_path": str(app.state.connection_log.path),
            "providers": len(repository.list_providers()) if repository else 0,
            "disabled": sum(not route.enabled for route in routes),
        }}

    @app.get("/api/admin/health")
    def admin_health(request: Request, authorization: Annotated[str | None, Header()] = None):
        require_admin(request, authorization)
        return {"data": [route_json(route) for route in gateway.routes]}

    @app.get("/api/admin/connections")
    def admin_connections(request: Request, limit: int = 100, authorization: Annotated[str | None, Header()] = None):
        require_admin(request, authorization)
        return {"data": app.state.connection_log.read(max(1, min(limit, 500)))}

    @app.get("/api/admin/tenants")
    def admin_list_tenants(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ):
        require_admin(request, authorization)
        return {"data": [tenant.__dict__ for tenant in (repository.list_tenants() if repository else [])]}

    @app.post("/api/admin/tenants", status_code=201)
    def admin_create_tenant(
        request: Request,
        payload: dict,
        authorization: Annotated[str | None, Header()] = None,
    ):
        require_admin(request, authorization)
        if repository is None:
            raise HTTPException(status_code=503, detail="persistence is not configured")
        tenant_id = _require_identity_id(payload.get("id"), "tenant id")
        name = _require_identity_name(payload.get("name"), "tenant name")
        try:
            tenant = repository.create_tenant(tenant_id, name)
        except sqlite3.IntegrityError as error:
            raise HTTPException(status_code=409, detail="tenant already exists") from error
        return tenant.__dict__

    @app.get("/api/admin/applications")
    def admin_list_applications(
        request: Request,
        tenant_id: str | None = None,
        authorization: Annotated[str | None, Header()] = None,
    ):
        require_admin(request, authorization)
        applications = repository.list_applications(tenant_id) if repository else []
        return {"data": [application.__dict__ for application in applications]}

    @app.post("/api/admin/applications", status_code=201)
    def admin_create_application(
        request: Request,
        payload: dict,
        authorization: Annotated[str | None, Header()] = None,
    ):
        require_admin(request, authorization)
        if repository is None:
            raise HTTPException(status_code=503, detail="persistence is not configured")
        application_id = _require_identity_id(payload.get("id"), "application id")
        tenant_id = _require_identity_id(payload.get("tenant_id"), "tenant id")
        name = _require_identity_name(payload.get("name"), "application name")
        try:
            application, application_key = repository.create_application(application_id, tenant_id, name)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="tenant not found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except sqlite3.IntegrityError as error:
            raise HTTPException(status_code=409, detail="application already exists") from error
        return {"application": application.__dict__, "api_key": application_key}

    @app.get("/api/admin/quotas")
    def admin_list_quotas(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ):
        require_admin(request, authorization)
        policies = repository.list_quota_policies() if repository else []
        return {
            "data": [
                {
                    **policy.__dict__,
                    "cost_limit": (
                        None
                        if policy.cost_limit_micros is None
                        else round(policy.cost_limit_micros / 1_000_000, 6)
                    ),
                }
                for policy in policies
            ]
        }

    @app.put("/api/admin/quotas/{scope_type}/{scope_id}")
    def admin_set_quota(
        scope_type: str,
        scope_id: str,
        request: Request,
        payload: dict,
        authorization: Annotated[str | None, Header()] = None,
    ):
        require_admin(request, authorization)
        if repository is None:
            raise HTTPException(status_code=503, detail="persistence is not configured")
        if scope_type not in {"tenant", "application"}:
            raise HTTPException(status_code=422, detail="scope_type must be tenant or application")
        token_limit = _optional_nonnegative_int(payload.get("token_limit"), "token_limit")
        cost_limit = _optional_nonnegative_number(payload.get("cost_limit"), "cost_limit")
        cost_limit_micros = None if cost_limit is None else round(cost_limit * 1_000_000)
        currency = _pricing_currency(payload.get("currency", "USD"))
        warning_threshold_percent = _optional_percentage(
            payload.get("warning_threshold_percent", 80),
            "warning_threshold_percent",
        )
        try:
            policy = repository.save_quota_policy(
                scope_type,
                scope_id,
                token_limit=token_limit,
                cost_limit_micros=cost_limit_micros,
                currency=currency,
                warning_threshold_percent=warning_threshold_percent,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"{scope_type} not found") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {
            "data": {
                **policy.__dict__,
                "cost_limit": (
                    None
                    if policy.cost_limit_micros is None
                    else round(policy.cost_limit_micros / 1_000_000, 6)
                ),
            }
        }

    @app.get("/api/admin/usage")
    def admin_usage(
        request: Request,
        days: int = 7,
        tenant_id: str | None = None,
        application_id: str | None = None,
        provider_id: str | None = None,
        remote_model: str | None = None,
        authorization: Annotated[str | None, Header()] = None,
    ):
        require_admin(request, authorization)
        if repository is None:
            return {
                "data": {
                    "days": max(1, min(days, 365)),
                    "filters": {},
                    "filter_options": {
                        "tenants": [], "applications": [], "providers": [], "models": []
                    },
                    "calls": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "avg_latency_ms": 0.0,
                    "priced_calls": 0,
                    "unpriced_calls": 0,
                    "estimated_costs": [],
                    "quota_period": None,
                    "selected_quota": None,
                    "by_tenant": [],
                    "by_application": [],
                    "by_provider": [],
                    "by_model": [],
                    "by_day": [],
                }
            }
        return {
            "data": repository.usage_summary(
                days,
                tenant_id=tenant_id,
                application_id=application_id,
                provider_id=provider_id,
                remote_model=remote_model,
            )
        }

    @app.get("/v1/models")
    def list_models(authorization: Annotated[str | None, Header()] = None) -> dict:
        require_token(authorization)
        data = []
        seen_models = set()
        for route in gateway.routes:
            if not route.enabled or route.remote_model in seen_models:
                continue
            seen_models.add(route.remote_model)
            data.append({
                "id": route.remote_model,
                "object": "model",
                "owned_by": route.provider_id,
                "display_name": route.display_name or route.remote_model,
            })
        data.insert(0, {"id": "auto", "object": "model", "owned_by": "freellm-gateway"})
        return {"object": "list", "data": data}

    @app.post("/v1/chat/completions")
    async def chat_completions(
        payload: dict,
        response: Response,
        authorization: Annotated[str | None, Header()] = None,
    ):
        identity = require_token(authorization)
        usage_context = {
            "tenant_id": identity.tenant_id,
            "application_id": identity.application_id,
        }
        _require_known_model(payload.get("model", "auto"), gateway)
        capability = infer_capability(payload)
        quota_check = _quota_preflight(repository, gateway, identity, payload, capability)
        quota_headers = _quota_response_headers(quota_check)
        reservation_id = quota_check.get("reservation_id")
        if payload.get("stream"):
            async def quota_stream():
                try:
                    async for chunk in gateway.stream(payload, usage_context=usage_context):
                        yield chunk
                finally:
                    if repository is not None:
                        repository.release_quota_reservation(reservation_id)

            return StreamingResponse(
                quota_stream(),
                media_type="text/event-stream",
                headers=quota_headers,
            )
        try:
            result = await gateway.complete(
                payload,
                capability=capability,
                usage_context=usage_context,
            )
            for name, value in quota_headers.items():
                response.headers[name] = value
            return result
        except ProviderError as error:
            raise HTTPException(status_code=error.status_code, detail=error.kind) from error
        finally:
            if repository is not None:
                repository.release_quota_reservation(reservation_id)

    @app.post("/v1/images/generations")
    async def image_generations(
        payload: dict,
        response: Response,
        authorization: Annotated[str | None, Header()] = None,
    ):
        identity = require_token(authorization)
        usage_context = {
            "tenant_id": identity.tenant_id,
            "application_id": identity.application_id,
        }
        payload = {**payload, "task": "image_generation"}
        _require_known_model(payload.get("model", "auto"), gateway)
        quota_check = _quota_preflight(
            repository,
            gateway,
            identity,
            payload,
            "image_generation",
        )
        reservation_id = quota_check.get("reservation_id")
        try:
            result = await gateway.complete(
                payload,
                capability="image_generation",
                usage_context=usage_context,
            )
            for name, value in _quota_response_headers(quota_check).items():
                response.headers[name] = value
            return result
        except ProviderError as error:
            raise HTTPException(status_code=error.status_code, detail=error.kind) from error
        finally:
            if repository is not None:
                repository.release_quota_reservation(reservation_id)

    @app.get("/api/admin/routes")
    def admin_list_routes(request: Request, authorization: Annotated[str | None, Header()] = None):
        require_admin(request, authorization)
        return {"data": [route_json(route) for route in gateway.routes]}

    @app.get("/api/admin/providers")
    def admin_list_providers(request: Request, authorization: Annotated[str | None, Header()] = None):
        require_admin(request, authorization)
        providers = repository.list_providers() if repository else []
        return {"data": [provider.__dict__ for provider in providers]}

    @app.post("/api/admin/providers", status_code=201)
    async def admin_create_provider(request: Request, payload: dict, authorization: Annotated[str | None, Header()] = None):
        require_admin(request, authorization)
        if repository is None:
            raise HTTPException(status_code=503, detail="persistence is not configured")
        provider = _provider_from_payload(payload)
        repository.save_provider(provider)
        await refresh_provider_adapters(provider)
        return provider.__dict__

    @app.put("/api/admin/providers/{provider_id}")
    async def admin_update_provider(
        provider_id: str,
        request: Request,
        payload: dict,
        authorization: Annotated[str | None, Header()] = None,
    ):
        require_admin(request, authorization)
        if repository is None:
            raise HTTPException(status_code=503, detail="persistence is not configured")
        current = next((item for item in repository.list_providers() if item.id == provider_id), None)
        if current is None:
            raise HTTPException(status_code=404, detail="provider not found")
        provider = _provider_from_payload(payload)
        if provider.id != provider_id:
            raise HTTPException(status_code=422, detail="provider id cannot be changed")
        repository.save_provider(provider)
        await refresh_provider_adapters(provider)
        return provider.__dict__

    @app.delete("/api/admin/providers/{provider_id}", status_code=204)
    async def admin_delete_provider(
        provider_id: str,
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ):
        require_admin(request, authorization)
        if repository is None:
            raise HTTPException(status_code=503, detail="persistence is not configured")
        current = next((item for item in repository.list_providers() if item.id == provider_id), None)
        if current is None:
            raise HTTPException(status_code=404, detail="provider not found")
        if any(route.provider_id == provider_id for route in repository.list_routes()):
            raise HTTPException(status_code=409, detail="provider has model routes")
        repository.delete_provider(provider_id)

    @app.post("/api/admin/providers/{provider_id}/discover")
    async def admin_discover_provider(provider_id: str, request: Request, authorization: Annotated[str | None, Header()] = None):
        require_admin(request, authorization)
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
        _resequence_routes(gateway, repository)
        return {"data": [route_json(gateway.route(route.id)) for route in new_routes]}

    @app.post("/api/admin/providers/{provider_id}/models")
    async def admin_list_provider_models(
        provider_id: str,
        payload: dict,
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ):
        require_admin(request, authorization)
        if repository is None:
            raise HTTPException(status_code=503, detail="persistence is not configured")
        provider = next((item for item in repository.list_providers() if item.id == provider_id), None)
        if provider is None:
            raise HTTPException(status_code=404, detail="provider not found")
        if provider.protocol not in SUPPORTED_PROVIDER_PROTOCOLS:
            raise HTTPException(status_code=501, detail="provider model discovery is not supported")
        _require_provider_base_url(provider.base_url)
        credential = payload.get("credential")
        if not isinstance(credential, str) or not credential.strip():
            raise HTTPException(status_code=422, detail="credential must be a non-empty string")
        if provider.protocol == "openai":
            adapter = OpenAICompatibleAdapter(
                provider.base_url.rstrip("/") + "/chat/completions",
                credential.strip(),
            )
        elif provider.protocol == "anthropic":
            adapter = AnthropicAdapter(
                anthropic_messages_endpoint(provider.base_url),
                credential.strip(),
            )
        else:
            adapter = GeminiAdapter(provider.base_url, credential.strip())
        try:
            return {"data": await adapter.list_models()}
        except ProviderError as error:
            raise HTTPException(status_code=error.status_code, detail=error.kind) from error
        finally:
            await adapter.aclose()

    @app.post("/api/admin/connection/models")
    async def admin_list_unsaved_connection_models(
        payload: dict,
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ):
        require_admin(request, authorization)
        provider = _provider_from_payload(payload.get("provider"))
        credential = payload.get("credential")
        if not isinstance(credential, str) or not credential.strip():
            raise HTTPException(status_code=422, detail="credential must be a non-empty string")
        if provider.protocol == "openai":
            adapter = OpenAICompatibleAdapter(
                provider.base_url.rstrip("/") + "/chat/completions",
                credential.strip(),
            )
        elif provider.protocol == "anthropic":
            adapter = AnthropicAdapter(
                anthropic_messages_endpoint(provider.base_url),
                credential.strip(),
            )
        else:
            adapter = GeminiAdapter(provider.base_url, credential.strip())
        try:
            return {"data": await adapter.list_models()}
        except ProviderError as error:
            raise HTTPException(status_code=error.status_code, detail=error.kind) from error
        finally:
            await adapter.aclose()

    @app.patch("/api/admin/routes/{route_id}")
    def admin_update_route(route_id: str, payload: dict, request: Request, authorization: Annotated[str | None, Header()] = None):
        require_admin(request, authorization)
        try:
            current = gateway.route(route_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="route not found") from error
        updates = {}
        for field in ("provider_id", "remote_model", "display_name", "endpoint", "public_url", "public_docs_url", "free_summary", "catalog_status"):
            if field in payload:
                value = payload[field]
                if value is not None and not isinstance(value, str):
                    raise HTTPException(status_code=422, detail=f"{field} must be a string or null")
                if field == "catalog_status" and value not in SUPPORTED_CATALOG_STATUSES:
                    raise HTTPException(status_code=422, detail="catalog_status must be draft or published")
                updates[field] = value
        if "reasoning_effort" in payload:
            value = payload["reasoning_effort"]
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise HTTPException(status_code=422, detail="reasoning_effort must be a non-empty string or null")
            updates["reasoning_effort"] = value.strip() if isinstance(value, str) else None
        if "priority" in payload:
            if not isinstance(payload["priority"], int) or payload["priority"] < 1:
                raise HTTPException(status_code=422, detail="priority must be a positive integer")
            updates["priority"] = payload["priority"]
        if "enabled" in payload:
            if not isinstance(payload["enabled"], bool):
                raise HTTPException(status_code=422, detail="enabled must be boolean")
            updates["enabled"] = payload["enabled"]
        if "capabilities" in payload:
            capabilities = payload["capabilities"]
            if not isinstance(capabilities, list) or not capabilities or any(not isinstance(item, str) for item in capabilities):
                raise HTTPException(status_code=422, detail="capabilities must be a non-empty string list")
            updates["capabilities"] = frozenset(capabilities)
        for field in ("input_price_per_million", "output_price_per_million"):
            if field in payload:
                updates[field] = _optional_nonnegative_number(payload[field], field)
        if "pricing_currency" in payload:
            updates["pricing_currency"] = _pricing_currency(payload["pricing_currency"])
        provider_id = updates.get("provider_id", current.provider_id)
        if repository and not any(provider.id == provider_id for provider in repository.list_providers()):
            raise HTTPException(status_code=422, detail="provider must exist before updating a route")
        if updates.get("endpoint"):
            _require_provider_base_url(updates["endpoint"])
        for field in ("public_url", "public_docs_url"):
            if updates.get(field):
                _require_public_url(updates[field], field)
        credential = payload.get("credential")
        if credential is not None:
            if not isinstance(credential, str) or not credential:
                raise HTTPException(status_code=422, detail="credential must be a non-empty string")
            if app.state.secrets is None:
                raise HTTPException(status_code=503, detail="secret storage is not configured")
            updates["credential_ref"] = app.state.secrets.save(route_id, credential)
        updated = replace(current, **updates)
        adapter = gateway.adapters.get(route_id)
        if repository and app.state.secrets and updated.credential_ref:
            provider = next((item for item in repository.list_providers() if item.id == updated.provider_id), None)
            adapter = adapter_for_route(updated, provider, app.state.secrets)
        gateway.replace_route(updated, adapter)
        if repository:
            repository.save_route(gateway.route(route_id))
        _resequence_routes(gateway, repository, route_id, updated.priority)
        return route_json(gateway.route(route_id))

    @app.delete("/api/admin/routes/{route_id}", status_code=204)
    def admin_delete_route(route_id: str, request: Request, authorization: Annotated[str | None, Header()] = None):
        require_admin(request, authorization)
        try:
            gateway.remove_route(route_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="route not found") from error
        if repository:
            repository.delete_route(route_id)
        _resequence_routes(gateway, repository)

    @app.post("/api/admin/routes/{route_id}/probe")
    async def admin_probe_route(route_id: str, request: Request, authorization: Annotated[str | None, Header()] = None):
        require_admin(request, authorization)
        try:
            await gateway.probe(route_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="route not found") from error
        except ProviderError as error:
            if repository:
                repository.save_route(gateway.route(route_id))
            raise HTTPException(status_code=error.status_code, detail=error.kind) from error
        if repository:
            repository.save_route(gateway.route(route_id))
        return route_json(gateway.route(route_id))

    @app.post("/api/admin/routes", status_code=201)
    def admin_create_route(request: Request, payload: dict, authorization: Annotated[str | None, Header()] = None):
        require_admin(request, authorization)
        required = ("id", "provider_id", "remote_model")
        if any(not isinstance(payload.get(field), str) or not payload[field] for field in required):
            raise HTTPException(status_code=422, detail="id, provider_id and remote_model are required")
        if any(route.id == payload["id"] for route in gateway.routes):
            raise HTTPException(status_code=409, detail="route already exists")
        route = _route_from_payload(payload, priority=len(gateway.routes) + 1)
        if repository and not any(provider.id == route.provider_id for provider in repository.list_providers()):
            raise HTTPException(status_code=422, detail="provider must exist before adding a route")
        if route.endpoint:
            _require_provider_base_url(route.endpoint)
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
        _resequence_routes(gateway, repository, route.id, route.priority)
        return route_json(gateway.route(route.id))

    @app.post("/api/admin/routes/bulk")
    def admin_bulk_create_routes(request: Request, payload: dict, authorization: Annotated[str | None, Header()] = None):
        require_admin(request, authorization)
        if repository is None:
            raise HTTPException(status_code=503, detail="persistence is not configured")
        provider_payload = payload.get("provider")
        provider = _provider_from_payload(provider_payload)
        models = payload.get("models")
        if not isinstance(models, list) or not models:
            raise HTTPException(status_code=422, detail="models must be a non-empty list")
        if any(
            not isinstance(item, dict)
            or not isinstance(item.get("remote_model"), str)
            or not item["remote_model"].strip()
            for item in models
        ):
            raise HTTPException(status_code=422, detail="each model must have a non-empty remote_model")
        if any("enabled" in item and not isinstance(item["enabled"], bool) for item in models):
            raise HTTPException(status_code=422, detail="enabled must be boolean")

        existing_provider = next(
            (item for item in repository.list_providers() if item.id == provider.id),
            None,
        )
        if existing_provider and _provider_connection_key(existing_provider) != _provider_connection_key(provider):
            raise HTTPException(
                status_code=409,
                detail="provider id already belongs to another base URL",
            )
        provider = existing_provider or provider
        if existing_provider is None:
            repository.save_provider(provider)
        existing = {
            (route.provider_id, route.remote_model): route
            for route in gateway.routes
        }
        next_priority = int(payload.get("priority", len(gateway.routes) + 1))
        if next_priority < 1:
            raise HTTPException(status_code=422, detail="priority must be a positive integer")
        credential = payload.get("credential")
        if credential is not None:
            if not isinstance(credential, str) or not credential:
                raise HTTPException(status_code=422, detail="credential must be a non-empty string")
            if app.state.secrets is None:
                raise HTTPException(status_code=503, detail="secret storage is not configured")

        created = []
        skipped = []
        for item in models:
            remote_model = item["remote_model"].strip()
            if (provider.id, remote_model) in existing:
                skipped.append({"remote_model": remote_model})
                continue
            route_payload = {
                "id": _bulk_route_id(provider.id, remote_model),
                "provider_id": provider.id,
                "remote_model": remote_model,
                "priority": item.get("priority", next_priority),
                "enabled": item.get("enabled", True),
                "display_name": item.get("display_name", payload.get("display_name")),
                "public_url": item.get("public_url", payload.get("public_url")),
                "public_docs_url": item.get("public_docs_url", payload.get("public_docs_url")),
                "free_summary": item.get("free_summary", payload.get("free_summary")),
                "catalog_status": item.get("catalog_status", payload.get("catalog_status", "draft")),
                "capabilities": item.get("capabilities", payload.get("capabilities", ["chat"])),
                "reasoning_effort": item.get("reasoning_effort", payload.get("reasoning_effort")),
                "input_price_per_million": item.get(
                    "input_price_per_million", payload.get("input_price_per_million")
                ),
                "output_price_per_million": item.get(
                    "output_price_per_million", payload.get("output_price_per_million")
                ),
                "pricing_currency": item.get(
                    "pricing_currency", payload.get("pricing_currency", "USD")
                ),
            }
            route = _route_from_payload(route_payload, priority=next_priority)
            route = replace(route, enabled=route_payload["enabled"])
            if route.endpoint:
                _require_provider_base_url(route.endpoint)
            for field in ("public_url", "public_docs_url"):
                if getattr(route, field):
                    _require_public_url(getattr(route, field), field)
            if credential is not None:
                route = replace(route, credential_ref=app.state.secrets.save(route.id, credential))
            repository.save_route(route)
            provider_adapter = None
            if app.state.secrets and route.credential_ref:
                provider_adapter = adapter_for_route(route, provider, app.state.secrets)
            gateway.add_route(route, provider_adapter)
            created.append(route_json(route))
            existing[(provider.id, remote_model)] = route
            next_priority += 1
        _resequence_routes(gateway, repository)
        return {"data": {"created": [route_json(gateway.route(item["id"])) for item in created], "skipped": skipped}}

    @app.post("/api/admin/routes/bulk-connections")
    def admin_bulk_create_connection_routes(
        request: Request,
        payload: dict,
        authorization: Annotated[str | None, Header()] = None,
    ):
        require_admin(request, authorization)
        if repository is None:
            raise HTTPException(status_code=503, detail="persistence is not configured")
        connections = payload.get("connections")
        if not isinstance(connections, list) or not connections:
            raise HTTPException(status_code=422, detail="connections must be a non-empty list")

        created = []
        skipped = []
        failed = []
        providers = repository.list_providers()
        existing = {(route.provider_id, route.remote_model): route for route in gateway.routes}
        next_priority = len(gateway.routes) + 1

        for connection in connections:
            provider_payload = connection.get("provider") if isinstance(connection, dict) else None
            requested_provider_id = provider_payload.get("id") if isinstance(provider_payload, dict) else None
            requested_base_url = provider_payload.get("base_url") if isinstance(provider_payload, dict) else None
            try:
                if not isinstance(connection, dict):
                    raise HTTPException(status_code=422, detail="each connection must be an object")
                provider = _provider_from_payload(provider_payload)
                models = _validate_connection_models(connection.get("models"))
                credential = connection.get("credential")
                if credential is not None and (not isinstance(credential, str) or not credential.strip()):
                    raise HTTPException(status_code=422, detail="credential must be a non-empty string")
                if credential is not None and app.state.secrets is None:
                    raise HTTPException(status_code=503, detail="secret storage is not configured")

                connection_key = _provider_connection_key(provider)
                matched_provider = next(
                    (item for item in providers if _provider_connection_key(item) == connection_key),
                    None,
                )
                named_provider = next((item for item in providers if item.id == provider.id), None)
                if named_provider and _provider_connection_key(named_provider) != connection_key:
                    raise _ConnectionBatchError(
                        "provider_identity_conflict",
                        "provider id already belongs to another base URL",
                    )
                provider = matched_provider or provider
                if matched_provider is None:
                    repository.save_provider(provider)
                    providers.append(provider)

                connection_priority = connection.get("priority", next_priority)
                if not isinstance(connection_priority, int) or connection_priority < 1:
                    raise HTTPException(status_code=422, detail="priority must be a positive integer")
                common = {
                    "display_name": connection.get("display_name"),
                    "public_url": connection.get("public_url"),
                    "public_docs_url": connection.get("public_docs_url"),
                    "free_summary": connection.get("free_summary"),
                    "catalog_status": connection.get("catalog_status", "draft"),
                    "capabilities": connection.get("capabilities", ["chat"]),
                }
                _validate_connection_metadata(common)
                for item in models:
                    remote_model = item["remote_model"].strip()
                    if (provider.id, remote_model) in existing:
                        skipped.append({"provider_id": provider.id, "remote_model": remote_model})
                        continue
                    route_payload = {
                        "id": _bulk_route_id(provider.id, remote_model),
                        "provider_id": provider.id,
                        "remote_model": remote_model,
                        "priority": item.get("priority", connection_priority),
                        "enabled": item.get("enabled", True),
                        "display_name": item.get("display_name", common["display_name"]),
                        "public_url": item.get("public_url", common["public_url"]),
                        "public_docs_url": item.get("public_docs_url", common["public_docs_url"]),
                        "free_summary": item.get("free_summary", common["free_summary"]),
                        "catalog_status": item.get("catalog_status", common["catalog_status"]),
                        "capabilities": item.get("capabilities", common["capabilities"]),
                        "reasoning_effort": item.get("reasoning_effort", connection.get("reasoning_effort")),
                        "input_price_per_million": item.get(
                            "input_price_per_million", connection.get("input_price_per_million")
                        ),
                        "output_price_per_million": item.get(
                            "output_price_per_million", connection.get("output_price_per_million")
                        ),
                        "pricing_currency": item.get(
                            "pricing_currency", connection.get("pricing_currency", "USD")
                        ),
                    }
                    route = _route_from_payload(route_payload, priority=next_priority)
                    route = replace(route, enabled=route_payload["enabled"])
                    for field in ("public_url", "public_docs_url"):
                        if getattr(route, field):
                            _require_public_url(getattr(route, field), field)
                    if credential is not None:
                        route = replace(route, credential_ref=app.state.secrets.save(route.id, credential.strip()))
                    repository.save_route(route)
                    provider_adapter = None
                    if app.state.secrets and route.credential_ref:
                        provider_adapter = adapter_for_route(route, provider, app.state.secrets)
                    gateway.add_route(route, provider_adapter)
                    existing[(provider.id, remote_model)] = route
                    created.append(route)
                    next_priority += 1
            except _ConnectionBatchError as error:
                failed.append({
                    "provider_id": requested_provider_id,
                    "base_url": requested_base_url,
                    "error_type": error.error_type,
                    "message": error.message,
                })
            except HTTPException as error:
                failed.append({
                    "provider_id": requested_provider_id,
                    "base_url": requested_base_url,
                    "error_type": "secret_storage_unavailable" if error.status_code == 503 else "validation_error",
                    "message": "secret storage is not configured" if error.status_code == 503 else str(error.detail),
                })
            except (sqlite3.IntegrityError, ValueError) as error:
                failed.append({
                    "provider_id": requested_provider_id,
                    "base_url": requested_base_url,
                    "error_type": "persistence_error",
                    "message": str(error),
                })

        _resequence_routes(gateway, repository)
        return {"data": {"created": [route_json(gateway.route(route.id)) for route in created], "skipped": skipped, "failed": failed}}

    @app.post("/api/admin/routes/reorder")
    def admin_reorder_routes(request: Request, payload: dict, authorization: Annotated[str | None, Header()] = None):
        require_admin(request, authorization)
        ids = payload.get("ids")
        current = {route.id: route for route in gateway.routes}
        if not isinstance(ids, list) or set(ids) != set(current) or len(ids) != len(current):
            raise HTTPException(status_code=422, detail="ids must contain every route exactly once")
        gateway.routes = [replace(current[route_id], priority=index) for index, route_id in enumerate(ids, 1)]
        if repository:
            for route in gateway.routes:
                repository.save_route(route)
        return {"data": [route_json(route) for route in gateway.routes]}

    @app.post("/api/admin/catalog/export")
    def admin_export_catalog(request: Request, authorization: Annotated[str | None, Header()] = None):
        require_admin(request, authorization)
        providers = {provider.id: provider for provider in repository.list_providers()} if repository else {}
        data = export_catalog(gateway.routes, providers, app.state.catalog_output)
        return {"data": data, "path": str(app.state.catalog_output)}

    @app.post("/api/admin/catalog/sync")
    def admin_sync_catalog(request: Request, authorization: Annotated[str | None, Header()] = None):
        require_admin(request, authorization)
        if app.state.site_repo is None:
            raise HTTPException(status_code=503, detail="site repository is not configured")
        providers = {provider.id: provider for provider in repository.list_providers()} if repository else {}
        data = export_catalog(gateway.routes, providers, app.state.catalog_output)
        try:
            result = sync_catalog_to_site(data, app.state.site_repo)
        except FileNotFoundError as error:
            raise HTTPException(status_code=422, detail=f"site catalog file not found: {error}") from error
        return {"data": {"catalog": data, "sync": result}}

    @app.get("/api/admin/catalog/source")
    async def admin_source_catalog(
        request: Request,
        scope: str = "models",
        authorization: Annotated[str | None, Header()] = None,
    ):
        require_admin(request, authorization)
        try:
            offers = await fetch_public_catalog(app.state.catalog_source)
        except (ValueError, httpx.HTTPError) as error:
            raise HTTPException(status_code=502, detail=f"catalog source unavailable: {error}") from error
        data = model_offers(offers) if scope == "models" else offers
        if scope == "models":
            provider_names = {
                provider.id: provider.name
                for provider in (repository.list_providers() if repository else [])
            }
            data = [_with_pool_status(offer, gateway.routes, provider_names) for offer in data]
        return {"source": app.state.catalog_source, "scope": scope, "data": data}

    app.state.admin_token = admin_token
    return app


def _route_from_payload(payload: dict, priority: int):
    from .models import ModelRoute

    endpoint = payload.get("endpoint")
    if endpoint is not None:
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise HTTPException(status_code=422, detail="endpoint must be a non-empty string or null")
        endpoint = endpoint.strip()
        _require_provider_base_url(endpoint)

    return ModelRoute(
        id=payload["id"],
        provider_id=payload["provider_id"],
        remote_model=payload["remote_model"],
        priority=int(payload.get("priority", priority)),
        capabilities=frozenset(payload.get("capabilities", ["chat"])),
        display_name=payload.get("display_name"),
        reasoning_effort=_normalize_reasoning_effort(payload.get("reasoning_effort")),
        endpoint=endpoint,
        public_url=payload.get("public_url"),
        public_docs_url=payload.get("public_docs_url"),
        free_summary=payload.get("free_summary"),
        catalog_status=_catalog_status(payload.get("catalog_status", "draft")),
        input_price_per_million=_optional_nonnegative_number(
            payload.get("input_price_per_million"),
            "input_price_per_million",
        ),
        output_price_per_million=_optional_nonnegative_number(
            payload.get("output_price_per_million"),
            "output_price_per_million",
        ),
        pricing_currency=_pricing_currency(payload.get("pricing_currency", "USD")),
    )


def _catalog_status(value: object) -> str:
    if not isinstance(value, str) or value not in SUPPORTED_CATALOG_STATUSES:
        raise HTTPException(status_code=422, detail="catalog_status must be draft or published")
    return value


def _normalize_reasoning_effort(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=422, detail="reasoning_effort must be a non-empty string or null")
    return value.strip()


def _provider_from_payload(payload: dict | None) -> Provider:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="provider is required")
    required = ("id", "name", "protocol", "base_url", "official_url")
    if any(not isinstance(payload.get(field), str) or not payload[field].strip() for field in required):
        raise HTTPException(status_code=422, detail="provider fields are required")
    provider = Provider(*(payload[field].strip() for field in required))
    if provider.protocol not in SUPPORTED_PROVIDER_PROTOCOLS:
        raise HTTPException(status_code=422, detail="bulk import supports only openai, anthropic or gemini providers")
    _require_provider_base_url(provider.base_url)
    _require_public_url(provider.official_url, "official_url")
    return provider


class _ConnectionBatchError(Exception):
    def __init__(self, error_type: str, message: str):
        self.error_type = error_type
        self.message = message
        super().__init__(message)


def _normalize_provider_base_url(value: str) -> str:
    parsed = urlparse(value.strip())
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}"


def _provider_connection_key(provider: Provider) -> tuple[str, str]:
    return provider.protocol, _normalize_provider_base_url(provider.base_url)


def _validate_connection_models(models: object) -> list[dict]:
    if not isinstance(models, list) or not models:
        raise HTTPException(status_code=422, detail="models must be a non-empty list")
    for item in models:
        if not isinstance(item, dict) or not isinstance(item.get("remote_model"), str) or not item["remote_model"].strip():
            raise HTTPException(status_code=422, detail="each model must have a non-empty remote_model")
        if "enabled" in item and not isinstance(item["enabled"], bool):
            raise HTTPException(status_code=422, detail="enabled must be boolean")
        if "priority" in item and (not isinstance(item["priority"], int) or item["priority"] < 1):
            raise HTTPException(status_code=422, detail="priority must be a positive integer")
        if "capabilities" in item and (
            not isinstance(item["capabilities"], list)
            or not item["capabilities"]
            or any(not isinstance(value, str) for value in item["capabilities"])
        ):
            raise HTTPException(status_code=422, detail="capabilities must be a non-empty string list")
    return models


def _validate_connection_metadata(metadata: dict) -> None:
    for field in ("display_name", "public_url", "public_docs_url", "free_summary", "catalog_status"):
        value = metadata.get(field)
        if value is not None and not isinstance(value, str):
            raise HTTPException(status_code=422, detail=f"{field} must be a string or null")
    capabilities = metadata.get("capabilities")
    if (
        not isinstance(capabilities, list)
        or not capabilities
        or any(not isinstance(value, str) for value in capabilities)
    ):
        raise HTTPException(status_code=422, detail="capabilities must be a non-empty string list")


def _bulk_route_id(provider_id: str, remote_model: str) -> str:
    readable = re.sub(r"[^a-z0-9]+", "-", f"{provider_id}-{remote_model}".lower()).strip("-")
    readable = readable[:90].rstrip("-")
    digest = sha1(f"{provider_id}\0{remote_model}".encode("utf-8")).hexdigest()[:10]
    return f"{readable or 'model'}-{digest}"


def _optional_nonnegative_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HTTPException(status_code=422, detail=f"{field} must be a non-negative integer or null")
    return value


def _optional_nonnegative_number(value: object, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise HTTPException(status_code=422, detail=f"{field} must be a non-negative number or null")
    return float(value)


def _optional_percentage(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HTTPException(status_code=422, detail=f"{field} must be a number between 0 and 100")
    normalized = float(value)
    if normalized < 0 or normalized > 100:
        raise HTTPException(status_code=422, detail=f"{field} must be between 0 and 100")
    return normalized


def _estimate_request_quota_projection(
    payload: dict,
    gateway: ModelGateway,
    capability: str,
) -> dict:
    if capability == "image_generation":
        return {
            "projected_tokens": 0,
            "projected_costs": {},
            "cost_projection_complete": False,
            "token_projection_complete": True,
        }

    serialized = json.dumps(
        {key: value for key, value in payload.items() if key != "stream"},
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    input_tokens = max(1, (len(serialized) + 3) // 4)
    raw_output = payload.get("max_completion_tokens", payload.get("max_tokens"))
    output_tokens = (
        raw_output
        if isinstance(raw_output, int) and not isinstance(raw_output, bool) and raw_output >= 0
        else 0
    )
    output_complete = isinstance(raw_output, int) and not isinstance(raw_output, bool) and raw_output >= 0
    projected_tokens = input_tokens + output_tokens
    requested_model = str(payload.get("model", "auto"))
    candidates = gateway.candidates(requested_model, capability)
    projected_costs: dict[str, int] = {}
    cost_complete = bool(candidates) and output_complete

    for route in candidates:
        currency = (route.pricing_currency or "USD").upper()
        input_price = route.input_price_per_million
        output_price = route.output_price_per_million
        if input_price is None or (output_tokens > 0 and output_price is None):
            cost_complete = False
            continue
        micros = round(
            input_tokens * float(input_price)
            + output_tokens * float(output_price or 0)
        )
        projected_costs[currency] = max(projected_costs.get(currency, 0), max(0, micros))

    return {
        "projected_tokens": projected_tokens,
        "projected_costs": projected_costs,
        "cost_projection_complete": cost_complete,
        "token_projection_complete": output_complete,
    }


def _quota_preflight(
    repository: Repository | None,
    gateway: ModelGateway,
    identity: RequestIdentity,
    payload: dict,
    capability: str,
) -> dict:
    if repository is None:
        return {
            "allowed": True,
            "reservation_id": None,
            "warnings": [],
            "checks": [],
            "period": None,
        }
    projection = _estimate_request_quota_projection(payload, gateway, capability)
    check = repository.reserve_quota(
        identity.tenant_id,
        identity.application_id,
        projected_tokens=projection["projected_tokens"],
        projected_costs=projection["projected_costs"],
        token_projection_complete=projection["token_projection_complete"],
        cost_projection_complete=projection["cost_projection_complete"],
    )
    for item in check.get("checks", []):
        item["token_projection_complete"] = projection["token_projection_complete"]
    if check.get("allowed"):
        return check

    violation = check.get("violation") or {"code": "quota_exceeded"}
    headers = {
        "X-FreeLLM-Quota-Scope": str(violation.get("scope_type", "")),
        "X-FreeLLM-Quota-Resource": str(violation.get("resource", "")),
    }
    period_end = violation.get("period_end")
    if isinstance(period_end, str):
        headers["X-FreeLLM-Quota-Period-End"] = period_end
        try:
            end = datetime.fromisoformat(period_end)
            now = datetime.now(timezone.utc)
            retry_after = max(1, int((end - now).total_seconds()))
            headers["Retry-After"] = str(retry_after)
        except ValueError:
            pass
    status_code = (
        422
        if violation.get("code") in {
            "quota_output_limit_required",
            "quota_cost_projection_unavailable",
        }
        else 429
    )
    raise HTTPException(status_code=status_code, detail=violation, headers=headers)


def _quota_response_headers(check: dict) -> dict[str, str]:
    warnings = check.get("warnings") or []
    headers: dict[str, str] = {}
    if warnings:
        parts = []
        for warning in warnings:
            utilization = warning.get("utilization_percent")
            utilization_text = "unknown" if utilization is None else f"{float(utilization):.2f}"
            parts.append(
                f"{warning.get('scope_type')}:{warning.get('scope_id')}:"
                f"{warning.get('resource')}:{utilization_text}%"
            )
        headers["X-FreeLLM-Quota-Warning"] = ";".join(parts)
        headers["X-FreeLLM-Quota-Warning-Count"] = str(len(warnings))
    checks = check.get("checks") or []
    if any(
        item.get("token_projection_complete") is False
        or item.get("cost_projection_complete") is False
        for item in checks
    ):
        headers["X-FreeLLM-Quota-Projection"] = "partial"
    period = check.get("period") or {}
    if period.get("end"):
        headers["X-FreeLLM-Quota-Period-End"] = str(period["end"])
    return headers


def _pricing_currency(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 8:
        raise HTTPException(status_code=422, detail="currency must be a non-empty string up to 8 characters")
    return value.strip().upper()


def _require_identity_id(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=f"{field} is required")
    normalized = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,63}", normalized):
        raise HTTPException(
            status_code=422,
            detail=f"{field} must be 1-64 letters, digits or hyphens",
        )
    return normalized


def _require_identity_name(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=422, detail=f"{field} is required")
    normalized = value.strip()
    if len(normalized) > 120:
        raise HTTPException(status_code=422, detail=f"{field} must be at most 120 characters")
    return normalized


def _require_known_model(model: str, gateway: ModelGateway) -> None:
    if model != "auto" and not any(
        route.id == model or route.remote_model == model for route in gateway.routes
    ):
        raise HTTPException(status_code=404, detail="model route not found")


def _require_public_url(value: str, field: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail=f"{field} must be an https URL without credentials")


def _require_provider_base_url(value: str) -> None:
    try:
        validate_provider_target(value, resolve_dns=True)
    except UnsafeProviderTarget as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _with_pool_status(offer: dict, routes: list, provider_names: dict[str, str] | None = None) -> dict:
    """Attach safe local model-pool metadata to a public catalog offer."""
    provider = str(offer.get("provider") or "").strip().casefold()
    model = str(offer.get("model") or "").strip().casefold()
    offer_id = str(offer.get("id") or "").strip().casefold()
    provider_names = provider_names or {}
    def provider_matches(route) -> bool:
        route_id = str(route.provider_id).strip().casefold()
        route_name = str(provider_names.get(route.provider_id, "")).strip().casefold()
        return bool(provider and provider in {route_id, route_name})

    provider_routes = [route for route in routes if provider_matches(route)]
    exact = []
    for route in routes:
        route_model = str(route.remote_model).strip().casefold()
        route_id = str(route.id).strip().casefold()
        if offer_id and offer_id == route_id:
            exact.append(route)
        elif provider_matches(route) and model and model == route_model:
            exact.append(route)
    matched = exact[0] if exact else None
    counted = exact if matched else provider_routes if provider else []
    result = dict(offer)
    result["pool_status"] = {
        "state": "enabled" if matched and matched.enabled else "disabled" if matched else "not_added",
        "exact": bool(matched),
        "route_id": matched.id if matched else None,
        "enabled_count": sum(route.enabled for route in counted),
        "disabled_count": sum(not route.enabled for route in counted),
    }
    return result
