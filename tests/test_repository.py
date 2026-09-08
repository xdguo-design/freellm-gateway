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
    )

    repository.save_provider(provider)
    repository.save_route(route)

    loaded = repository.list_routes()[0]
    assert loaded.id == "groq-fast"
    assert loaded.priority == 1
    assert loaded.credential_ref.startswith("keyring://")
    assert "super-secret" not in str(loaded)
