"""執行模式的 Celery＋Redis 轉接器（Docker 模式）。

- 派送與撤銷：Celery（Docker 模式的 gevent worker、主機端 GPU worker 的 ``local_asr`` 佇列）
- 狀態廣播：Redis pub/sub 的 ``transcription_updates`` 頻道，訂閱端斷線時指數退避重連
- 取消旗標與任務登記：存 Redis，橫跨 FastAPI、gevent worker 與主機端 solo GPU worker
  三個行程共享；TTL 大於 celery visibility_timeout

Celery 專用的部分只留在這個轉接器裡；celery 在派送時才 import。
"""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from typing import Any, AsyncIterator, Callable, Optional

import redis

from app.runtime.run_mode import RegisteredTask
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

CHANNEL = "transcription_updates"

_CANCEL_KEY = "transcription:cancel:{file_uid}"
_TASK_ID_KEY = "transcription:task_id:{file_uid}"
# 比 celery visibility_timeout（12h）長，確保被重派的任務啟動時旗標仍在
_TTL_SECONDS = 24 * 60 * 60

# 訂閱端重連退避（秒）
_RECONNECT_INITIAL_DELAY = 1
_RECONNECT_MAX_DELAY = 30


class CeleryRedisRunMode:
    def __init__(self, client: Any, async_client_factory: Callable[[], Any]):
        """
        Args:
            client: 同步 Redis 用戶端（旗標、登記、發布）。
            async_client_factory: 建立 ``decode_responses=True`` 的 asyncio Redis 用戶端，
                每次（重）連線呼叫一次。
        """
        self._redis = client
        self._async_client_factory = async_client_factory

    @classmethod
    def from_url(cls, url: str) -> "CeleryRedisRunMode":
        import redis.asyncio as aioredis

        return cls(
            redis.from_url(url),
            lambda: aioredis.from_url(url, encoding="utf-8", decode_responses=True),
        )

    # ── 派送與控制 ────────────────────────────────────────────────
    def submit_transcription(self, task_id: str, task_params_dict: dict, queue: str) -> None:
        from app.celery.task import transcribe_media_task

        transcribe_media_task.apply_async(args=[task_params_dict], queue=queue, task_id=task_id)

    def submit_batch(self, task_params_dict: dict) -> str:
        from app.celery.batch_task import batch_transcribe_task

        return batch_transcribe_task.delay(task_params_dict).id

    def submit_recover(self, batch_id: str, api_key: str) -> str:
        from app.celery.batch_task import batch_recover_task

        return batch_recover_task.delay(batch_id, api_key).id

    def revoke(self, task_id: str, terminate: bool = False) -> None:
        from app.celery.celery import celery_app

        celery_app.control.revoke(task_id, terminate=terminate)

    def is_alive(self, task_id: str) -> Optional[bool]:
        if not task_id:
            return None
        try:
            from celery.result import AsyncResult

            from app.celery.celery import celery_app
            result = AsyncResult(task_id, app=celery_app)
            # STARTED = 正在執行（需要 task_track_started=True）
            # PENDING = 尚未開始 或 worker 已死 或 結果已過期
            # SUCCESS/FAILURE/REVOKED = 已結束
            if result.state == "STARTED":
                return True
            if result.state in ("SUCCESS", "FAILURE", "REVOKED"):
                return False
            # PENDING: 無法確定，交由呼叫端以任務存在時間輔助判斷
            return None
        except Exception as e:
            logger.warning(f"檢查 Celery 任務狀態失敗 ({task_id}): {e}")
            return None

    # ── 狀態廣播 ──────────────────────────────────────────────────
    def publish(self, message: dict) -> None:
        self._redis.publish(
            CHANNEL, json.dumps(message, default=str, ensure_ascii=False))

    async def subscribe(self) -> AsyncIterator[dict]:
        delay = _RECONNECT_INITIAL_DELAY
        while True:
            r = None
            pubsub = None
            try:
                r = self._async_client_factory()
                pubsub = r.pubsub()
                await pubsub.subscribe(CHANNEL)
                logger.info(f"已訂閱 '{CHANNEL}' Redis 頻道。")
                delay = _RECONNECT_INITIAL_DELAY  # 連線成功後重置退避

                while True:
                    try:
                        message = await pubsub.get_message(
                            ignore_subscribe_messages=True, timeout=1.0)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.error(f"Redis get_message 發生錯誤: {e}")
                        break  # 跳出內層，由外層重連

                    if not message:
                        continue
                    try:
                        data = json.loads(message["data"])
                    except Exception as e:
                        logger.error(f"解析 Redis 訊息時發生錯誤: {e}")
                        continue
                    yield data

            except asyncio.CancelledError:
                logger.info("Redis 訂閱被取消")
                raise
            except Exception as e:
                logger.error(f"Redis 訂閱連線失敗: {e}")
            finally:
                if pubsub is not None:
                    with suppress(Exception):
                        await pubsub.unsubscribe(CHANNEL)
                    with suppress(Exception):
                        await pubsub.aclose()
                if r is not None:
                    with suppress(Exception):
                        await r.aclose()

            logger.info(f"Redis 訂閱將在 {delay}s 後重連...")
            await asyncio.sleep(delay)
            delay = min(delay * 2, _RECONNECT_MAX_DELAY)

    # ── 取消旗標與任務登記 ────────────────────────────────────────
    def request_cancel(self, file_uid: str) -> None:
        self._redis.set(
            _CANCEL_KEY.format(file_uid=file_uid), "1", ex=_TTL_SECONDS)

    def is_cancel_requested(self, file_uid: str) -> bool:
        try:
            return self._redis.exists(_CANCEL_KEY.format(file_uid=file_uid)) > 0
        except redis.RedisError:
            # 查不到 Redis 時寧可讓任務繼續，也不要誤取消
            return False

    def clear_cancel(self, file_uid: str) -> None:
        self._redis.delete(_CANCEL_KEY.format(file_uid=file_uid))

    def register_task(self, file_uid: str, task_id: str, *, can_terminate: bool) -> None:
        value = json.dumps({"task_id": task_id, "can_terminate": can_terminate})
        self._redis.set(_TASK_ID_KEY.format(file_uid=file_uid), value, ex=_TTL_SECONDS)

    def registered_task(self, file_uid: str) -> Optional[RegisteredTask]:
        return _registration(self._redis.get(_TASK_ID_KEY.format(file_uid=file_uid)))

    def task_ended(self, file_uid: str, task_id: str) -> None:
        key = _TASK_ID_KEY.format(file_uid=file_uid)

        def clear(pipe) -> None:
            # WATCH 著登記：比對與刪除之間被改掉（新任務剛登記）時整段重來
            registered = _registration(pipe.get(key))
            if registered is not None and registered.task_id != task_id:
                return
            pipe.multi()
            pipe.delete(key, _CANCEL_KEY.format(file_uid=file_uid))

        self._redis.transaction(clear, key)

    # ── 生命週期 ──────────────────────────────────────────────────
    def close(self) -> None:
        with suppress(Exception):
            self._redis.close()


def _registration(value: Optional[bytes]) -> Optional[RegisteredTask]:
    """Redis 裡的任務登記；升級前登記的只有 task_id（不能強制終止）。"""
    if not value:
        return None
    try:
        data = json.loads(value)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return RegisteredTask(value.decode(), can_terminate=False)
    return RegisteredTask(str(data["task_id"]), bool(data.get("can_terminate")))
