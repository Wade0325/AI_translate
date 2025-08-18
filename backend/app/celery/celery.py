from celery import Celery
import os
from dotenv import load_dotenv

# 在 Celery 應用程式初始化之前載入 .env 檔案
load_dotenv()


# 從環境變數中讀取 Redis 的位置
# 如果沒有設定，則預設為 localhost
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", "6379")

# --- 修正開始 ---
# 從環境變數中讀取資料庫的 URL
# 這個修正後的邏輯可以正確處理 'postgresql://' 和 'postgresql+psycopg2://' 兩種前綴
DATABASE_URL_FROM_ENV = os.getenv(
    "DATABASE_URL", "postgresql+psycopg2://user:password@localhost/dbname")

if DATABASE_URL_FROM_ENV.startswith("postgresql+psycopg2://"):
    DATABASE_URL_FOR_CELERY = DATABASE_URL_FROM_ENV.replace(
        "postgresql+psycopg2://", "db+postgresql://")
elif DATABASE_URL_FROM_ENV.startswith("postgresql://"):
    DATABASE_URL_FOR_CELERY = DATABASE_URL_FROM_ENV.replace(
        "postgresql://", "db+postgresql://")
else:
    # 如果是其他資料庫，直接使用
    DATABASE_URL_FOR_CELERY = DATABASE_URL_FROM_ENV
# --- 修正結束 ---


# 建立 Celery 實例
# 我們將 main 參數設為 'app'，這將是我們 Celery worker 的命名空間。
celery_app = Celery(
    "app",
    broker=f"redis://{REDIS_HOST}:{REDIS_PORT}/0",
    backend=DATABASE_URL_FOR_CELERY,
    include=["app.celery.task"]  # 自動發現任務的模組
)

# Celery 的設定
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Taipei",
    enable_utc=True,
    # 任務結果的過期時間，設定為一天 (86400秒)
    result_expires=86400,
)

if __name__ == "__main__":
    celery_app.start()
