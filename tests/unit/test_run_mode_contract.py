"""執行模式的契約測試：同一組測試跑行程內轉接器與 Redis 轉接器（fakeredis）。

涵蓋兩者共有的行為：狀態廣播與訂閱、取消旗標的要求／查詢／清除、任務登記與查詢、
任務結束時清掉登記與旗標。
Celery 本身的派送與撤銷不納入；行程內執行緒池的派送、撤銷與重試見 test_local_executor.py。
"""
import asyncio
from contextlib import aclosing, asynccontextmanager, suppress
from datetime import datetime

import fakeredis
import fakeredis.aioredis
import pytest

from app.runtime.celery_redis import CeleryRedisRunMode
from app.runtime.in_process import InProcessRunMode
from app.runtime.run_mode import RegisteredTask


def _in_process():
    return InProcessRunMode(concurrency=1)


def _redis():
    server = fakeredis.FakeServer()
    return CeleryRedisRunMode(
        fakeredis.FakeRedis(server=server),
        lambda: fakeredis.aioredis.FakeRedis(server=server, decode_responses=True),
    )


@pytest.fixture(params=[_in_process, _redis], ids=["in_process", "redis"])
def mode(request):
    m = request.param()
    yield m
    m.close()


# ── 取消旗標 ────────────────────────────────────────────────────────────

def test_cancel_flag_lifecycle(mode):
    assert mode.is_cancel_requested("f1") is False
    mode.request_cancel("f1")
    assert mode.is_cancel_requested("f1") is True
    # 其他檔案不受影響
    assert mode.is_cancel_requested("f2") is False
    mode.clear_cancel("f1")
    assert mode.is_cancel_requested("f1") is False
    # 重複清除不報錯
    mode.clear_cancel("f1")


def test_cancel_request_is_idempotent(mode):
    mode.request_cancel("f1")
    mode.request_cancel("f1")
    mode.clear_cancel("f1")
    assert mode.is_cancel_requested("f1") is False


# ── 任務登記 ────────────────────────────────────────────────────────────

def test_task_registration(mode):
    assert mode.registered_task("f1") is None
    mode.register_task("f1", "task-a", can_terminate=True)
    assert mode.registered_task("f1") == RegisteredTask("task-a", can_terminate=True)
    # 同一檔案再開任務時覆蓋
    mode.register_task("f1", "task-b", can_terminate=False)
    assert mode.registered_task("f1") == RegisteredTask("task-b", can_terminate=False)
    assert mode.registered_task("f2") is None


def test_empty_task_id_liveness_is_unknown(mode):
    assert mode.is_alive("") is None


def test_task_ended_clears_its_registration_and_cancel_flag(mode):
    mode.register_task("f1", "task-a", can_terminate=False)
    mode.request_cancel("f1")

    mode.task_ended("f1", "task-a")

    assert mode.registered_task("f1") is None
    assert mode.is_cancel_requested("f1") is False
    mode.task_ended("f1", "task-a")  # 重複收尾不報錯


def test_task_ended_leaves_a_newer_task_of_the_same_file_alone(mode):
    # 同一個檔案已經派送了新的任務，舊任務才收尾：不能清掉新任務的登記與取消
    mode.register_task("f1", "task-b", can_terminate=False)
    mode.request_cancel("f1")

    mode.task_ended("f1", "task-a")

    assert mode.registered_task("f1").task_id == "task-b"
    assert mode.is_cancel_requested("f1") is True


def test_task_ended_without_a_registration_clears_the_cancel_flag(mode):
    mode.request_cancel("f1")

    mode.task_ended("f1", "task-a")

    assert mode.is_cancel_requested("f1") is False


def test_redis_registration_written_before_the_upgrade_is_still_found():
    # 升級前（Docker 模式，登記留在 Redis 最多 24 小時）登記的只有 task_id：照樣找得到、
    # 收尾時照樣清掉；不知道能不能強制終止，就當成不能
    server = fakeredis.FakeServer()
    client = fakeredis.FakeRedis(server=server)
    client.set("transcription:task_id:f1", "task-a")
    mode = CeleryRedisRunMode(
        client, lambda: fakeredis.aioredis.FakeRedis(server=server, decode_responses=True))

    assert mode.registered_task("f1") == RegisteredTask("task-a", can_terminate=False)
    mode.task_ended("f1", "task-a")
    assert mode.registered_task("f1") is None


# ── 狀態廣播與訂閱 ──────────────────────────────────────────────────────

@asynccontextmanager
async def _subscription(mode):
    """在背景訂閱，把收到的訊息放進佇列；暖身到訂閱生效後才交出佇列。

    對訂閱 generator 套逾時會把它取消掉，所以由背景 task 消費，測試只對佇列設逾時。
    """
    inbox: asyncio.Queue = asyncio.Queue()

    async def pump():
        async with aclosing(mode.subscribe()) as messages:
            async for msg in messages:
                inbox.put_nowait(msg)

    task = asyncio.create_task(pump())
    try:
        # 反覆廣播暖身訊息直到收到：之後廣播的訊息保證送得到
        for _ in range(40):
            await asyncio.to_thread(mode.publish, {"client_id": "warmup"})
            try:
                await asyncio.wait_for(inbox.get(), 0.05)
                break
            except asyncio.TimeoutError:
                continue
        else:
            raise AssertionError("訂閱端一直沒收到暖身訊息")
        yield _Inbox(inbox)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


class _Inbox:
    def __init__(self, queue):
        self._queue = queue

    async def next(self):
        """下一則非暖身訊息。"""
        while True:
            msg = await asyncio.wait_for(self._queue.get(), 2.0)
            if msg.get("client_id") != "warmup":
                return msg


def test_published_messages_arrive_in_order(mode):
    async def main():
        async with _subscription(mode) as inbox:
            def worker():
                # 從 worker 執行緒廣播，對齊任務端的呼叫方式
                for i in range(5):
                    mode.publish({"client_id": "c1", "seq": i})

            await asyncio.to_thread(worker)
            return [await inbox.next() for _ in range(5)]

    received = asyncio.run(main())
    assert [m["seq"] for m in received] == [0, 1, 2, 3, 4]
    assert all(m["client_id"] == "c1" for m in received)


def test_published_message_is_json_roundtripped(mode):
    async def main():
        async with _subscription(mode) as inbox:
            await asyncio.to_thread(mode.publish, {
                "client_id": "c1",
                "status_text": "處理中",
                "ts": datetime(2026, 1, 1, 12, 0, 0),
                "result": {"segments": [1, 2]},
            })
            return await inbox.next()

    msg = asyncio.run(main())
    assert msg["status_text"] == "處理中"
    assert msg["result"] == {"segments": [1, 2]}
    # datetime 經 default=str 轉為字串
    assert msg["ts"] == str(datetime(2026, 1, 1, 12, 0, 0))


def test_every_subscriber_receives_each_message(mode):
    async def main():
        async with _subscription(mode) as a, _subscription(mode) as b:
            await asyncio.to_thread(mode.publish, {"client_id": "c1", "seq": 1})
            return await a.next(), await b.next()

    first, second = asyncio.run(main())
    assert first == second == {"client_id": "c1", "seq": 1}


def test_publish_without_subscriber_is_dropped_silently(mode):
    # 沒有訂閱端時不拋例外
    mode.publish({"client_id": "nobody"})
