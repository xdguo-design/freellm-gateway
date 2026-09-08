import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from freellm_gateway.catalog import merge_into_site_offers


def sync(export_path: Path, site_repo: Path, check: bool = False, build: bool = False) -> bool:
    export_data = json.loads(export_path.read_text(encoding="utf-8"))
    offers_path = site_repo / "data" / "offers.json"
    review_path = site_repo / "data" / "review-queue.json"
    offers = json.loads(offers_path.read_text(encoding="utf-8"))
    existing_review = json.loads(review_path.read_text(encoding="utf-8")) if review_path.exists() else []
    merged_offers, new_review = merge_into_site_offers(offers, export_data)
    published_ids = {item.get("id") for item in export_data.get("published", [])}
    review = _merge_review(existing_review, new_review, published_ids)
    offers_text = json.dumps(merged_offers, ensure_ascii=False, indent=2) + "\n"
    review_text = json.dumps(review, ensure_ascii=False, indent=2) + "\n"
    changed = offers_text != offers_path.read_text(encoding="utf-8") or (
        not review_path.exists() or review_text != review_path.read_text(encoding="utf-8")
    )
    if check:
        print("catalog sync: changes detected" if changed else "catalog sync: current")
        return changed
    if changed:
        offers_path.write_text(offers_text, encoding="utf-8")
        review_path.write_text(review_text, encoding="utf-8")
        print(f"catalog sync: wrote {offers_path} and {review_path}")
    else:
        print("catalog sync: no changes")
    if build:
        subprocess.run([sys.executable, "scripts/build_static.py"], cwd=site_repo, check=True)
        subprocess.run([sys.executable, "scripts/build_seo_pages.py"], cwd=site_repo, check=True)
    return changed


def _merge_review(existing: list[dict], new_items: list[dict], published_ids: set[str]) -> list[dict]:
    merged = {item.get("id"): item for item in existing if item.get("id")}
    merged.update({item.get("id"): item for item in new_items if item.get("id")})
    for item_id in published_ids:
        merged.pop(item_id, None)
    return list(merged.values())


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync public gateway models into the FreeLLM site repo")
    parser.add_argument("--export", required=True, type=Path)
    parser.add_argument("--site-repo", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    changed = sync(args.export, args.site_repo, check=args.check, build=args.build)
    return 1 if args.check and changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
