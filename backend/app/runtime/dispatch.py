"""任務派發薄層：依執行模式路由至 Celery（docker）或行程內執行器（standalone）。

api/transcription.py 與 api/batch.py 只依賴此模組派發／控制任務。
celery 相關 import 全部收在 docker 分支的函式內，standalone 模式因此
完全不需要 celery / redis / gevent / psycopg2 套件。
"""

from __future__ import annotations

import uuid

from app.core.config import get_settings
from app.exceptions import GeminiTransientError
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def _is_standalone() -> bool:
    return get_settings().is_standalone


def submit_transcription(task_params_dict: dict, queue: str) -> str:
    """派發單檔轉錄任務，回傳 task_id（同時是 TranscriptionLog 主鍵）。"""
    if _is_standalone():
        from app.runtime.executor import get_executor
        from app.tasks.transcribe_core import run_transcription

        # task_id 須先於執行產生：呼叫端要先 register_task_id 供取消使用
        task_id = str(uuid.uuid4())
        get_executor().submit(
            run_transcription,
            args=(task_params_dict, task_id),
            task_id=task_id,
            queue=queue,
            retry_on=(GeminiTransientError,),
        )
        return task_id

    from app.celery.task import transcribe_media_task
    async_result = transcribe_media_task.apply_async(
        args=[task_params_dict], queue=queue)
    return async_result.id


def submit_batch(task_params_dict: dict) -> str:
    """派發批次轉錄任務，回傳 task_id。"""
    if _is_standalone():
        from app.runtime.executor import get_executor
        from app.tasks.batch_core import run_batch

        task_id = str(uuid.uuid4())
        get_executor().submit(
            run_batch,
            args=(task_params_dict, task_id),
            task_id=task_id,
            retry_on=(GeminiTransientError,),
        )
        return task_id

    from app.celery.batch_task import batch_transcribe_task
    return batch_transcribe_task.delay(task_params_dict).id


def submit_recover(batch_id: str, api_key: str) -> str:
    """派發批次結果恢復任務（不重試，對齊 Celery 版 max_retries=0）。"""
    if _is_standalone():
        from app.runtime.executor import get_executor
        from app.tasks.batch_core import run_recover

        task_id = str(uuid.uuid4())
        get_executor().submit(
            run_recover, args=(batch_id, api_key), task_id=task_id)
        return task_id

    from app.celery.batch_task import batch_recover_task
    return batch_recover_task.delay(batch_id, api_key).id


def revoke_task(task_id: str, terminate: bool = False) -> None:
    """取消佇列中的任務。

    執行中的任務兩種模式都靠 cancellation 合作式旗標停止；
    ``terminate`` 僅 docker 模式的 gevent pool 支援（local solo pool 不支援）。
    """
    if _is_standalone():
        from app.runtime.executor import get_executor
        get_executor().revoke(task_id)
        return

    from app.celery.celery import celery_app
    celery_app.control.revoke(task_id, terminate=terminate)


def task_is_alive(task_id: str) -> bool | None:
    """檢查任務是否仍在執行。回傳 True=執行中, False=已結束/已死, None=無法判斷。"""
    if not task_id:
        return None

    if _is_standalone():
        from app.runtime.executor import get_executor
        return get_executor().is_alive(task_id)

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
