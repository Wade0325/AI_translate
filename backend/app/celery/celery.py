from celery import Celery
from celery.signals import worker_init

from app.core.config import get_settings
from app.runtime import run_mode

settings = get_settings()

celery_app = Celery(
    "app",
    broker=settings.redis_url,
    backend=settings.celery_backend_url,
    include=["app.celery.task", "app.celery.batch_task"]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone=settings.celery_timezone,
    enable_utc=True,
    task_track_started=True,
    result_expires=settings.celery_result_expires,
    # 本機的任務單檔可跑數小時；預設 1h visibility timeout 會讓執行中的
    # 任務被誤判逾時而重複派發（local_worker.bat 與 runtime/celery_redis.py 的旗標 TTL 依賴此值）
    broker_transport_options={"visibility_timeout": 12 * 60 * 60},
)


@worker_init.connect
def _select_run_mode(**_) -> None:
    """worker 啟動時就依執行模式選定轉接器，不等第一個任務；選不了（例如設定錯）當場失敗。"""
    run_mode.get()


if __name__ == "__main__":
    celery_app.start()
