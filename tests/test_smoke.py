from fastapi.testclient import TestClient

from freellm_gateway.main import app


def test_health_endpoint_reports_ok():
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
