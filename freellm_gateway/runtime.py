from .adapters.anthropic import AnthropicAdapter, anthropic_messages_endpoint
from .adapters.gemini import GeminiAdapter
from .adapters.openai import OpenAICompatibleAdapter
from .network_safety import UnsafeProviderTarget, validate_provider_target
from .repository import Repository
from .service import ModelGateway


def build_gateway(repository: Repository, secrets) -> ModelGateway:
    providers = {provider.id: provider for provider in repository.list_providers()}
    routes = repository.list_routes()
    adapters = {}
    for route in routes:
        provider = providers.get(route.provider_id)
        adapter = adapter_for_route(route, provider, secrets)
        if adapter:
            adapters[route.id] = adapter
    return ModelGateway(routes, adapters, on_route_changed=repository.save_route)


def adapter_for_route(route, provider, secrets):
    if not provider or not route.credential_ref:
        return None
    api_key = secrets.get(route.credential_ref)
    if not api_key:
        return None
    try:
        return adapter_for_provider(provider, api_key, route.endpoint)
    except UnsafeProviderTarget:
        return None


def adapter_for_provider(provider, api_key: str, endpoint: str | None = None):
    if provider.protocol == "openai":
        endpoint = endpoint or provider.base_url.rstrip("/") + "/chat/completions"
        validate_provider_target(endpoint, resolve_dns=True)
        return OpenAICompatibleAdapter(endpoint, api_key)
    if provider.protocol == "anthropic":
        endpoint = endpoint or anthropic_messages_endpoint(provider.base_url)
        validate_provider_target(endpoint, resolve_dns=True)
        return AnthropicAdapter(endpoint, api_key)
    if provider.protocol == "gemini":
        target = endpoint or provider.base_url
        validate_provider_target(target, resolve_dns=True)
        return GeminiAdapter(target, api_key)
    return None
