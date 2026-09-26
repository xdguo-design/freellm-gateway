"""End-to-end smoke test for the FreeLLM Studio desktop app.

Launches the built freellm-studio.exe and verifies the whole lifecycle:

  1. process stays alive and a window appears
  2. the gateway sidecar comes up on the port recorded in
     %APPDATA%/top.freellm.desktop/gateway.port (within 30s)
  3. the admin UI is served over that port
  4. gracefully closing the window only hides it to the tray
     (process and gateway stay alive)
  5. force-killing the app terminates the whole gateway process tree

Usage:
    python scripts/smoke_test.py [--exe path\\to\\freellm-studio.exe]

Exit code 0 = all checks passed.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

APP_DATA = Path(os.environ["APPDATA"]) / "top.freellm.desktop"
DEFAULT_EXE = Path(__file__).resolve().parents[1] / "src-tauri" / "target" / "release" / "freellm-studio.exe"
PORT_FILE = APP_DATA / "gateway.port"


def http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def wait_for(fn, deadline_s: float, interval: float = 0.2):
    end = time.time() + deadline_s
    while time.time() < end:
        result = fn()
        if result:
            return result
        time.sleep(interval)
    return None


def kill(process=None, force: bool = False) -> None:
    args = ["taskkill", "/PID", str(process.pid)]
    if force:
        args.append("/F")
    subprocess.run(args, capture_output=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", default=str(DEFAULT_EXE))
    args = parser.parse_args()
    exe = Path(args.exe)
    if not exe.is_file():
        print(f"FAIL: app not found: {exe}")
        return 1

    # Clean slate: no app or gateway from an earlier run.
    for name in ("freellm-studio", "freellm-gateway"):
        subprocess.run(["taskkill", "/IM", f"{name}.exe", "/F"], capture_output=True)
    time.sleep(1)
    PORT_FILE.unlink(missing_ok=True)

    print(f"launching {exe}")
    app = subprocess.Popen([str(exe)], cwd=str(exe.parent))

    failures = []

    # 1. process alive + window appears
    if not wait_for(lambda: app.poll() is None and window_title() is not None, 20):
        failures.append("window did not appear within 20s (or app exited early)")
    else:
        print("OK   window appears:", window_title())

    # 2. gateway comes up on the port from the port file
    def gateway_ready():
        if not PORT_FILE.is_file():
            return None
        port = int(PORT_FILE.read_text(encoding="utf-8").strip())
        return port if http_ok(f"http://127.0.0.1:{port}/health") else None

    port = wait_for(gateway_ready, 30)
    if port is None:
        failures.append("gateway did not become healthy within 30s")
    else:
        print(f"OK   gateway healthy on port {port}")

    # 3. React admin shell + generated assets are served.
    if port and not wait_for(lambda: react_admin_ok(port), 10):
        failures.append("React admin UI or assets were not served correctly")
    else:
        print("OK   React admin shell and assets served")

    # 4. graceful window close = hide to tray (process + gateway stay alive).
    # taskkill is process termination, not a window-close signal, so use the
    # process MainWindowHandle through CloseMainWindow().
    close_main_window()
    time.sleep(3)
    if app.poll() is not None:
        failures.append("app exited on graceful window close (should hide to tray)")
    elif port and not http_ok(f"http://127.0.0.1:{port}/health"):
        failures.append("gateway died after window close (should keep serving)")
    else:
        print("OK   window close hides to tray, gateway still serving")

    # 4.5 watchdog revives a killed gateway (the reported failure mode: splash
    # used to time out forever after the gateway died; "Retry" now recovers)
    if port:
        subprocess.run(["taskkill", "/IM", "freellm-gateway.exe", "/F"], capture_output=True)
        revived = wait_for(lambda: http_ok(f"http://127.0.0.1:{port}/health"), 25)
        if revived is None:
            failures.append("watchdog did not revive a killed gateway within 25s")
        else:
            print("OK   watchdog revives killed gateway")

    # 5. force kill = whole tree gone
    kill(app, force=True)
    time.sleep(3)
    if app.poll() is None:
        kill(app, force=True)
        time.sleep(2)
    tasklist = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq freellm-gateway.exe"], capture_output=True
    ).stdout
    if b"freellm-gateway" in tasklist:
        failures.append("gateway process survived app force-kill (job object failed)")
    else:
        print("OK   force-kill cleans up gateway process tree")

    if failures:
        for failure in failures:
            print("FAIL:", failure)
        return 1
    print("\nSMOKE TEST PASSED")
    return 0


def admin_html(port: int) -> bytes:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/admin/", timeout=3) as response:
            return response.read()
    except Exception:
        return b""


def react_admin_ok(port: int) -> bool:
    html = admin_html(port)
    if b'<div id="root"></div>' not in html:
        return False
    marker = b'./assets/'
    if marker not in html:
        marker = b'/assets/'
    if marker not in html:
        return False
    text = html.decode("utf-8", errors="ignore")
    import re
    match = re.search(r'(?:\./)?assets/[^"']+\.js', text)
    if not match:
        return False
    asset = match.group(0)
    if not asset.startswith("/"):
        asset = "/" + asset.removeprefix("./")
    return http_ok(f"http://127.0.0.1:{port}/admin{asset}")


def close_main_window() -> None:
    subprocess.run(
        [
            "powershell", "-NoProfile", "-Command",
            "$p = Get-Process freellm-studio -ErrorAction SilentlyContinue | "
            "Select-Object -First 1; if ($p) { [void]$p.CloseMainWindow() }",
        ],
        capture_output=True,
        text=True,
    )


def window_title():
    probe = subprocess.run(
        [
            "powershell", "-NoProfile", "-Command",
            "(Get-Process freellm-studio -ErrorAction SilentlyContinue | "
            "Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1).MainWindowTitle",
        ],
        capture_output=True,
        text=True,
    )
    title = probe.stdout.strip()
    return title or None


if __name__ == "__main__":
    sys.exit(main())
