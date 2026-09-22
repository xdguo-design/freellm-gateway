from .adapters.gemini import GeminiNativeAdapter
from .adapters.openai import OpenAICompatibleAdapter
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
    return ModelGateway(routes, adapters)


def adapter_for_route(route, provider, secrets):
    if not provider or not route.credential_ref:
        return None
    api_key = secrets.get(route.credential_ref)
    if not api_key:
        return None
    if provider.protocol == "openai":
        endpoint = route.endpoint or provider.base_url.rstrip("/") + "/chat/completions"
        return OpenAICompatibleAdapter(endpoint, api_key, provider_id=provider.id)
    if provider.protocol == "gemini":
        base_url = route.endpoint or provider.base_url
        return GeminiNativeAdapter(base_url, api_key, provider_id=provider.id)
    return None
