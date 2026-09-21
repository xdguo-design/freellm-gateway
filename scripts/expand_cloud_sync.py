#!/usr/bin/env python3
"""Restore full api.py and admin.html from compressed blobs."""
from pathlib import Path
import zlib, base64

ROOT = Path(__file__).resolve().parents[1]

def expand(name: str, target: Path):
    src = ROOT / "freellm_gateway" / f"_full_{name}.zlib.b64"
    if not src.exists():
        raise SystemExit(f"missing {src}")
    data = zlib.decompress(base64.b64decode(src.read_text().strip().encode("ascii")))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    print(f"wrote {target} ({len(data)} bytes)")

def main():
    expand("api", ROOT / "freellm_gateway" / "api.py")
    expand("admin", ROOT / "freellm_gateway" / "templates" / "admin.html")
    print("done — full Phase1/2 + Hybrid RAG sources restored")

if __name__ == "__main__":
    main()
