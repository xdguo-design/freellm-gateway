from freellm_gateway.db import Database
from freellm_gateway.models import ModelRoute, Provider
from freellm_gateway.repository import Repository
from freellm_gateway.runtime import build_gateway
from freellm_gateway.runtime import adapter_for_route
from freellm_gateway.adapters.anthropic import AnthropicAdapter
from freellm_gateway.adapters.gemini import GeminiAdapter


class FakeSecrets:
    def get(self, reference):
        return "secret-for-route"


def test_runtime_builds_openai_adapter_from_persisted_provider_and_route(tmp_path):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    repository.initialize()
    repository.save_provider(Provider("groq", "Groq", "openai", "https://api.groq.com/openai/v1", "https://groq.com"))
    repository.save_route(ModelRoute(
        id="groq-llama", provider_id="groq", remote_model="llama", priority=1,
        credential_ref="keyring://test/groq-llama",
    ))

    gateway = build_gateway(repository, FakeSecrets())

    assert gateway.routes[0].id == "groq-llama"
    assert gateway.adapters["groq-llama"].endpoint.endswith("/chat/completions")


def test_runtime_builds_anthropic_adapter_from_persisted_provider_and_route(tmp_path):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    repository.initialize()
    provider = Provider("anthropic", "Anthropic", "anthropic", "https://api.anthropic.com", "https://anthropic.com")
    repository.save_provider(provider)
    route = ModelRoute(
        id="anthropic-claude", provider_id="anthropic", remote_model="claude-demo", priority=1,
        credential_ref="keyring://test/anthropic-claude",
    )
    repository.save_route(route)

    adapter = adapter_for_route(route, provider, FakeSecrets())

    assert isinstance(adapter, AnthropicAdapter)
    assert adapter.endpoint.endswith("/v1/messages")


def test_runtime_does_not_duplicate_anthropic_v1_base_path():
    provider = Provider("anthropic", "Anthropic", "anthropic", "https://api.anthropic.com/v1", "https://anthropic.com")
    route = ModelRoute("anthropic-claude", "anthropic", "claude-demo", 1, credential_ref="memory://key")

    adapter = adapter_for_route(route, provider, FakeSecrets())

    assert adapter.endpoint == "https://api.anthropic.com/v1/messages"


def test_runtime_builds_gemini_adapter_from_persisted_provider_and_route():
    provider = Provider(
        "gemini", "Gemini", "gemini",
        "https://generativelanguage.googleapis.com/v1beta", "https://ai.google.dev",
    )
    route = ModelRoute(
        "gemini-3.8-flash", "gemini", "gemini-3.8-flash", 1, credential_ref="memory://key"
    )

    adapter = adapter_for_route(route, provider, FakeSecrets())

    assert isinstance(adapter, GeminiAdapter)
    assert adapter.base_url.endswith("/v1beta")
