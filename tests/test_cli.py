from freellm_gateway.cli import build_parser


def test_cli_exposes_run_init_and_export_catalog_commands():
    parser = build_parser()

    run = parser.parse_args(["run"])
    assert run.command == "run"
    assert run.skip_web_build is False
    assert run.open_browser is False

    configured = parser.parse_args(["run", "--skip-web-build", "--open-browser", "--port", "9000"])
    assert configured.skip_web_build is True
    assert configured.open_browser is True
    assert configured.port == 9000
    assert parser.parse_args(["init"]).command == "init"
    assert parser.parse_args(["export-catalog"]).command == "export-catalog"


def test_cli_run_defaults_to_cloud_host_and_port_environment(monkeypatch):
    monkeypatch.setenv("FREELLM_GATEWAY_HOST", "0.0.0.0")
    monkeypatch.setenv("FREELLM_GATEWAY_PORT", "9001")
    parser = build_parser()

    run = parser.parse_args(["run"])

    assert run.host == "0.0.0.0"
    assert run.port == 9001


def test_cli_prefers_platform_port_environment(monkeypatch):
    monkeypatch.setenv("FREELLM_GATEWAY_PORT", "9001")
    monkeypatch.setenv("PORT", "10001")
    parser = build_parser()

    assert parser.parse_args(["run"]).port == 10001
