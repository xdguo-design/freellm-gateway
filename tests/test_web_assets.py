from pathlib import Path

import pytest

from freellm_gateway import web_assets


def test_prebuilt_admin_bundle_does_not_require_node(tmp_path, monkeypatch):
    package_dir = tmp_path / "freellm_gateway"
    index = package_dir / "static" / "admin" / "index.html"
    index.parent.mkdir(parents=True)
    index.write_text("<div id='root'></div>", encoding="utf-8")
    monkeypatch.setattr(web_assets, "find_npm", lambda: None)

    assert web_assets.ensure_admin_bundle(package_dir=package_dir) == index


def test_source_checkout_builds_missing_admin_bundle(tmp_path, monkeypatch):
    package_dir = tmp_path / "freellm_gateway"
    package_dir.mkdir()
    web_dir = tmp_path / "web"
    web_dir.mkdir()
    (web_dir / "package.json").write_text("{}", encoding="utf-8")
    calls = []

    monkeypatch.setattr(web_assets, "find_npm", lambda: "npm")

    def fake_run(command, cwd, check):
        calls.append((command, Path(cwd), check))
        if command[-2:] == ["run", "build"]:
            index = package_dir / "static" / "admin" / "index.html"
            index.parent.mkdir(parents=True)
            index.write_text("<div id='root'></div>", encoding="utf-8")

    monkeypatch.setattr(web_assets.subprocess, "run", fake_run)

    index = web_assets.ensure_admin_bundle(package_dir=package_dir)

    assert index.is_file()
    assert calls[0][0][:2] == ["npm", "install"]
    assert calls[1][0] == ["npm", "run", "build"]


def test_missing_bundle_without_source_or_node_fails_clearly(tmp_path, monkeypatch):
    package_dir = tmp_path / "freellm_gateway"
    package_dir.mkdir()
    monkeypatch.setattr(web_assets, "find_npm", lambda: None)

    with pytest.raises(RuntimeError, match="bundle is missing"):
        web_assets.ensure_admin_bundle(package_dir=package_dir)
