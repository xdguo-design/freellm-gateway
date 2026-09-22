#!/usr/bin/env python3
"""Restore full api.py and admin.html from compressed blobs (parts or single zlib.b64)."""
from pathlib import Path
import zlib, base64

ROOT = Path(__file__).resolve().parents[1]

def load_b64(name: str) -> str:
    for prefix in ("_push_", "_full_"):
        single = ROOT / "freellm_gateway" / f"{prefix}{name}.zlib.b64"
        if single.exists():
            return single.read_text().strip()
    for prefix in ("_push_", "_full_"):
        pieces = []
        for i in range(16):
            p = ROOT / "freellm_gateway" / f"{prefix}{name}.part{i}.b64"
            if not p.exists():
                break
            pieces.append(p.read_text().strip())
        if pieces:
            return "".join(pieces)
    raise SystemExit(f"missing compressed source for {name}")

def expand(name: str, target: Path):
    b64 = load_b64(name)
    data = zlib.decompress(base64.b64decode(b64.encode("ascii")))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    print(f"wrote {target} ({len(data)} bytes)")

def main():
    expand("api", ROOT / "freellm_gateway" / "api.py")
    expand("admin", ROOT / "freellm_gateway" / "templates" / "admin.html")
    print("done — embedding-routed knowledge + admin UI restored")

if __name__ == "__main__":
    main()
