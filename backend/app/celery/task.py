"""單檔轉錄 Celery 任務（Docker 模式的入口 shim）。

任務本體在 `app.tasks.transcribe_core`；此處僅保留 Celery 裝飾器。
Celery 任務名由 module + 函式名決定，shim 留在原處原名，
broker 上的任務名因此不變，滾動部署時新舊 worker 可互通。
"""

from celery.signals import task_revoked

from app.celery.celery import celery_app
from app.tasks.transcribe_core import abandon_transcription, run_transcription


@celery_app.task(bind=True)
def transcribe_media_task(self, task_params_dict: dict):
    """單檔轉錄 Celery 任務：去靜音 → 轉錄 → 格式轉換 → 計費 → 寫 DB。

    不自動重試：暫時錯誤在分段轉錄裡重試出錯的那一段，和免安裝模式相同。
    """
    return run_transcription(task_params_dict, self.request.id)


@task_revoked.connect(sender=transcribe_media_task)
def _finish_revoked(request=None, terminated=False, **_) -> None:
    """worker 丟掉被撤銷的任務（還在佇列中）：任務不會再執行，照樣收尾。

    執行中被強制終止（``terminated``）的不在這裡收尾：任務自己的生命週期在 finally 收尾。
    單檔任務只有取消端點會撤銷，所以一律當成使用者取消。
    """
    if terminated:
        return
    abandon_transcription(request.args[0], request.id, cancelled=True)
