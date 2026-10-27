"""
整合測試：本機 API 依執行模式限制存取（#16 Q4、Q8a、Q8d、Q8e）
測試範圍：app.core.api_access（main.app 用它掛 middleware、決定 API 文件的網址）

免安裝模式（使用者拿到的版本）：
  - 只接受 Host 是 127.0.0.1 或 localhost 的請求。漏洞重現：DNS rebinding 的請求，Host 是攻擊者
    的網域，瀏覽器卻當成同源，CORS 與 WebSocket 的 Origin 檢查都擋不住
  - 不掛 CORS，WebSocket 只接受同源。漏洞重現：沿用開發用的清單（http://localhost:5173）時，
    電腦上任何跑在 5173 埠的網頁都能讀 API 的回應、連上 WebSocket
  - 沒有 /docs 與 /redoc：開啟時會向 cdn.jsdelivr.net、fonts.googleapis.com 等第三方要資源
Docker 模式（開發用）：照 CORS_ALLOWED_ORIGINS，但不帶憑證；Host 不限（跟著 #22）。
"""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDenialResponse
from starlette.websockets import WebSocketDisconnect

from app.core.api_access import api_docs_urls, restrict_access
from app.core.config import Settings

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
VITE_ORIGIN = "http://localhost:5173"


def _settings(mode: str) -> Settings:
    return Settings(_env_file=None, app_mode=mode)


def _client(mode: str) -> TestClient:
    """照 main.py 的做法組一個小 app：一個 HTTP 端點、一個 WebSocket 端點。

    HTTP 請求的 Host 預設是 launcher 開的 127.0.0.1:8000；TestClient 的 WebSocket 不看
    base_url，Host 一律是 testserver，所以 WebSocket 的測試自己帶 Host。
    """
    settings = _settings(mode)
    app = FastAPI(**api_docs_urls(settings))

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok"}

    @app.websocket("/api/v1/ws/{file_uid}")
    async def ws(websocket: WebSocket, file_uid: str):
        await websocket.accept()
        await websocket.close()

    restrict_access(app, settings)
    return TestClient(app, base_url="http://127.0.0.1:8000")


def _preflight(client: TestClient, origin: str):
    return client.options("/api/v1/health", headers={
        "Origin": origin,
        "Access-Control-Request-Method": "GET",
    })


# ─── 免安裝模式 ──────────────────────────────────────────────────────────────

class TestStandaloneHostAllowList:
    @pytest.mark.parametrize("host", ["127.0.0.1:8000", "127.0.0.1:53123", "localhost:8000"])
    def test_loopback_host_is_served(self, host):
        response = _client("standalone").get("/api/v1/health", headers={"Host": host})
        assert response.status_code == 200

    @pytest.mark.parametrize("host", [
        "evil.example:8000",          # DNS rebinding：攻擊者的網域解析到 127.0.0.1
        "evil.example",
        "127.0.0.1.evil.example:8000",
        "192.168.1.10:8000",          # 區網位址：免安裝版只綁 127.0.0.1，不會有這種請求
    ])
    def test_other_host_is_refused(self, host):
        response = _client("standalone").get("/api/v1/health", headers={"Host": host})
        assert response.status_code == 400

    def test_websocket_with_other_host_is_refused(self):
        with pytest.raises(WebSocketDenialResponse):
            with _client("standalone").websocket_connect(
                    "/api/v1/ws/uid", headers={"Host": "evil.example:8000",
                                               "Origin": "http://evil.example:8000"}):
                pass


