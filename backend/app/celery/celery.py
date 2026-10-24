from celery import Celery
from celery.signals import worker_init

from app.core.config import get_settings
from app.runtime import run_mode
from app.database.session import without_db_details
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

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


@worker_init.connect
def on_worker_start(sender, **_) -> None:
    """worker 啟動時，在開始收任務之前：

    - 依執行模式選定轉接器，不等第一個任務；選不了（例如設定錯）當場失敗。
    - 消費預設佇列（批次跑在這裡）的 worker，把上傳中的批次記成失敗：之前在上傳的那個 worker
      已經停了（:func:`~app.tasks.batch_core.end_stopped_uploads`）。主機的 GPU worker 只消費
      ``local_asr``（``local_worker.bat``），不收。
    """
    run_mode.get()
    if sender.app.conf.task_default_queue not in sender.app.amqp.queues.consume_from:
        return
    from app.tasks import batch_core
    try:
        ended = batch_core.end_stopped_uploads()
    except Exception as e:
        # 收不了也照樣啟動，任務頁的批次照舊停在上傳中
        logger.error(f"worker 啟動時無法收掉上傳中的批次: {without_db_details(e)}")
        return
    if ended:
        logger.info(f"worker 啟動：{ended} 個上傳時停住的批次記成失敗")


if __name__ == "__main__":
    celery_app.start()
