#!/usr/bin/env python3
"""Restore full api.py and admin.html from compressed blobs (full or parts)."""
from pathlib import Path
import zlib, base64

ROOT = Path(__file__).resolve().parents[1]

def load_b64(name: str, part_count: int | None = None) -> str:
    full = ROOT / "freellm_gateway" / f"_full_{name}.zlib.b64"
    if full.exists() and full.stat().st_size > 1000:
        text = full.read_text().strip()
        try:
            zlib.decompress(base64.b64decode(text.encode("ascii")))
            return text
        except Exception:
            pass
    if part_count:
        pieces = []
        for i in range(part_count):
            p = ROOT / "freellm_gateway" / f"_full_{name}.part{i}.b64"
            if not p.exists():
                raise SystemExit(f"missing {p}")
            pieces.append(p.read_text().strip())
        return "".join(pieces)
    raise SystemExit(f"no valid blob for {name}")

def expand(name: str, target: Path, part_count: int | None = None):
    b64 = load_b64(name, part_count)
    data = zlib.decompress(base64.b64decode(b64.encode("ascii")))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    print(f"wrote {target} ({len(data)} bytes)")

def main():
    expand("api", ROOT / "freellm_gateway" / "api.py", part_count=3)
    expand("admin", ROOT / "freellm_gateway" / "templates" / "admin.html", part_count=4)
    print("done — full Phase1/2 + Hybrid RAG sources restored")

if __name__ == "__main__":
    main()
