from fastapi.testclient import TestClient

from freellm_gateway.main import app


def test_health_endpoint_reports_ok():
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_allows_desktop_webview_origin():
    response = TestClient(app).get(
        "/health",
        headers={"Origin": "http://tauri.localhost"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://tauri.localhost"
