import json

from freellm_gateway.catalog import export_catalog, merge_into_site_offers
from freellm_gateway.models import ModelRoute, Provider


def test_catalog_export_separates_published_and_review_and_removes_private_fields(tmp_path):
    provider = Provider(
        id="groq", name="Groq", protocol="openai", base_url="https://api.groq.com/v1", official_url="https://groq.com"
    )
    routes = [
        ModelRoute(
            id="groq-live", provider_id="groq", remote_model="llama-3", priority=1,
            public_url="https://console.groq.com", public_docs_url="https://console.groq.com/docs",
            free_summary="Free plan", catalog_status="published", credential_ref="keyring://private/live",
        ),
        ModelRoute(
            id="groq-new", provider_id="groq", remote_model="new-model", priority=2,
            public_url="https://console.groq.com", catalog_status="draft", credential_ref="keyring://private/new",
        ),
    ]
    output = tmp_path / "catalog-export.json"

    export_catalog(routes, {provider.id: provider}, output, generated_at="2026-09-08T00:00:00Z")
    data = json.loads(output.read_text(encoding="utf-8"))

    assert data["schemaVersion"] == 1
    assert [item["model"] for item in data["published"]] == ["llama-3"]
    assert [item["model"] for item in data["review"]] == ["new-model"]
    assert "credential_ref" not in output.read_text(encoding="utf-8")
    assert "keyring" not in output.read_text(encoding="utf-8")
    assert data["published"][0]["register"] == "https://console.groq.com"


def test_merge_into_site_offers_adds_gateway_offer_and_preserves_existing_entry():
    exported = {
        "schemaVersion": 1,
        "generatedAt": "2026-09-08T00:00:00Z",
        "published": [{
            "id": "groq-live", "providerId": "groq", "provider": "Groq",
            "model": "llama-3", "name": "Llama via Groq", "register": "https://groq.com",
            "docsUrl": "https://groq.com/docs", "apiEndpoint": "https://api.groq.com/v1/chat/completions",
            "capabilities": ["chat"], "freeSummary": "Free plan", "lastVerifiedAt": "2026-09-08",
            "catalogStatus": "published",
        }],
        "review": [{"id": "groq-new", "model": "new-model", "catalogStatus": "draft"}],
    }
    existing = [{"id": "handwritten", "name": "Manual entry"}]

    offers, review = merge_into_site_offers(existing, exported)

    assert [item["id"] for item in offers] == ["handwritten", "groq-live"]
    assert offers[0]["name"] == "Manual entry"
    assert offers[1]["gatewayManaged"] is True
    assert review == [{"id": "groq-new", "model": "new-model", "catalogStatus": "draft"}]


def test_merge_refreshes_existing_gateway_managed_offer():
    exported = {
        "published": [{
            "id": "managed", "providerId": "p", "provider": "Provider", "model": "new-model",
            "name": "Updated model", "register": "https://provider.test", "apiEndpoint": "https://api.test/v1/chat/completions",
            "capabilities": ["chat"], "freeSummary": "Updated free plan", "lastVerifiedAt": "2026-09-08",
        }],
        "review": [],
    }
    existing = [{"id": "managed", "name": "Old model", "gatewayManaged": True, "order": 4}]

    offers, _ = merge_into_site_offers(existing, exported)

    assert len(offers) == 1
    assert offers[0]["name"] == "Updated model"
    assert offers[0]["order"] == 4
