from fastapi.testclient import TestClient

from freellm_gateway.api import create_app
from freellm_gateway.models import ModelRoute
from freellm_gateway.service import ModelGateway


def test_admin_can_reorder_routes_and_non_admin_is_rejected():
    routes = [
        ModelRoute(id="first", provider_id="p", remote_model="m1", priority=1),
        ModelRoute(id="second", provider_id="p", remote_model="m2", priority=2),
    ]
    app = create_app(ModelGateway(routes, {}), api_token="api", admin_token="admin")
    client = TestClient(app)

    denied = client.post("/api/admin/routes/reorder", json={"ids": ["second", "first"]})
    response = client.post(
        "/api/admin/routes/reorder",
        headers={"Authorization": "Bearer admin"},
        json={"ids": ["second", "first"]},
    )

    assert denied.status_code == 401
    assert response.status_code == 200
    assert [route.id for route in app.state.gateway.routes] == ["second", "first"]
    assert [route.priority for route in app.state.gateway.routes] == [1, 2]


def test_admin_can_create_route_with_public_metadata():
    app = create_app(ModelGateway([], {}), api_token="api", admin_token="admin")
    client = TestClient(app)

    response = client.post(
        "/api/admin/routes",
        headers={"Authorization": "Bearer admin"},
        json={
            "id": "new-route", "provider_id": "p", "remote_model": "remote",
            "priority": 1, "public_url": "https://provider.example/register",
        },
    )

    assert response.status_code == 201
    assert response.json()["id"] == "new-route"
    assert app.state.gateway.routes[0].remote_model == "remote"


def test_admin_page_loads_before_admin_api_authentication():
    app = create_app(ModelGateway([], {}), api_token="api", admin_token="admin")
    client = TestClient(app)

    response = client.get("/admin")
    denied = client.get("/api/admin/routes")

    assert response.status_code == 200
    assert "Model Pool" in response.text
    assert 'id="auth-form"' in response.text
    assert "Request Routing" in response.text
    assert 'data-action="probe"' in response.text
    assert denied.status_code == 401
