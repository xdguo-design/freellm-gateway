from freellm_gateway.cli import build_parser


def test_cli_exposes_run_init_and_export_catalog_commands():
    parser = build_parser()

    assert parser.parse_args(["run"]).command == "run"
    assert parser.parse_args(["init"]).command == "init"
    assert parser.parse_args(["export-catalog"]).command == "export-catalog"
