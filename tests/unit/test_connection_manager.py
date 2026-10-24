"""單元測試：WebSocket 連線的登記（websocket/manager.py 的 ConnectionManager，#203）。

同一個 key（單檔是 file_uid，批次是 batch_id）可能先後有兩條連線：例如重新轉錄時，伺服器還沒發現
舊連線已經斷了，新連線就連上來。舊連線之後的收尾只能關掉、移除自己那一條，不能動到新連線，
否則任務的狀態訊息就送不到畫面。
"""
import asyncio

from app.websocket.manager import ConnectionManager

STATUS = {"client_id": "uid", "status_code": "PROCESSING"}


class FakeWebSocket:
    """伺服器端的一條連線：記下送出的訊息與關閉碼。"""

    def __init__(self):
        self.sent = []
        self.close_code = None

    async def accept(self):
        pass

    async def send_json(self, message):
        self.sent.append(message)

    async def close(self, code=1000):
        self.close_code = code


class DiesWhileSending(FakeWebSocket):
    """送訊息時才發現連線已經斷了；``meanwhile`` 是送出失敗之前、還在等的期間發生的事。"""

    def __init__(self, meanwhile=None):
        super().__init__()
        self._meanwhile = meanwhile

    async def send_json(self, message):
        if self._meanwhile is not None:
            await self._meanwhile()
        raise ConnectionResetError("連線已經斷了")


def test_old_connection_cleanup_keeps_the_new_connection():
    manager = ConnectionManager()
    old, new = FakeWebSocket(), FakeWebSocket()

    async def main():
        await manager.connect(old, "uid")
        await manager.connect(new, "uid")
        manager.disconnect("uid", old)  # 舊連線的處理流程這時才收到斷線
        await manager.send_personal_message(STATUS, "uid")

    asyncio.run(main())
    assert new.sent == [STATUS]
    assert new.close_code is None


def test_failed_send_on_the_old_connection_keeps_the_new_connection():
    manager = ConnectionManager()
    new = FakeWebSocket()
    old = DiesWhileSending(meanwhile=lambda: manager.connect(new, "uid"))

    async def main():
        await manager.connect(old, "uid")
        # 送給舊連線的途中新連線登記上來，接著舊連線送失敗
        await manager.send_personal_message(STATUS, "uid")
        await manager.send_personal_message(STATUS, "uid")

    asyncio.run(main())
    assert new.sent == [STATUS]
    assert new.close_code is None


def test_closed_only_connection_leaves_nothing_registered():
    manager = ConnectionManager()
    ws = FakeWebSocket()

    async def main():
        await manager.connect(ws, "uid")
        manager.disconnect("uid", ws)
        await manager.send_personal_message(STATUS, "uid")

    asyncio.run(main())
    assert manager.active_connections == {}
    assert ws.sent == []


def test_failed_send_on_the_only_connection_closes_and_removes_it():
    manager = ConnectionManager()
    ws = DiesWhileSending()

    async def main():
        await manager.connect(ws, "uid")
        await manager.send_personal_message(STATUS, "uid")

    asyncio.run(main())
    assert manager.active_connections == {}
    assert ws.close_code == 1011
