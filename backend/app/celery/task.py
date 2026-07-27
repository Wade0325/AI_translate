"""單檔轉錄 Celery 任務（docker 模式的入口 shim）。

任務本體在 `app.tasks.transcribe_core`；此處僅保留 Celery 裝飾器。
Celery 任務名由 module + 函式名決定，shim 留在原處原名，
broker 上的任務名因此不變，滾動部署時新舊 worker 可互通。
"""

from app.celery.celery import celery_app
from app.exceptions import GeminiTransientError
from app.tasks.transcribe_core import run_transcription


@celery_app.task(
    bind=True,
    autoretry_for=(GeminiTransientError,),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=60,
)
def transcribe_media_task(self, task_params_dict: dict):
    """單檔轉錄 Celery 任務：VAD 前處理 → 轉錄 → 格式轉換 → 計費 → 寫 DB。"""
    return run_transcription(task_params_dict, self.request.id)
