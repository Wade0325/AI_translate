"""
整合測試：CORS 只放行設定裡的來源
測試範圍：main.app 的 CORSMiddleware

漏洞重現：原本 allow_origins=["*"] 搭配 allow_credentials=True，
任何網站的頁面都能跨站呼叫本機 API 並讀到回應（例如設定、歷史紀錄）。
"""
from fastapi.testclient import TestClient

from app.core.config import get_settings

EVIL_ORIGIN = "http://evil.example"


def _allowed_origin() -> str:
    return get_settings().cors_origins[0]


class TestCorsAllowList:
    def test_simple_request_from_unknown_origin_gets_no_cors_header(self, client: TestClient):
        response = client.get("/api/v1/health", headers={"Origin": EVIL_ORIGIN})
        assert response.status_code == 200
        assert "access-control-allow-origin" not in response.headers

    def test_preflight_from_unknown_origin_is_refused(self, client: TestClient):
        response = client.options("/api/v1/setting/models", headers={
            "Origin": EVIL_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        })
        assert response.headers.get("access-control-allow-origin") is None

    def test_allowed_origin_gets_cors_header(self, client: TestClient):
        origin = _allowed_origin()
        response = client.get("/api/v1/health", headers={"Origin": origin})
        assert response.headers.get("access-control-allow-origin") == origin
        # 前端沒有用 cookie，跨來源請求不帶憑證（#16 Q8a）
        assert "access-control-allow-credentials" not in response.headers

    def test_preflight_from_allowed_origin_succeeds(self, client: TestClient):
        origin = _allowed_origin()
        response = client.options("/api/v1/setting/models", headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        })
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == origin

    def test_request_without_origin_is_unaffected(self, client: TestClient):
        """不帶 Origin 的請求（非瀏覽器客戶端、同源 GET）不受影響。"""
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
