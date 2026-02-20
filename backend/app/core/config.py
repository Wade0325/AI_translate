from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# 計算 backend/.env 的絕對路徑，確保不受工作目錄影響
# __file__ = backend/app/core/config.py
# .parent = backend/app/core/
# .parent.parent = backend/app/
# .parent.parent.parent = backend/
ENV_FILE_PATH = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    """
    應用程式集中設定管理

    優先順序：環境變數 > .env 檔案 > 預設值
    """

    # Database
    database_url: str = "postgresql://user:password@localhost:5432/mydatabase"
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379

    # Celery
    celery_timezone: str = "Asia/Taipei"
    celery_result_expires: int = 86400

    # App
    temp_uploads_dir: str = "temp_uploads"

    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH if ENV_FILE_PATH.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def redis_url(self) -> str:
        """Redis 連線 URL"""
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    @property
    def celery_backend_url(self) -> str:
        """轉換 DATABASE_URL 為 Celery 相容格式"""
        if self.database_url.startswith("postgresql+psycopg2://"):
            return self.database_url.replace("postgresql+psycopg2://", "db+postgresql://")
        elif self.database_url.startswith("postgresql://"):
            return self.database_url.replace("postgresql://", "db+postgresql://")
        return self.database_url


@lru_cache()
def get_settings() -> Settings:
    """
    取得應用程式設定（單例模式）

    使用 lru_cache 確保每個進程只建立一次 Settings 實例
    """
    return Settings()
