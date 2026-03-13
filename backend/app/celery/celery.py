from celery import Celery
from app.core.config import get_settings

# 取得集中管理的設定
settings = get_settings()

# 建立 Celery 實例
# 我們將 main 參數設為 'app'，這將是我們 Celery worker 的命名空間。
celery_app = Celery(
    "app",
    broker=settings.redis_url,
    backend=settings.celery_backend_url,
    include=["app.celery.task", "app.celery.batch_task"]
)

# Celery 的設定
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone=settings.celery_timezone,
    enable_utc=True,
    task_track_started=True,
    # 任務結果的過期時間
    result_expires=settings.celery_result_expires,
)

if __name__ == "__main__":
    celery_app.start()
