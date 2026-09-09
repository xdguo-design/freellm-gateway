"""Entry point for the packaged desktop gateway (PyInstaller sidecar).

Loads the ASGI app object directly so uvicorn does not need to import it by
string (module-string imports break inside a frozen executable). All runtime
configuration comes from environment variables set by the desktop shell.

Built with ``--windowed`` (no console window), so stdout/stderr are redirected
to a log file for diagnosability.
"""

import os
import sys

import uvicorn

from freellm_gateway.main import app


def main() -> None:
    log_path = os.environ.get("FREELLM_GATEWAY_LOG")
    if log_path:
        try:
            log_file = open(log_path, "a", buffering=1, encoding="utf-8", errors="replace")
            sys.stdout = log_file
            sys.stderr = log_file
        except OSError:
            pass
    uvicorn.run(
        app,
        host=os.getenv("FREELLM_GATEWAY_HOST", "127.0.0.1"),
        port=int(os.getenv("FREELLM_GATEWAY_PORT", "18900")),
        log_level="info",
    )


if __name__ == "__main__":
    main()
