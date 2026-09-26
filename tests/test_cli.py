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
