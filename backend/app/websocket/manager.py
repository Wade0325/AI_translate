import asyncio
import json
from fastapi import WebSocket
from typing import Dict
import redis.asyncio as redis
import os

from app.utils.logger import setup_logger

logger = setup_logger(__name__)

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}"


class ConnectionManager:
    """管理 WebSocket 連線和 Redis 訊息監聽"""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        logger.info(f"新的 WebSocket 連線: {client_id}")

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
            logger.info(f"WebSocket 連線關閉: {client_id}")

    async def send_personal_message(self, message: dict, client_id: str):
        if client_id in self.active_connections:
            websocket = self.active_connections[client_id]
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"傳送訊息至客戶端 {client_id} 時發生錯誤: {e}")

    async def redis_listener(self):
        try:
            r = redis.from_url(REDIS_URL, encoding="utf-8",
                               decode_responses=True)
            pubsub = r.pubsub()
            await pubsub.subscribe("transcription_updates")
            logger.info("已訂閱 'transcription_updates' Redis 頻道。")

            while True:
                try:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if message:
                        logger.info(f"從 Redis 收到訊息: {message['data']}")
                        data = json.loads(message['data'])
                        client_id = data.get("client_id")
                        if client_id:
                            await self.send_personal_message(data, client_id)
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Redis 監聽器發生錯誤: {e}")
                    await asyncio.sleep(5)  # 發生錯誤時等待一段時間再重試
        except redis.ConnectionError as e:
            logger.error(f"無法連接至 Redis: {e}")


# 建立一個單例 manager
manager = ConnectionManager()
