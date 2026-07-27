"""standalone 模式 SPA 靜態檔服務測試：未知路徑退回 index.html。"""
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_spa_fallback_serves_index(tmp_path):
    from main import _SPAStaticFiles

    (tmp_path / "index.html").write_text("<html>app-shell</html>", encoding="utf-8")
    (tmp_path / "asset.js").write_text("console.log(1)", encoding="utf-8")

    app = FastAPI()
    app.mount("/", _SPAStaticFiles(directory=str(tmp_path), html=True))
    client = TestClient(app)

    # 實體檔案照常服務
    assert client.get("/asset.js").text == "console.log(1)"
    # SPA 路由（實體不存在）退回 index.html，讓 react-router 接手
    resp = client.get("/history")
    assert resp.status_code == 200
    assert "app-shell" in resp.text
    # API 未知路徑維持 404，不退回 index.html
    assert client.get("/api/v1/does-not-exist").status_code == 404
