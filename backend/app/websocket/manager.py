import asyncio
import json
from contextlib import suppress
from typing import Dict, Optional

import redis.asyncio as redis
from fastapi import WebSocket

from app.core.config import get_settings
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

settings = get_settings()
REDIS_URL = settings.redis_url

# Redis listener 重連退避（秒）
_RECONNECT_INITIAL_DELAY = 1
_RECONNECT_MAX_DELAY = 30


class ConnectionManager:
    """管理 WebSocket 連線和 Redis 訊息監聽。"""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self._listener_task: Optional[asyncio.Task] = None
        self._stopping = False

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        # 若同一 client_id 已存在舊連線，先關閉避免洩漏
        old = self.active_connections.get(client_id)
        if old is not None and old is not websocket:
            logger.info(f"偵測到重複 client_id={client_id}，關閉舊 WebSocket 連線")
            with suppress(Exception):
                await old.close(code=1000)
        self.active_connections[client_id] = websocket
        logger.info(f"新的 WebSocket 連線: {client_id}")

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
            logger.info(f"WebSocket 連線關閉: {client_id}")

    async def send_personal_message(self, message: dict, client_id: str):
        websocket = self.active_connections.get(client_id)
        if websocket is None:
            return
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"傳送訊息至客戶端 {client_id} 時發生錯誤: {e}")
            # 送訊息失敗代表連線已斷或不健康，從表中移除並嘗試關閉
            self.disconnect(client_id)
            with suppress(Exception):
                await websocket.close(code=1011)

    async def redis_listener(self):
        """訂閱 Redis pub/sub 並轉送至對應 WebSocket。

        外層 while 確保 Redis 短暫斷線時自動以指數退避重連，
        直到 shutdown() 被呼叫設定 _stopping=True。
        """
        delay = _RECONNECT_INITIAL_DELAY
        while not self._stopping:
            r = None
            pubsub = None
            try:
                r = redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
                pubsub = r.pubsub()
                await pubsub.subscribe("transcription_updates")
                logger.info("已訂閱 'transcription_updates' Redis 頻道。")
                delay = _RECONNECT_INITIAL_DELAY  # 連線成功後重置退避

                while not self._stopping:
                    try:
                        message = await pubsub.get_message(
                            ignore_subscribe_messages=True, timeout=1.0
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.error(f"Redis get_message 發生錯誤: {e}")
                        break  # 跳出內層，由外層重連

                    if not message:
                        continue

                    try:
                        logger.info(f"從 Redis 收到訊息: {message['data']}")
                        data = json.loads(message["data"])
                        client_id = data.get("client_id")
                        if client_id:
                            await self.send_personal_message(data, client_id)
                    except Exception as e:
                        logger.error(f"處理 Redis 訊息時發生錯誤: {e}")

            except asyncio.CancelledError:
                logger.info("Redis listener 被取消")
                raise
            except Exception as e:
                logger.error(f"Redis listener 連線失敗: {e}")
            finally:
                if pubsub is not None:
                    with suppress(Exception):
                        await pubsub.unsubscribe("transcription_updates")
                    with suppress(Exception):
                        await pubsub.close()
                if r is not None:
                    with suppress(Exception):
                        await r.close()

            if self._stopping:
                break
            logger.info(f"Redis listener 將在 {delay}s 後重連...")
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                raise
            delay = min(delay * 2, _RECONNECT_MAX_DELAY)

    def start(self) -> asyncio.Task:
        """由 lifespan 呼叫，啟動背景 listener。"""
        self._stopping = False
        if self._listener_task is None or self._listener_task.done():
            self._listener_task = asyncio.create_task(self.redis_listener())
            logger.info("WebSocket Redis 監聽器已在背景啟動。")
        return self._listener_task

    async def shutdown(self):
        """由 lifespan 呼叫，乾淨地關閉 listener 與所有 WebSocket。"""
        self._stopping = True

        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._listener_task

        # 關閉所有殘餘的 WebSocket
        for client_id, ws in list(self.active_connections.items()):
            with suppress(Exception):
                await ws.close(code=1001)
            self.active_connections.pop(client_id, None)
        logger.info("ConnectionManager shutdown complete")


# 建立一個單例 manager
manager = ConnectionManager()
