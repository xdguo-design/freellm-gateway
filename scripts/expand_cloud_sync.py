#!/usr/bin/env python3
"""Restore full api.py and admin.html from compressed part blobs."""
from pathlib import Path
import zlib, base64, sys

ROOT = Path(__file__).resolve().parents[1]

def load_parts(name: str, max_parts: int = 16) -> str:
    pieces = []
    for i in range(max_parts):
        p = ROOT / "freellm_gateway" / f"_full_{name}.part{i}.b64"
        if not p.exists():
            if i == 0:
                raise SystemExit(f"missing {p}")
            break
        pieces.append(p.read_text().strip())
    return "".join(pieces)

def expand(name: str, target: Path):
    b64 = load_parts(name)
    data = zlib.decompress(base64.b64decode(b64.encode("ascii")))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    print(f"wrote {target} ({len(data)} bytes)")

def main():
    expand("api", ROOT / "freellm_gateway" / "api.py")
    expand("admin", ROOT / "freellm_gateway" / "templates" / "admin.html")
    print("done — full Phase1/2 + Hybrid RAG sources restored")

if __name__ == "__main__":
    main()
