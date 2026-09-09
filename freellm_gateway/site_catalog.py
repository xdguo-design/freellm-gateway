from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

import httpx


PUBLIC_FIELDS = (
    "id", "order", "date", "name", "providerMark", "provider", "model", "modelMeta",
    "productType", "capabilities", "usageGuide", "register", "registerLabel", "docsUrl",
    "apiEndpoint", "freeSummary", "validitySummary", "accessSummary", "badges",
    "originCountry", "availability", "freeMechanism", "quota", "renewal", "lastVerifiedAt",
)
MODEL_PRODUCT_TYPES = {"api", "open_weights", "payg", "free_model", "model_api"}


async def fetch_public_catalog(
    source_url: str,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    parsed = urlparse(source_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("catalog source must be an https URL")
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0))
    try:
        response = await client.get(source_url)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError:
        raise
    finally:
        if owns_client:
            await client.aclose()
    offers = payload.get("offers", payload) if isinstance(payload, dict) else payload
    if not isinstance(offers, list):
        raise ValueError("catalog response must contain an offers list")
    return [item for item in offers if isinstance(item, dict)]


def model_offers(offers: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for offer in offers:
        product_type = offer.get("productType")
        capabilities = set(offer.get("capabilities") or [])
        if product_type not in MODEL_PRODUCT_TYPES and not capabilities.intersection({"model_api", "open_weights"}):
            continue
        result.append({field: offer[field] for field in PUBLIC_FIELDS if field in offer})
    return sorted(result, key=lambda item: (item.get("order", 10**9), item.get("id", "")))
