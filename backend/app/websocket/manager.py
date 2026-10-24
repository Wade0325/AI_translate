import asyncio
from contextlib import aclosing, suppress
from typing import Dict, Optional

from fastapi import WebSocket

from app.utils.logger import setup_logger

logger = setup_logger(__name__)


class ConnectionManager:
    """管理 WebSocket 連線，並把執行模式的狀態廣播轉送給對應的連線。"""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self._listener_task: Optional[asyncio.Task] = None

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

    def disconnect(self, client_id: str, websocket: WebSocket):
        """把這條連線從登記移除。

        同一個 client_id 已經登記了之後連上的另一條連線時不動它：例如重新轉錄時，伺服器還沒發現
        舊連線斷了，新連線就連上來，舊連線之後才收尾（#203）。
        """
        if self.active_connections.get(client_id) is websocket:
            del self.active_connections[client_id]
            logger.info(f"WebSocket 連線關閉: {client_id}")

    async def close(self, client_id: str, websocket: WebSocket, code: int = 1000):
        """關掉這條連線並從登記移除；和 :meth:`disconnect` 一樣不動之後登記的另一條連線。

        這條連線可能已經被新連線換掉、在 :meth:`connect` 裡關掉了，所以關閉時的錯誤不往外丟。
        """
        self.disconnect(client_id, websocket)
        with suppress(Exception):
            await websocket.close(code=code)

    async def send_personal_message(self, message: dict, client_id: str):
        websocket = self.active_connections.get(client_id)
        if websocket is None:
            return
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"傳送訊息至客戶端 {client_id} 時發生錯誤: {e}")
            # 送訊息失敗代表連線已斷或不健康，從表中移除並嘗試關閉。等送出的期間可能已經有新連線
            # 登記上來，所以只移除、只關這條
            await self.close(client_id, websocket, code=1011)

    async def _listen(self):
        """訂閱執行模式的狀態廣播，轉送至對應 WebSocket，直到被取消。"""
        from app.runtime import run_mode

        async with aclosing(run_mode.get().subscribe()) as messages:
            async for data in messages:
                try:
                    # 完成訊息帶著整份字幕，只記摘要避免灌爆 log
                    logger.info(f"收到狀態訊息: {str(data)[:200]}")
                    client_id = data.get("client_id")
                    if client_id:
                        await self.send_personal_message(data, client_id)
                except Exception as e:
                    logger.error(f"處理狀態訊息時發生錯誤: {e}")

    def start(self) -> asyncio.Task:
        """由 lifespan 呼叫，在背景啟動狀態監聽器。"""
        if self._listener_task is None or self._listener_task.done():
            self._listener_task = asyncio.create_task(self._listen())
            logger.info("WebSocket 狀態監聽器已在背景啟動。")
        return self._listener_task

    async def shutdown(self):
        """由 lifespan 呼叫，乾淨地關閉 listener 與所有 WebSocket。"""
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


# 單例 manager
manager = ConnectionManager()
