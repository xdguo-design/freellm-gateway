from freellm_gateway.db import Database
from freellm_gateway.models import ModelRoute, Provider
from freellm_gateway.repository import Repository
from freellm_gateway.runtime import build_gateway


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
