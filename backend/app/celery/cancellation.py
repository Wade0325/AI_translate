"""轉錄任務取消機制。

取消流程是合作式的：API 取消端點設置旗標，task 啟動前與 asr.py 的檢查點
輪詢旗標自行中止（solo pool / 執行緒都無法強制終止執行中的任務）。

- docker 模式：旗標存 Redis，橫跨三個行程（FastAPI、Docker gevent worker、
  主機端 solo GPU worker）共享，TTL 需大於 celery visibility_timeout
- standalone 模式：全部在同一行程內，旗標用 in-memory dict + Lock 即可，
  行程生命週期即旗標生命週期

``task_id:{file_uid}`` 記錄最近一次派發的 task id，供 revoke 使用；
重跑同一檔案時會被新 id 覆蓋。
"""

from __future__ import annotations

import threading
from typing import Optional

from app.core.config import get_settings


if get_settings().is_standalone:
    _lock = threading.Lock()
    _cancel_flags: set[str] = set()
    _task_ids: dict[str, str] = {}

    def request_cancel(file_uid: str) -> None:
        with _lock:
            _cancel_flags.add(file_uid)

    def is_cancel_requested(file_uid: str) -> bool:
        with _lock:
            return file_uid in _cancel_flags

    def clear_cancel_flag(file_uid: str) -> None:
        with _lock:
            _cancel_flags.discard(file_uid)

    def register_task_id(file_uid: str, task_id: str) -> None:
        with _lock:
            _task_ids[file_uid] = task_id

    def get_task_id(file_uid: str) -> Optional[str]:
        with _lock:
            return _task_ids.get(file_uid)

else:
    import redis

    from app.celery.celery import celery_app

    _redis_client = redis.from_url(celery_app.conf.broker_url)

    _CANCEL_KEY = "transcription:cancel:{file_uid}"
    _TASK_ID_KEY = "transcription:task_id:{file_uid}"
    # 比 celery visibility_timeout（12h）長，確保被重派的任務啟動時旗標仍在
    _TTL_SECONDS = 24 * 60 * 60

    def request_cancel(file_uid: str) -> None:
        _redis_client.set(
            _CANCEL_KEY.format(file_uid=file_uid), "1", ex=_TTL_SECONDS)

    def is_cancel_requested(file_uid: str) -> bool:
        try:
            return _redis_client.exists(
                _CANCEL_KEY.format(file_uid=file_uid)) > 0
        except redis.RedisError:
            # 查不到 Redis 時寧可讓任務繼續，也不要誤取消
            return False

    def clear_cancel_flag(file_uid: str) -> None:
        _redis_client.delete(_CANCEL_KEY.format(file_uid=file_uid))

    def register_task_id(file_uid: str, task_id: str) -> None:
        _redis_client.set(
            _TASK_ID_KEY.format(file_uid=file_uid), task_id, ex=_TTL_SECONDS)

    def get_task_id(file_uid: str) -> Optional[str]:
        value = _redis_client.get(_TASK_ID_KEY.format(file_uid=file_uid))
        return value.decode() if value else None
