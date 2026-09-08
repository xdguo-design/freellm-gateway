import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .models import ModelRoute, Provider


def export_catalog(
    routes: list[ModelRoute],
    providers: dict[str, Provider],
    output_path: str | Path,
    generated_at: str | None = None,
) -> dict[str, Any]:
    timestamp = generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    entries = [_public_entry(route, providers.get(route.provider_id), timestamp) for route in sorted(routes, key=lambda item: (item.priority, item.id))]
    data = {
        "schemaVersion": 1,
        "generatedAt": timestamp,
        "published": [entry for entry in entries if entry["catalogStatus"] == "published"],
        "review": [entry for entry in entries if entry["catalogStatus"] != "published"],
    }
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def _public_entry(route: ModelRoute, provider: Provider | None, timestamp: str) -> dict[str, Any]:
    register = route.public_url or (provider.official_url if provider else None)
    return {
        "id": route.id,
        "providerId": route.provider_id,
        "provider": provider.name if provider else route.provider_id,
        "model": route.remote_model,
        "name": route.display_name or route.remote_model,
        "capabilities": sorted(route.capabilities),
        "register": register,
        "docsUrl": route.public_docs_url,
        "apiEndpoint": _public_url(
            route.endpoint or (
                provider.base_url.rstrip("/") + "/chat/completions"
                if provider and provider.protocol == "openai" else None
            )
        ),
        "freeSummary": route.free_summary,
        "catalogStatus": route.catalog_status,
        "lastVerifiedAt": timestamp[:10],
    }


def merge_into_site_offers(existing: list[dict], exported: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    offers = list(existing)
    existing_by_id = {item.get("id"): index for index, item in enumerate(offers)}
    published = list(exported.get("published", []))
    review = list(exported.get("review", []))
    for entry in published:
        if not entry.get("register") or not entry.get("apiEndpoint"):
            review.append(entry)
            continue
        entry_id = entry.get("id")
        existing_index = existing_by_id.get(entry_id)
        if existing_index is not None:
            if offers[existing_index].get("gatewayManaged"):
                order = offers[existing_index].get("order", existing_index + 1)
                offers[existing_index] = _site_offer(entry, order)
            continue
        offers.append(_site_offer(entry, len(offers) + 1))
    return offers, review


def sync_catalog_to_site(exported: dict[str, Any], site_repo: str | Path) -> dict[str, Any]:
    site_path = Path(site_repo)
    offers_path = site_path / "data" / "offers.json"
    review_path = site_path / "data" / "review-queue.json"
    if not offers_path.exists():
        raise FileNotFoundError(offers_path)
    offers = json.loads(offers_path.read_text(encoding="utf-8"))
    existing_review = json.loads(review_path.read_text(encoding="utf-8")) if review_path.exists() else []
    merged_offers, new_review = merge_into_site_offers(offers, exported)
    published_ids = {item.get("id") for item in exported.get("published", [])}
    review_by_id = {item.get("id"): item for item in existing_review if item.get("id")}
    review_by_id.update({item.get("id"): item for item in new_review if item.get("id")})
    for item_id in published_ids:
        review_by_id.pop(item_id, None)
    review = list(review_by_id.values())
    offers_text = json.dumps(merged_offers, ensure_ascii=False, indent=2) + "\n"
    review_text = json.dumps(review, ensure_ascii=False, indent=2) + "\n"
    changed = offers_text != offers_path.read_text(encoding="utf-8") or (
        not review_path.exists() or review_text != review_path.read_text(encoding="utf-8")
    )
    if changed:
        offers_path.write_text(offers_text, encoding="utf-8")
        review_path.write_text(review_text, encoding="utf-8")
    return {
        "changed": changed,
        "offers_path": str(offers_path),
        "review_path": str(review_path),
        "published": len(exported.get("published", [])),
        "review": len(review),
    }


def _site_offer(entry: dict[str, Any], order: int) -> dict[str, Any]:
    register = entry.get("register")
    docs_url = entry.get("docsUrl") or register
    endpoint = entry["apiEndpoint"]
    date = entry.get("lastVerifiedAt") or "1970-01-01"
    return {
        "id": entry["id"], "order": order, "date": date,
        "name": entry.get("name") or entry["model"], "providerMark": entry.get("provider", "AI")[:2].upper(),
        "provider": entry.get("provider") or entry.get("providerId"), "providerMeta": "Gateway observed",
        "model": entry["model"], "modelMeta": "OpenAI-compatible API",
        "type": ["api", "free"], "productType": "api", "capabilities": ["model_api"],
        "usageGuide": {
            "summary": "通过统一 API 调用该模型",
            "prerequisites": ["Provider 账号", "API Key"],
            "steps": ["打开官方入口注册并创建 API Key", "将模型加入本地网关后调用"],
            "examples": {"curl": f"curl {endpoint} -H 'Authorization: Bearer $API_KEY'"},
            "endpoint": endpoint, "method": "POST", "authentication": "Bearer API key", "docsUrl": docs_url,
        },
        "kicker": "FREE API", "badges": ["FREE", "LOCAL GATEWAY"],
        "freeSummary": entry.get("freeSummary") or "Free plan; provider limits apply",
        "validitySummary": "Provider free-plan limits", "accessSummary": "Check provider availability",
        "checkedSummary": f"Gateway check / {date}", "title": entry.get("name") or entry["model"],
        "why": "This model was exported from a locally configured FreeLLM Gateway route.",
        "mechanism": entry.get("freeSummary") or "Provider free plan", "validity": "Check provider terms",
        "access": "Provider account and API key", "command": f"curl {endpoint}",
        "register": register, "registerLabel": "Register at provider", "links": [["Official registration", register]],
        "originCountry": "Unknown", "availability": "Check provider terms", "freeMechanism": "free_rate_limited",
        "quota": entry.get("freeSummary") or "Provider limits", "renewal": "Check provider terms",
        "phoneRequired": "unknown", "cardRequired": "unknown", "commercialUse": "check provider terms",
        "sourceUrls": [url for url in (register, docs_url) if url],
        "evidence": "Imported from a local gateway public catalog export.", "status": "verified",
        "confidence": "medium", "lastVerifiedAt": date, "checkedBy": "gateway", "notes": "gatewayManaged=true",
        "gatewayManaged": True,
    }


def _public_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        return None
    return value
