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


def source_bundle_is_stale(web_dir: Path, index: Path) -> bool:
    if not index.is_file():
        return True
    inputs = [
        web_dir / "package.json",
        web_dir / "package-lock.json",
        web_dir / "vite.config.ts",
        web_dir / "tsconfig.json",
        web_dir / "index.html",
    ]
    src = web_dir / "src"
    if src.is_dir():
        inputs.extend(path for path in src.rglob("*") if path.is_file())
    bundle_mtime = index.stat().st_mtime
    return any(path.is_file() and path.stat().st_mtime > bundle_mtime for path in inputs)


def ensure_admin_bundle(
    *,
    package_dir: Path = PACKAGE_DIR,
    install_dependencies: bool = True,
) -> Path:
    """Return a usable React admin index, building source checkouts as needed.

    Installed wheels already contain the static/admin bundle and do not include
    the source web directory, so they never need Node.js. In a source checkout
    the bundle is rebuilt when React source/config is newer than index.html.
    """
    index = admin_index_path(package_dir)
    web_dir = source_web_dir(package_dir)
    package_json = web_dir / "package.json"

    if not package_json.is_file():
        if index.is_file():
            return index
        raise RuntimeError(
            "React admin bundle is missing from this installation. "
            "Install an official wheel/build that includes freellm_gateway/static/admin."
        )

    if not source_bundle_is_stale(web_dir, index):
        return index

    npm = find_npm()
    if not npm:
        raise RuntimeError(
            "React admin bundle is missing or stale and npm was not found. "
            "Install Node.js 18+ or run from a packaged wheel."
        )

    vite_name = "vite.cmd" if shutil.which("cmd") else "vite"
    vite = web_dir / "node_modules" / ".bin" / vite_name
    if install_dependencies and not vite.exists():
        install_command = [npm, "ci" if (web_dir / "package-lock.json").is_file() else "install"]
        install_command.extend(["--no-audit", "--no-fund"])
        subprocess.run(install_command, cwd=web_dir, check=True)

    subprocess.run([npm, "run", "build"], cwd=web_dir, check=True)
    if not index.is_file():
        raise RuntimeError(
            f"React admin build completed but {index} was not created."
        )
    return index
