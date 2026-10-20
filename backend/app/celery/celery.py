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
    # 結果後端（Postgres）的 engine 是 Celery 自己建的，不經 app.database.session：同樣不在
    # 例外文字附上 SQL 參數，任務的回傳值有轉錄結果（#157）
    database_engine_options={"hide_parameters": True},
    # 本機的任務單檔可跑數小時；預設 1h visibility timeout 會讓執行中的
    # 任務被誤判逾時而重複派發（local_worker.bat 與 runtime/celery_redis.py 的旗標 TTL 依賴此值）
    broker_transport_options={"visibility_timeout": 12 * 60 * 60},
)

if __name__ == "__main__":
    celery_app.start()
