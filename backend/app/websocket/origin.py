"""WebSocket 握手的 Origin 檢查。

瀏覽器的 WebSocket 不受同源政策限制，也沒有 CORS 預檢：任何網站的頁面都能連
ws://localhost:8000/api/v1/...，提交轉錄請求、收看任務進度與結果。所以握手時檢查
Origin 標頭：

- 與伺服器自身同源（scheme、host、port 都相同；standalone 由本服務提供前端）→ 放行
- 在 CORS 允許清單（``CORS_ALLOWED_ORIGINS``）內 → 放行。docker 開發模式的
  Vite proxy 會把 Host 改成後端位址、Origin 原封不動，靠這條放行
- 其他來源 → 以 1008（policy violation）拒絕
- 沒有 Origin 標頭：非瀏覽器客戶端（瀏覽器一定會帶），放行

以 ASGI middleware 實作，所有 WebSocket 端點（含日後新增的）都會經過。
"""

from __future__ import annotations

from typing import Iterable, Optional
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocketClose

from app.utils.logger import setup_logger

logger = setup_logger(__name__)

_DEFAULT_PORTS = {"http": 80, "https": 443}
# WebSocket 的 scheme 對應到頁面的 scheme（ws 握手來自 http 頁面，wss 來自 https）
_WS_TO_HTTP = {"ws": "http", "wss": "https", "http": "http", "https": "https"}


def _normalize(origin: str) -> str:
    return origin.strip().rstrip("/").lower()


def _origin_tuple(origin: str) -> Optional[tuple[str, str, int]]:
    try:
        parts = urlsplit(origin.strip())
        scheme = parts.scheme.lower()
        if scheme not in _DEFAULT_PORTS or not parts.hostname:
            return None
        return scheme, parts.hostname.lower(), parts.port or _DEFAULT_PORTS[scheme]
    except ValueError:  # port 不是數字或超出範圍
        return None


def _server_tuple(host: str, ws_scheme: str) -> Optional[tuple[str, str, int]]:
    scheme = _WS_TO_HTTP.get(ws_scheme.lower())
    if scheme is None:
        return None
    try:
        parts = urlsplit(f"//{host.strip()}")
        if not parts.hostname:
            return None
        return scheme, parts.hostname.lower(), parts.port or _DEFAULT_PORTS[scheme]
    except ValueError:
        return None


def is_origin_allowed(
    origin: Optional[str],
    host: Optional[str],
    scheme: str,
    allowed_origins: Iterable[str],
) -> bool:
    """依上面的規則判斷握手的 Origin 是否可接受。"""
    if origin is None:
        return True
    if _normalize(origin) in {_normalize(o) for o in allowed_origins}:
        return True
    origin_tuple = _origin_tuple(origin)
    if origin_tuple is None or not host:
        return False
    return origin_tuple == _server_tuple(host, scheme)


class WebSocketOriginMiddleware:
    """拒絕 Origin 不符的 WebSocket 握手；HTTP 請求原樣放行（交給 CORSMiddleware）。"""

    def __init__(self, app: ASGIApp, allowed_origins: Iterable[str] = ()):
        self.app = app
        self.allowed_origins = [_normalize(o) for o in allowed_origins]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            headers = Headers(scope=scope)
            origin = headers.get("origin")
            if not is_origin_allowed(origin, headers.get("host"),
                                     scope.get("scheme", "ws"), self.allowed_origins):
                logger.warning(
                    f"拒絕來源不符的 WebSocket 連線: origin={origin!r} "
                    f"host={headers.get('host')!r} path={scope.get('path')}")
                await WebSocketClose(code=1008)(scope, receive, send)
                return
        await self.app(scope, receive, send)
