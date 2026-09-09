import httpx
import pytest

from freellm_gateway.site_catalog import fetch_public_catalog, model_offers


@pytest.mark.asyncio
async def test_fetch_public_catalog_reads_freellm_json_without_secrets():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        "generatedAt": "2026-09-08",
        "offers": [{"id": "groq-free", "productType": "api", "register": "https://groq.com"}],
    }))
    async with httpx.AsyncClient(transport=transport) as client:
        offers = await fetch_public_catalog("https://freellm.top/data/offers.json", client=client)

    assert offers[0]["id"] == "groq-free"
    assert "secret" not in str(offers)


def test_model_offers_keeps_api_and_open_weight_resources():
    offers = [
        {"id": "api", "productType": "api"},
        {"id": "weights", "productType": "open_weights"},
        {"id": "ide", "productType": "free_ide"},
    ]

    assert [item["id"] for item in model_offers(offers)] == ["api", "weights"]


@pytest.mark.asyncio
async def test_fetch_public_catalog_rejects_non_https_source():
    with pytest.raises(ValueError):
        await fetch_public_catalog("http://freellm.top/data/offers.json")
