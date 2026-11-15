"""
整合測試：本機 API 依執行模式限制存取（#16 Q4、Q8a、Q8d、Q8e；#341 第 5 點）
測試範圍：app.core.api_access（main.app 用它掛 middleware、決定 API 文件的網址）

免安裝模式（使用者拿到的版本）：
  - 只接受 Host 是 127.0.0.1 或 localhost 的請求。漏洞重現：DNS rebinding 的請求，Host 是攻擊者
    的網域，瀏覽器卻當成同源，CORS 與 WebSocket 的 Origin 檢查都擋不住
  - 不掛 CORS，WebSocket 只接受同源。漏洞重現：沿用開發用的清單（http://localhost:5173）時，
    電腦上任何跑在 5173 埠的網頁都能讀 API 的回應、連上 WebSocket
  - 沒有 /docs 與 /redoc：開啟時會向 cdn.jsdelivr.net、fonts.googleapis.com 等第三方要資源
  - 會改資料的請求只收 app 自己的頁面送的（#341 第 5 點）：Origin 和 Host 不同源、或 Sec-Fetch-Site
    不是 same-origin／none 的回 403，不論 Content-Type；兩個標頭都沒有的（不是瀏覽器送的）照常處理
Docker 模式（開發用）：照 CORS_ALLOWED_ORIGINS，但不帶憑證；Host 不限（跟著 #22）；不加只收自己
頁面的寫入請求那一層。
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
OWN_ORIGIN = "http://127.0.0.1:8000"
"""launcher 開的頁面：TestClient 的 HTTP 請求預設的 Host 是 127.0.0.1:8000。"""
WRITE_METHODS = ["POST", "PUT", "PATCH", "DELETE"]


def _settings(mode: str) -> Settings:
    return Settings(_env_file=None, app_mode=mode)


def _client(mode: str, written: list | None = None) -> TestClient:
    """照 main.py 的做法組一個小 app：一個讀的 HTTP 端點、一個寫的 HTTP 端點（四種寫入方法，
    真的執行時記進 ``written``）、一個 WebSocket 端點。

    HTTP 請求的 Host 預設是 launcher 開的 127.0.0.1:8000；TestClient 的 WebSocket 不看
    base_url，Host 一律是 testserver，所以 WebSocket 的測試自己帶 Host。
    """
    settings = _settings(mode)
    app = FastAPI(**api_docs_urls(settings))

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok"}

    @app.api_route("/api/v1/things/{thing}", methods=WRITE_METHODS, include_in_schema=False)
    def write(thing: str):
        if written is not None:
            written.append(thing)
        return {"written": thing}

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


def _write(client: TestClient, method: str, headers: dict, content_type: str | None = None):
    if content_type is not None:
        headers = {**headers, "Content-Type": content_type}
    return client.request(method, "/api/v1/things/x", headers=headers,
                          content=b"" if content_type is None else b"a=1")


class TestStandaloneWritesOnlyFromOwnPage:
    @pytest.mark.parametrize("content_type", [
        None,                                  # 沒有 body
        "application/json",
        "text/plain",                          # 以下三種瀏覽器跨站送出時不必預檢
        "application/x-www-form-urlencoded",
        "multipart/form-data; boundary=x",
    ])
    @pytest.mark.parametrize("method", WRITE_METHODS)
    def test_other_site_origin_is_refused_before_the_endpoint(self, method, content_type):
        written = []
        response = _write(_client("standalone", written), method,
                          {"Origin": "http://other.example"}, content_type)

        assert response.status_code == 403
        assert response.json()["detail"] == "只接受 Mimiji 自己的頁面送出的請求"
        assert written == []

    @pytest.mark.parametrize("origin", [
        VITE_ORIGIN,                            # 同一台電腦上別的埠的頁面
        "http://127.0.0.1:8001",
        "https://127.0.0.1:8000",               # scheme 不同
        "http://127.0.0.1:8000.other.example",
        "null",                                 # 沙箱化的 iframe、本機檔案打開的頁面
        "not a url",
    ])
    @pytest.mark.parametrize("method", WRITE_METHODS)
    def test_origin_that_is_not_this_server_is_refused(self, method, origin):
        written = []
        assert _write(_client("standalone", written), method, {"Origin": origin}).status_code == 403
        assert written == []

    @pytest.mark.parametrize("site", ["cross-site", "same-site", "CROSS-SITE"])
    @pytest.mark.parametrize("method", WRITE_METHODS)
    def test_sec_fetch_site_other_than_own_page_is_refused(self, method, site):
        written = []
        client = _client("standalone", written)

        assert _write(client, method, {"Sec-Fetch-Site": site}).status_code == 403
        # Origin 看起來同源也一樣：兩項都要過
        assert _write(client, method, {"Sec-Fetch-Site": site, "Origin": OWN_ORIGIN},
                      "text/plain").status_code == 403
        assert written == []

    @pytest.mark.parametrize("headers", [
        pytest.param({"Origin": OWN_ORIGIN, "Sec-Fetch-Site": "same-origin"}, id="own-page"),
        pytest.param({"Origin": OWN_ORIGIN}, id="own-origin-only"),
        pytest.param({"Sec-Fetch-Site": "same-origin"}, id="same-origin-only"),
        pytest.param({"Sec-Fetch-Site": "none"}, id="user-initiated"),
        pytest.param({}, id="not-a-browser"),   # 測試與指令
    ])
    @pytest.mark.parametrize("method", WRITE_METHODS)
    def test_own_page_and_non_browser_writes_go_through(self, method, headers):
        written = []
        response = _write(_client("standalone", written), method, headers, "application/json")

        assert response.status_code == 200
        assert written == ["x"]

    def test_own_page_opened_as_localhost_on_another_port_goes_through(self):
        response = _client("standalone").post("/api/v1/things/x", headers={
            "Host": "localhost:53123", "Origin": "http://localhost:53123", "Sec-Fetch-Site": "same-origin"})
        assert response.status_code == 200

    def test_reads_are_not_affected(self):
        response = _client("standalone").get("/api/v1/health", headers={
            "Origin": "http://other.example", "Sec-Fetch-Site": "cross-site"})
        assert response.status_code == 200

    def test_other_host_is_still_refused_first(self):
        # DNS rebinding：Origin 和 Host 同源，但 Host 不是 127.0.0.1／localhost
        response = _client("standalone").post("/api/v1/things/x", headers={
            "Host": "other.example:8000", "Origin": "http://other.example:8000",
            "Sec-Fetch-Site": "same-origin"})
        assert response.status_code == 400

    def test_the_refusal_is_logged_without_the_origin(self, app_log):
        _write(_client("standalone"), "POST", {"Origin": "http://other.example"})

        refusals = [entry for entry in app_log if "寫入請求" in entry]
        assert len(refusals) == 1 and "/api/v1/things/x" in refusals[0]
        assert "other.example" not in refusals[0]


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

    @pytest.mark.parametrize("method", WRITE_METHODS)
    def test_writes_are_not_restricted_by_origin(self, method):
        """開發用，照 CORS 的設定；前端經 Vite proxy 呼叫是同源請求。"""
        written = []
        response = _write(_client("docker", written), method,
                          {"Origin": "http://other.example", "Sec-Fetch-Site": "cross-site"})
        assert response.status_code == 200
        assert written == ["x"]


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
        other = {"Origin": "http://other.example"}
        own = {"Origin": "http://127.0.0.1:8000", "Sec-Fetch-Site": "same-origin"}
        segment = "/api/v1/transcripts/not-a-uuid/segments/0000"
        print("PROBE patch", client.patch(segment, json={"text": "A"}, headers=other).status_code,
              client.patch(segment, json={"text": "A"}, headers=own).status_code,
              client.patch(segment, json={"text": "A"}).status_code)
        print("PROBE upload", client.post("/api/v1/upload", headers=other,
                                          files={"file": ("a.wav", b"RIFF", "audio/wav")}).status_code)
        print("PROBE settings", client.post("/api/v1/setting/models", headers=other,
                                            content=b"{}").status_code)
        print("PROBE delete", client.delete("/api/v1/history/" + "0" * 32,
                                            headers={"Sec-Fetch-Site": "cross-site"}).status_code)
        print("PROBE cancel", client.post("/api/v1/transcription/uid/cancel", headers=other).status_code)
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
        # 寫入請求只收 app 自己的頁面送的：別的網站送的不交給端點；自己的頁面與不是瀏覽器送的照常
        # 交給端點（任務 id 格式不對，所以是 400）
        "PROBE patch 403 400 400",
        "PROBE upload 403",
        "PROBE settings 403",
        "PROBE delete 403",
        "PROBE cancel 403",
    ], result.stdout
