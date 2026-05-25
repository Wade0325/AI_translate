"""Celery 任務統一狀態廣播模組。

`task.py` 與 `batch_task.py` 都透過此模組將狀態更新 publish 到 Redis 的
``transcription_updates`` 頻道，由 `ConnectionManager` 轉發至對應 WebSocket。
"""

from __future__ import annotations

import json
from typing import Optional

import redis

from app.celery.celery import celery_app
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

CHANNEL = "transcription_updates"

# 與 FastAPI 端共用同一 Redis 設定
_redis_client = redis.from_url(celery_app.conf.broker_url)


def publish_status(
    client_id: str,
    task_uuid: str,
    status_text: str,
    status_code: str = "PROCESSING",
    *,
    file_uid: Optional[str] = None,
    result_data: Optional[dict] = None,
    extra: Optional[dict] = None,
) -> None:
    """向 Redis pub/sub 廣播狀態更新。

    Args:
        client_id: WebSocket 對應的 client_id（單檔轉錄為 file_uid，批次為 batch_id）。
        task_uuid: 任務唯一識別碼。
        status_text: 顯示給使用者的訊息。
        status_code: 機器可讀的狀態碼，例如 PROCESSING/COMPLETED/FAILED/BATCH_COMPLETED。
        file_uid: 批次任務中，單一檔案的識別碼。
        result_data: 任務完成時的結果 payload。
        extra: 其他需要併入訊息的欄位（例如 batch_id）。
    """
    message = {
        "client_id": client_id,
        "task_uuid": task_uuid,
        "status_code": status_code,
        "status_text": status_text,
    }
    if file_uid:
        message["file_uid"] = file_uid
    if result_data:
        message["result"] = result_data
    if extra:
        message.update(extra)

    try:
        _redis_client.publish(
            CHANNEL, json.dumps(message, default=str, ensure_ascii=False)
        )
    except Exception as e:
        logger.error(f"發布狀態更新至 Redis 時失敗: {e}")
