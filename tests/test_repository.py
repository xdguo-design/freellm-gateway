from freellm_gateway.db import Database
from freellm_gateway.models import ModelRoute, Provider
from freellm_gateway.repository import Repository


def test_repository_persists_provider_and_route_without_secret_value(tmp_path):
    repository = Repository(Database(tmp_path / "gateway.sqlite3"))
    repository.initialize()
    provider = Provider(
        id="groq", name="Groq", protocol="openai", base_url="https://api.groq.com/openai/v1", official_url="https://groq.com"
    )
    route = ModelRoute(
        id="groq-fast", provider_id="groq", remote_model="llama", priority=1,
        credential_ref="keyring://freellm-gateway/groq-fast",
        capabilities=frozenset({"chat", "tools"}),
        context_window=131072,
        max_output_tokens=8192,
        input_price_per_million=0.2,
        output_price_per_million=0.8,
        pricing_currency="USD",
    )

    repository.save_provider(provider)
    repository.save_route(route)

    loaded = repository.list_routes()[0]
    assert loaded.id == "groq-fast"
    assert loaded.priority == 1
    assert loaded.credential_ref.startswith("keyring://")
    assert loaded.context_window == 131072
    assert loaded.max_output_tokens == 8192
    assert loaded.input_price_per_million == 0.2
    assert loaded.output_price_per_million == 0.8
    assert loaded.pricing_currency == "USD"
    assert "super-secret" not in str(loaded)
