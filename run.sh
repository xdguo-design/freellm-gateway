#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT"

HOST="${FREELLM_GATEWAY_HOST:-127.0.0.1}"
PORT="${FREELLM_GATEWAY_PORT:-8765}"

if [ ! -x ".venv/bin/python" ]; then
  python3 -m venv .venv
fi

.venv/bin/python -m pip install -e .
exec .venv/bin/python -m freellm_gateway run --host "$HOST" --port "$PORT" --open-browser
