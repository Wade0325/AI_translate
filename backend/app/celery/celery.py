from celery import Celery
from app.core.config import get_settings

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
    # 本地 GPU 任務單檔可跑數小時；預設 1h visibility timeout 會讓執行中的
    # 任務被誤判逾時而重複派發（local_worker.bat 與 cancellation.py 依賴此值）
    broker_transport_options={"visibility_timeout": 12 * 60 * 60},
)

if __name__ == "__main__":
    celery_app.start()
