"""local_bus（standalone 行程內狀態廣播）單元測試。"""
import asyncio
from datetime import datetime

from app.runtime import local_bus


def test_publish_roundtrips_through_queue():
    async def main():
        queue = asyncio.Queue()
        local_bus.bind(asyncio.get_running_loop(), queue)
        try:
            local_bus.publish({
                "client_id": "c1",
                "status_code": "PROCESSING",
                "ts": datetime(2026, 1, 1, 12, 0, 0),
            })
            return await asyncio.wait_for(queue.get(), timeout=1)
        finally:
            local_bus.unbind()

    msg = asyncio.run(main())
    assert msg["client_id"] == "c1"
    assert msg["status_code"] == "PROCESSING"
    # 與 Redis 路徑相同的序列化語意：datetime 經 default=str 轉為字串
    assert isinstance(msg["ts"], str)


def test_publish_without_bind_is_noop():
    local_bus.unbind()
    # 不應拋例外，只丟棄訊息
    local_bus.publish({"client_id": "c1"})