class TestStandaloneHasNoCors:
    def test_vite_dev_server_origin_gets_no_cors_header(self):
        response = _client("standalone").get("/api/v1/health", headers={"Origin": VITE_ORIGIN})
        assert response.status_code == 200
        assert "access-control-allow-origin" not in response.headers

    def test_preflight_from_vite_dev_server_is_not_allowed(self):
        response = _preflight(_client("standalone"), VITE_ORIGIN)
        assert "access-control-allow-origin" not in response.headers

    def test_websocket_from_vite_dev_server_is_refused(self):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with _client("standalone").websocket_connect(
                    "/api/v1/ws/uid", headers={"Host": "127.0.0.1:8000", "Origin": VITE_ORIGIN}):
                pass
        assert exc_info.value.code == 1008

    def test_websocket_from_same_origin_is_accepted(self):
        """launcher 開 http://127.0.0.1:<port>，頁面與 WebSocket 同源。"""
        with _client("standalone").websocket_connect(
                "/api/v1/ws/uid", headers={"Host": "127.0.0.1:53123",
                                           "Origin": "http://127.0.0.1:53123"}):
            pass


class TestStandaloneHasNoApiDocs:
    @pytest.mark.parametrize("path", ["/docs", "/redoc"])
    def test_docs_are_gone(self, path):
        assert _client("standalone").get(path).status_code == 404

    def test_openapi_schema_stays(self):
        """/openapi.json 不連外，留給寫腳本的人。"""
        assert _client("standalone").get("/openapi.json").status_code == 200


# ─── Docker 模式 ─────────────────────────────────────────────────────────────

class TestDockerMode:
    def test_allowed_origin_gets_cors_header_without_credentials(self):
        response = _client("docker").get("/api/v1/health", headers={"Origin": VITE_ORIGIN})
        assert response.headers.get("access-control-allow-origin") == VITE_ORIGIN
        assert "access-control-allow-credentials" not in response.headers

    def test_preflight_does_not_allow_credentials(self):
        response = _preflight(_client("docker"), VITE_ORIGIN)
        assert response.status_code == 200
        assert "access-control-allow-credentials" not in response.headers

    def test_host_is_not_restricted(self):
        """Vite proxy 把 Host 改成 backend-service:8000；Docker 模式的 Host 白名單跟著 #22。"""
        response = _client("docker").get("/api/v1/health",
                                          headers={"Host": "backend-service:8000"})
        assert response.status_code == 200

    @pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
    def test_docs_stay(self, path):
        assert _client("docker").get(path).status_code == 200


# ─── main.app 真的照執行模式組起來 ───────────────────────────────────────────

def test_main_app_in_standalone_mode(tmp_path):
    """另開一個行程，以免安裝模式 import main：模式在 import 時決定，同一個行程換不了。"""
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("<html>app-shell</html>", encoding="utf-8")
    probe = textwrap.dedent("""
        from fastapi.testclient import TestClient
        from main import app

        client = TestClient(app, base_url="http://127.0.0.1:8000")
        docs = client.get("/docs")
        redoc = client.get("/redoc")
        print("PROBE docs", docs.status_code, "swagger" in docs.text.lower(), "app-shell" in docs.text)
        print("PROBE redoc", redoc.status_code, "redoc" in redoc.text.lower(), "app-shell" in redoc.text)
        print("PROBE openapi", client.get("/openapi.json").status_code)
        print("PROBE rebinding", client.get("/api/v1/health",
                                            headers={"Host": "evil.example:8000"}).status_code)
        cors = client.get("/api/v1/health", headers={"Origin": "http://localhost:5173"})
        print("PROBE cors", cors.status_code, cors.headers.get("access-control-allow-origin"))
    """)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "APP_MODE": "standalone",
           "AIT_DATA_DIR": str(tmp_path / "data"), "AIT_STATIC_DIR": str(static)}
    env.pop("DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=BACKEND_DIR, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=120, env=env)

    assert result.returncode == 0, result.stderr
    probe_lines = [line for line in result.stdout.splitlines() if line.startswith("PROBE ")]
    assert probe_lines == [
        # /docs 與 /redoc 不再是 API 文件，交給前端的路由（退回 index.html）
        "PROBE docs 200 False True",
        "PROBE redoc 200 False True",
        "PROBE openapi 200",
        "PROBE rebinding 400",
        "PROBE cors 200 None",
    ], result.stdout
