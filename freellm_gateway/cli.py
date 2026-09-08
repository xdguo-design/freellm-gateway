import argparse
import subprocess
import sys
from pathlib import Path

from .catalog import export_catalog
from .db import Database
from .repository import Repository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="freellm-gateway")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="start the local HTTP server")
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--port", default=8765, type=int)

    init = subparsers.add_parser("init", help="initialize the SQLite database")
    init.add_argument("--db", default="data/gateway.sqlite3")

    export = subparsers.add_parser("export-catalog", help="export public catalog JSON")
    export.add_argument("--db", default="data/gateway.sqlite3")
    export.add_argument("--output", default="data/catalog-export.json")

    sync = subparsers.add_parser("sync-site", help="sync an export into the FreeLLM site repo")
    sync.add_argument("--export", required=True)
    sync.add_argument("--site-repo", required=True)
    sync.add_argument("--check", action="store_true")
    sync.add_argument("--build", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        import uvicorn

        uvicorn.run("freellm_gateway.main:app", host=args.host, port=args.port, reload=False)
        return 0
    if args.command == "init":
        Repository(Database(args.db)).initialize()
        print(f"initialized database: {args.db}")
        return 0
    if args.command == "export-catalog":
        repository = Repository(Database(args.db))
        repository.initialize()
        providers = {provider.id: provider for provider in repository.list_providers()}
        data = export_catalog(repository.list_routes(), providers, args.output)
        print(f"exported catalog: {len(data['published'])} published, {len(data['review'])} review")
        return 0
    if args.command == "sync-site":
        command = [sys.executable, "scripts/sync_freellm_catalog.py", "--export", args.export, "--site-repo", args.site_repo]
        if args.check:
            command.append("--check")
        if args.build:
            command.append("--build")
        return subprocess.run(command, check=False).returncode
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
