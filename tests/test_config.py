from freellm_gateway.config import Settings


def test_missing_tokens_are_generated_instead_of_using_fixed_defaults(monkeypatch):
    monkeypatch.delenv("FREELLM_GATEWAY_API_TOKEN", raising=False)
    monkeypatch.delenv("FREELLM_GATEWAY_ADMIN_TOKEN", raising=False)

    settings = Settings.from_env()

    assert len(settings.api_token) >= 32
    assert len(settings.admin_token) >= 32
    assert settings.api_token != settings.admin_token
