import os
from pathlib import Path

import pytest

from freellm_gateway import web_assets


def test_prebuilt_wheel_bundle_does_not_require_node(tmp_path, monkeypatch):
    package_dir = tmp_path / "site-packages" / "freellm_gateway"
    index = package_dir / "static" / "admin" / "index.html"
    index.parent.mkdir(parents=True)
    index.write_text("<div id='root'></div>", encoding="utf-8")
    monkeypatch.setattr(web_assets, "find_npm", lambda: None)

    assert web_assets.ensure_admin_bundle(package_dir=package_dir) == index


def test_fresh_source_bundle_is_reused_without_node(tmp_path, monkeypatch):
    package_dir = tmp_path / "freellm_gateway"
    index = package_dir / "static" / "admin" / "index.html"
    index.parent.mkdir(parents=True)
    index.write_text("<div id='root'></div>", encoding="utf-8")
    web_dir = tmp_path / "web"
    web_dir.mkdir()
    package_json = web_dir / "package.json"
    package_json.write_text("{}", encoding="utf-8")
    old = index.stat().st_mtime - 10
    os.utime(package_json, (old, old))
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


def test_source_checkout_rebuilds_when_react_source_is_newer(tmp_path, monkeypatch):
    package_dir = tmp_path / "freellm_gateway"
    index = package_dir / "static" / "admin" / "index.html"
    index.parent.mkdir(parents=True)
    index.write_text("old", encoding="utf-8")
    web_dir = tmp_path / "web"
    src = web_dir / "src"
    src.mkdir(parents=True)
    package_json = web_dir / "package.json"
    package_json.write_text("{}", encoding="utf-8")
    source = src / "App.tsx"
    source.write_text("new source", encoding="utf-8")
    older = source.stat().st_mtime - 10
    os.utime(index, (older, older))
    calls = []

    monkeypatch.setattr(web_assets, "find_npm", lambda: "npm")

    def fake_run(command, cwd, check):
        calls.append(command)
        if command[-2:] == ["run", "build"]:
            index.write_text("new", encoding="utf-8")
            newer = source.stat().st_mtime + 10
            os.utime(index, (newer, newer))

    monkeypatch.setattr(web_assets.subprocess, "run", fake_run)

    assert web_assets.ensure_admin_bundle(package_dir=package_dir) == index
    assert ["npm", "run", "build"] in calls


def test_missing_bundle_without_source_fails_clearly(tmp_path, monkeypatch):
    package_dir = tmp_path / "freellm_gateway"
    package_dir.mkdir()
    monkeypatch.setattr(web_assets, "find_npm", lambda: None)

    with pytest.raises(RuntimeError, match="bundle is missing"):
        web_assets.ensure_admin_bundle(package_dir=package_dir)
