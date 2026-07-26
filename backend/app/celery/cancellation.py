"""轉錄任務取消機制（Redis 旗標）。

取消流程橫跨三個行程（FastAPI、Docker gevent worker、主機端 solo GPU worker），
以 Redis 為單一事實來源：

- API 取消端點設置 ``cancel:{file_uid}`` 旗標，並 revoke 佇列中的任務
- local provider 在 asr.py 的檢查點輪詢旗標，合作式中止
  （solo pool 不支援 terminate，執行中的任務只能靠這個機制停下）
- task.py 啟動時檢查旗標，攔截 revoke 廣播沒送達的情況（例如 worker 離線）
- ``task_id:{file_uid}`` 記錄最近一次派發的 Celery task id，供 revoke 使用；
  重跑同一檔案時會被新 id 覆蓋
"""

from __future__ import annotations

from typing import Optional

import redis

from app.celery.celery import celery_app

_redis_client = redis.from_url(celery_app.conf.broker_url)

_CANCEL_KEY = "transcription:cancel:{file_uid}"
_TASK_ID_KEY = "transcription:task_id:{file_uid}"
# 比 celery visibility_timeout（12h）長，確保被重派的任務啟動時旗標仍在
_TTL_SECONDS = 24 * 60 * 60


def request_cancel(file_uid: str) -> None:
    _redis_client.set(_CANCEL_KEY.format(file_uid=file_uid), "1", ex=_TTL_SECONDS)


def is_cancel_requested(file_uid: str) -> bool:
    try:
        return _redis_client.exists(_CANCEL_KEY.format(file_uid=file_uid)) > 0
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
