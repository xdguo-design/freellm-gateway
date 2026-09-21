#!/usr/bin/env python3
"""Expand cloud-synced compressed sources into api.py and admin.html."""
from pathlib import Path
import zlib, base64

ROOT = Path(__file__).resolve().parents[1]

def expand(b64_path: Path, target: Path):
    blob = b64_path.read_text().strip()
    data = zlib.decompress(base64.b64decode(blob.encode("ascii")))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    print(f"wrote {target} ({len(data)} bytes)")

def main():
    expand(ROOT / "freellm_gateway/_sync_api.py.zlib.b64", ROOT / "freellm_gateway/api.py")
    expand(ROOT / "freellm_gateway/_sync_admin.html.zlib.b64", ROOT / "freellm_gateway/templates/admin.html")
    print("done \u2014 Phase1/2 + Hybrid RAG sources restored")

if __name__ == "__main__":
    main()
