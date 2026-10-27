"""本機 API 的存取限制：哪些請求能進來、API 文件開不開（#16 Q4、Q8a、Q8d、Q8e）。

兩種執行模式分開設定：

- 免安裝模式（使用者拿到的版本）：
  - 只接受 Host 是 ``127.0.0.1`` 或 ``localhost`` 的請求（HTTP 與 WebSocket）。DNS rebinding
    的請求，Host 是攻擊者的網域，瀏覽器卻當成同源，CORS 與 Origin 檢查都擋不住。不比對埠：
    網域一換，主機名就對不上了。
  - 不掛 CORS，WebSocket 也只接受同源。前端由本服務同源提供，用不到跨來源；沿用開發用的
    清單（``http://localhost:5173``）的話，電腦上任何跑在那個埠的網頁都能讀 API 的回應。
  - 沒有 ``/docs`` 與 ``/redoc``：開啟時會向 cdn.jsdelivr.net、fonts.googleapis.com 等第三方
    要資源（ADR-0005）。``/openapi.json`` 不連外，照樣保留。
- Docker 模式（開發用）：CORS 與 WebSocket 都照 ``CORS_ALLOWED_ORIGINS``，不帶憑證（前端沒有
  用 cookie）。Host 白名單跟著 #22（埠要不要只綁 127.0.0.1）再定。
"""

from __future__ import annotations

from typing import TypedDict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import Settings
from app.websocket.origin import WebSocketOriginMiddleware

STANDALONE_HOSTS = ("127.0.0.1", "localhost")
"""免安裝模式接受的 Host：launcher 開 ``http://127.0.0.1:<port>``，uvicorn 也只綁 127.0.0.1。"""


class ApiDocsUrls(TypedDict):
    docs_url: str | None
    redoc_url: str | None


def api_docs_urls(settings: Settings) -> ApiDocsUrls:
    """``FastAPI(...)`` 的 ``docs_url`` 與 ``redoc_url``：免安裝模式不提供。"""
    if settings.is_standalone:
        return {"docs_url": None, "redoc_url": None}
    return {"docs_url": "/docs", "redoc_url": "/redoc"}


def restrict_access(app: FastAPI, settings: Settings) -> None:
    """依執行模式掛上存取限制的 middleware。後加的在外層，所以 Host 不對的請求最先被擋掉。"""
    if settings.is_standalone:
        app.add_middleware(WebSocketOriginMiddleware, allowed_origins=())
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(STANDALONE_HOSTS))
        return
    # Docker 模式開發時前端經 Vite proxy 呼叫 /api，對瀏覽器而言是同源請求，不靠 CORS；
    # 清單只影響真正跨來源的呼叫。不用 *
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["DELETE", "GET", "POST", "PUT"],
        allow_headers=["*"],
    )
    # WebSocket 不受 CORS 保護：握手時 Origin 必須同源或在同一份允許清單內
    app.add_middleware(WebSocketOriginMiddleware, allowed_origins=settings.cors_origins)
