"""standalone 模式的行程內狀態廣播通道（取代 Redis Pub/Sub）。

worker 執行緒呼叫 :func:`publish`，訊息經 ``call_soon_threadsafe`` 丟進
event loop 的 :class:`asyncio.Queue`，由 ``ConnectionManager.local_listener()``
消費後轉發至對應 WebSocket。
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

from app.utils.logger import setup_logger

logger = setup_logger(__name__)

_loop: Optional[asyncio.AbstractEventLoop] = None
_queue: Optional[asyncio.Queue] = None


def bind(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> None:
    """由 ConnectionManager 在 event loop 內呼叫，掛上消費佇列。"""
    global _loop, _queue
    _loop = loop
    _queue = queue


def unbind() -> None:
    global _loop, _queue
    _loop = None
    _queue = None


def publish(message: dict) -> None:
    """從任意執行緒發布狀態訊息。

    訊息先做 JSON round-trip，保持與 Redis 路徑（json.dumps → publish →
    json.loads）完全相同的序列化語意（datetime 等型別統一轉字串）。
    """
    if _loop is None or _queue is None:
        logger.warning("local_bus 尚未綁定 event loop，狀態訊息被丟棄")
        return
    payload = json.loads(json.dumps(message, default=str, ensure_ascii=False))
    try:
        _loop.call_soon_threadsafe(_queue.put_nowait, payload)
    except RuntimeError:
        # event loop 已關閉（應用程式 shutdown 中）
        logger.warning("event loop 已關閉，狀態訊息未送出")
