import argparse
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from .catalog import export_catalog
from .db import Database
from .repository import Repository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="freellm-gateway")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="start the local HTTP server")
    run.add_argument(
        "--host",
        default=os.getenv("FREELLM_GATEWAY_HOST", "127.0.0.1"),
    )
    run.add_argument(
        "--port",
        default=int(os.getenv("PORT", os.getenv("FREELLM_GATEWAY_PORT", "8765"))),
        type=int,
    )
    run.add_argument(
        "--skip-web-build",
        action="store_true",
        help="do not build the React admin bundle when running from source",
    )
    run.add_argument(
        "--open-browser",
        action="store_true",
        help="open the React admin console after the server starts",
    )

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

        if not args.skip_web_build:
            from .web_assets import ensure_admin_bundle

            try:
                ensure_admin_bundle()
            except (RuntimeError, subprocess.CalledProcessError) as error:
                print(f"unable to prepare React admin: {error}", file=sys.stderr)
                return 2

        if args.open_browser:
            browser_host = "127.0.0.1" if args.host in {"0.0.0.0", "::"} else args.host
            url = f"http://{browser_host}:{args.port}/admin/"

            def open_admin() -> None:
                time.sleep(0.8)
                webbrowser.open(url)

            threading.Thread(target=open_admin, daemon=True).start()

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
