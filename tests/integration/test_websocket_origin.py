"""
整合測試：WebSocket 握手檢查 Origin
測試範圍：
  WS /api/v1/ws/{file_uid}
  WS /api/v1/ws/{file_uid}/tasks/{task_uuid}（連線中斷之後接回任務）
  WS /api/v1/batch/ws/{batch_id}
  WS /api/v1/batch/ws/{batch_id}/reattach（連線中斷之後接回批次）

漏洞重現：瀏覽器的 WebSocket 不受同源政策與 CORS 保護，任何網站的頁面都能
連進本機後端、提交轉錄請求並收看任務進度與結果。
規則：有 Origin 標頭時，必須與伺服器自身的 host:port 同源，或在
CORS_ALLOWED_ORIGINS 允許清單內；否則以 1008 拒絕。沒有 Origin 的非瀏覽器客戶端放行。
"""
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import get_settings

WS_PATHS = [
    "/api/v1/ws/uid-origin-test",
    "/api/v1/ws/uid-origin-test/tasks/task-origin-test",
    "/api/v1/batch/ws/batch-origin-test",
    "/api/v1/batch/ws/batch-origin-test/reattach",
]


def _assert_rejected(client: TestClient, path: str, headers: dict):
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(path, headers=headers):
            pass
    assert exc_info.value.code == 1008


def _assert_accepted(client: TestClient, path: str, headers: dict):
    # 握手成功即代表放行；離開 with 時由客戶端正常關閉
    with client.websocket_connect(path, headers=headers):
        pass


# ─── 拒絕 ────────────────────────────────────────────────────────────────────

class TestRejectsForeignOrigin:
    @pytest.mark.parametrize("path", WS_PATHS)
    @pytest.mark.parametrize("origin", [
        "http://evil.example",
        "null",                              # sandbox iframe / file:// 頁面
        "http://testserver.evil.example",    # 前綴相同的其他網域
        "http://localhost:5173.evil.example",
        "http://testserver:8080",            # 同主機不同 port
        "https://testserver",                # 同主機不同 scheme（預設 port 不同）
        "",
    ])
    def test_rejected(self, client: TestClient, path, origin):
        _assert_rejected(client, path, {"Origin": origin})

    @pytest.mark.parametrize("path", WS_PATHS)
    def test_rejected_through_vite_proxy(self, client: TestClient, path):
        """Vite proxy（changeOrigin）把 Host 改成後端位址、Origin 原封不動轉送：
        惡意頁面經由 dev server 連線一樣會被擋。"""
        _assert_rejected(client, path, {
            "Host": "backend-service:8000",
            "Origin": "http://evil.example",
        })


# ─── 放行 ────────────────────────────────────────────────────────────────────

class TestAcceptsTrustedOrigin:
    @pytest.mark.parametrize("path", WS_PATHS)
    def test_same_origin(self, client: TestClient, path):
        _assert_accepted(client, path, {"Origin": "http://testserver"})

    @pytest.mark.parametrize("path", WS_PATHS)
    def test_same_origin_standalone_launcher(self, client: TestClient, path):
        """免安裝模式：launcher 開 http://127.0.0.1:<port>，頁面與 WS 同源。"""
        _assert_accepted(client, path, {
            "Host": "127.0.0.1:53123",
            "Origin": "http://127.0.0.1:53123",
        })

    @pytest.mark.parametrize("path", WS_PATHS)
    def test_allowlisted_origin_through_vite_proxy(self, client: TestClient, path):
        """Docker 模式開發時：瀏覽器在 Vite dev server，Host 被 proxy 改成後端位址，
        靠允許清單放行。"""
        origins = get_settings().cors_origins
        assert origins, "預設允許清單不應為空"
        for origin in origins:
            _assert_accepted(client, path, {
                "Host": "backend-service:8000",
                "Origin": origin,
            })

    @pytest.mark.parametrize("path", WS_PATHS)
    def test_without_origin_header(self, client: TestClient, path):
        _assert_accepted(client, path, {})
