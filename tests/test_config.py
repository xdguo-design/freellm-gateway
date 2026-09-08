from freellm_gateway.config import Settings


def test_missing_tokens_are_generated_instead_of_using_fixed_defaults(monkeypatch):
    monkeypatch.delenv("FREELLM_GATEWAY_API_TOKEN", raising=False)
    monkeypatch.delenv("FREELLM_GATEWAY_ADMIN_TOKEN", raising=False)

    settings = Settings.from_env()

    assert len(settings.api_token) >= 32
    assert len(settings.admin_token) >= 32
    assert settings.api_token != settings.admin_token


def test_generated_tokens_are_printed_for_local_startup(monkeypatch, capsys):
    monkeypatch.delenv("FREELLM_GATEWAY_API_TOKEN", raising=False)
    monkeypatch.delenv("FREELLM_GATEWAY_ADMIN_TOKEN", raising=False)

    Settings.from_env()

    output = capsys.readouterr().err
    assert "FREELLM_GATEWAY_API_TOKEN=" in output
    assert "FREELLM_GATEWAY_ADMIN_TOKEN=" in output
