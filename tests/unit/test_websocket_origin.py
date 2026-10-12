"""單元測試：WebSocket Origin 判斷（websocket/origin.py 的 is_origin_allowed）"""
import pytest

from app.websocket.origin import is_origin_allowed

ALLOWED = ["http://localhost:5173", "http://127.0.0.1:5173"]


@pytest.mark.parametrize("origin, host, scheme", [
    (None, "localhost:8000", "ws"),                     # 非瀏覽器客戶端
    ("http://localhost:8000", "localhost:8000", "ws"),
    ("HTTP://LocalHost:8000", "localhost:8000", "ws"),  # scheme／host 不分大小寫
    ("http://example.test", "example.test", "ws"),      # 預設 port 80
    ("https://example.test", "example.test", "wss"),    # 預設 port 443
    ("http://[::1]:8000", "[::1]:8000", "ws"),          # IPv6
    ("http://localhost:5173", "backend-service:8000", "ws"),   # 允許清單
    ("http://localhost:5173/", "backend-service:8000", "ws"),
])
def test_allowed(origin, host, scheme):
    assert is_origin_allowed(origin, host, scheme, ALLOWED) is True


@pytest.mark.parametrize("origin, host, scheme", [
    ("http://evil.example", "localhost:8000", "ws"),
    ("http://localhost:8001", "localhost:8000", "ws"),
    ("https://localhost:8000", "localhost:8000", "ws"),
    ("http://localhost:99999", "localhost:8000", "ws"),  # 不合法的 port
    ("file://", "localhost:8000", "ws"),
    ("null", "localhost:8000", "ws"),
    ("", "localhost:8000", "ws"),
    ("http://localhost:8000", None, "ws"),               # 沒有 Host 無從比對
])
def test_rejected(origin, host, scheme):
    assert is_origin_allowed(origin, host, scheme, ALLOWED) is False


def test_vite_origin_needs_allowlist():
    """清單清空後，經 Vite proxy（Host 已改成後端位址）的連線就不再放行。"""
    assert is_origin_allowed("http://localhost:5173", "backend-service:8000", "ws", []) is False
