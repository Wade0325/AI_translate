"""GET /api/v1/version：設定頁顯示的版本號（#85），和 /docs 上的版本號同一個來源。"""
from app.core.version import APP_VERSION


def test_version_endpoint_returns_the_app_version(client):
    response = client.get("/api/v1/version")

    assert response.status_code == 200
    assert response.json() == {"version": APP_VERSION}


def test_openapi_shows_the_same_version(client):
    assert client.get("/openapi.json").json()["info"]["version"] == APP_VERSION
