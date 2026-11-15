"""本機 API 的存取限制：哪些請求能進來、API 文件開不開（#16 Q4、Q8a、Q8d、Q8e；#341 第 5 點）。

兩種執行模式分開設定：

- 免安裝模式（使用者拿到的版本）：
  - 只接受 Host 是 ``127.0.0.1`` 或 ``localhost`` 的請求（HTTP 與 WebSocket）。DNS rebinding
    的請求，Host 是攻擊者的網域，瀏覽器卻當成同源，CORS 與 Origin 檢查都擋不住。不比對埠：
    網域一換，主機名就對不上了。
  - 不掛 CORS，WebSocket 也只接受同源。前端由本服務同源提供，用不到跨來源；沿用開發用的
    清單（``http://localhost:5173``）的話，電腦上任何跑在那個埠的網頁都能讀 API 的回應。
  - 會改資料的請求（GET、HEAD、OPTIONS 以外）只收 app 自己的頁面送的
    （:class:`SameOriginWriteMiddleware`）。API 沒有使用者驗證，別的網站的頁面不該能替使用者送出
    寫入請求；做在這一層，現有與之後加的寫入端點都不必各自處理。
  - 沒有 ``/docs`` 與 ``/redoc``：開啟時會向 cdn.jsdelivr.net、fonts.googleapis.com 等第三方
    要資源（ADR-0005）。``/openapi.json`` 不連外，照樣保留。
- Docker 模式（開發用）：CORS 與 WebSocket 都照 ``CORS_ALLOWED_ORIGINS``，不帶憑證（前端沒有
  用 cookie）。Host 白名單跟著 #22（埠要不要只綁 127.0.0.1）再定。不加只收自己頁面的寫入請求那一層
  （#341）：前端經 Vite proxy 呼叫 /api，對瀏覽器而言是同源請求，CORS 的 ``allow_methods`` 沒有 PATCH
  也不受影響。
"""

from __future__ import annotations

from typing import Optional, TypedDict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import Headers
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import Settings
from app.utils.logger import setup_logger
from app.websocket.origin import WebSocketOriginMiddleware, is_origin_allowed

logger = setup_logger(__name__)

STANDALONE_HOSTS = ("127.0.0.1", "localhost")
"""免安裝模式接受的 Host：launcher 開 ``http://127.0.0.1:<port>``，uvicorn 也只綁 127.0.0.1。"""

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
"""不改資料的請求方法；其他方法（POST、PUT、PATCH、DELETE……）都當成寫入請求。"""

OWN_PAGE_FETCH_SITES = frozenset({"same-origin", "none"})
"""``Sec-Fetch-Site`` 可以接受的值：同源的頁面送的，或使用者自己發起的（例如在網址列輸入）。"""

FOREIGN_WRITE_REFUSED = "只接受 Mimiji 自己的頁面送出的請求"


def write_refusal(headers: Headers, scheme: str) -> Optional[str]:
    """一個寫入請求為什麼不收（寫進日誌的原因）；app 自己的頁面送的、或不是瀏覽器送的時候是 None。

    - ``Sec-Fetch-Site`` 有帶、而且不是 ``same-origin`` 或 ``none``：別的網站（``cross-site``），或
      同一台電腦上別的埠的頁面（``same-site``）送的。
    - ``Origin`` 有帶、而且和請求的 Host 不是同一個來源（scheme、主機與埠都要相同；``null`` 也不收）。
    - 兩個標頭都沒有：不是瀏覽器送的（例如測試與指令），照常處理。瀏覽器送寫入請求一定帶 ``Origin``。
    """
    site = headers.get("sec-fetch-site")
    if site is not None and site.strip().lower() not in OWN_PAGE_FETCH_SITES:
        return f"Sec-Fetch-Site={site.strip().lower()[:20]!r}"
    if not is_origin_allowed(headers.get("origin"), headers.get("host"), scheme, ()):
        return "Origin 和 Host 不同源"
    return None


class SameOriginWriteMiddleware:
    """免安裝模式：會改資料的 HTTP 請求只收 app 自己的頁面送的，其他回 403，不交給端點。

    不看 ``Content-Type``：不論 body 是 JSON、表單或沒有 body 都一樣擋。WebSocket 另有握手時的
    Origin 檢查（:class:`~app.websocket.origin.WebSocketOriginMiddleware`）。日誌只寫方法、路徑與
    不收的原因，不寫 ``Origin`` 的值：那是使用者開過的網站，日誌可能附在公開的問題回報裡。
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"].upper() not in SAFE_METHODS:
            reason = write_refusal(Headers(scope=scope), scope.get("scheme", "http"))
            if reason is not None:
                logger.warning(f"拒絕不是 app 自己的頁面送出的寫入請求: {scope['method']} "
                               f"{scope.get('path')!r}（{reason}）")
                await JSONResponse({"detail": FOREIGN_WRITE_REFUSED}, status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


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
        app.add_middleware(SameOriginWriteMiddleware)
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
