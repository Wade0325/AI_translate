"""批次轉錄 Celery 任務（Docker 模式的入口 shim）。

任務本體在 `app.tasks.batch_core`；此處僅保留 Celery 裝飾器與原任務名。
"""

from app.celery.celery import celery_app
from app.tasks.batch_core import run_batch, run_recover


@celery_app.task(bind=True)
def batch_transcribe_task(self, task_params_dict: dict):
    """批次轉錄的 Celery 任務。

    不自動重試：暫時錯誤在批次裡重做出錯的那一步，和免安裝模式相同；檔案都已經開始，重跑整個批次會
    替同一個音檔再開一個任務。
    """
    return run_batch(task_params_dict, self.request.id)


@celery_app.task(name="batch_recover_task", bind=True, max_retries=0)
def batch_recover_task(self, batch_id: str, api_key: str):
    """從 Celery worker 中恢復批次結果的 Task wrapper。"""
    return run_recover(batch_id, api_key)
