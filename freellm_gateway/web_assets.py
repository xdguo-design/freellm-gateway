from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent


def admin_index_path(package_dir: Path = PACKAGE_DIR) -> Path:
    return package_dir / "static" / "admin" / "index.html"


def source_web_dir(package_dir: Path = PACKAGE_DIR) -> Path:
    return package_dir.parent / "web"


def find_npm() -> str | None:
    return shutil.which("npm") or shutil.which("npm.cmd")


def ensure_admin_bundle(
    *,
    package_dir: Path = PACKAGE_DIR,
    install_dependencies: bool = True,
) -> Path:
    """Return a usable React admin index, building it for source checkouts.

    Installed wheels already contain ``static/admin`` and therefore never need
    Node.js. A source checkout builds the bundle on first run if it is missing.
    """
    index = admin_index_path(package_dir)
    if index.is_file():
        return index

    web_dir = source_web_dir(package_dir)
    package_json = web_dir / "package.json"
    if not package_json.is_file():
        raise RuntimeError(
            "React admin bundle is missing from this installation. "
            "Install an official wheel/build that includes freellm_gateway/static/admin."
        )

    npm = find_npm()
    if not npm:
        raise RuntimeError(
            "React admin bundle has not been built and npm was not found. "
            "Install Node.js 18+ or run from a packaged wheel."
        )

    vite_name = "vite.cmd" if shutil.which("cmd") else "vite"
    vite = web_dir / "node_modules" / ".bin" / vite_name
    if install_dependencies and not vite.exists():
        subprocess.run(
            [npm, "install", "--no-audit", "--no-fund"],
            cwd=web_dir,
            check=True,
        )

    subprocess.run([npm, "run", "build"], cwd=web_dir, check=True)
    if not index.is_file():
        raise RuntimeError(
            f"React admin build completed but {index} was not created."
        )
    return index
