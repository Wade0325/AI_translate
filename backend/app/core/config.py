from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# 設定檔搜尋順序：backend/.env → 專案根目錄/.env.prod
# 本機開發和 Docker 都能用同一份設定
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent      # backend/
_PROJECT_ROOT = _BACKEND_DIR.parent                                # 專案根目錄

def _find_env_file() -> Path | None:
    for candidate in [_BACKEND_DIR / ".env", _PROJECT_ROOT / ".env.prod"]:
        if candidate.exists():
            return candidate
    return None

ENV_FILE_PATH = _find_env_file()


class Settings(BaseSettings):
    """
    應用程式集中設定管理

    優先順序：環境變數 > .env 檔案 > 預設值
    """

    # Database
    postgres_user: str = "user"
    postgres_password: str = "password"
    postgres_server: str = "localhost"
    postgres_port: str = "5432"
    postgres_db: str = "mydatabase"
    
    database_url: str | None = None
    db_pool_size: int = 10
    db_max_overflow: int = 20

    @property
    def sync_database_url(self) -> str:
        """取得同步資料庫連線 URL"""
        if self.database_url:
            return self.database_url
        
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_server}:{self.postgres_port}/{self.postgres_db}"

    @property
    def async_database_url(self) -> str:
        """取得非同步資料庫連線 URL (如果需要)"""
        url = self.sync_database_url
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://")
        return url


    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379

    # Celery
    celery_timezone: str = "Asia/Taipei"
    celery_result_expires: int = 86400

    # App
    temp_uploads_dir: str = "temp_uploads"

    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH if ENV_FILE_PATH else None,
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
        url = self.sync_database_url
        if url.startswith("postgresql+psycopg2://"):
            return url.replace("postgresql+psycopg2://", "db+postgresql://")
        elif url.startswith("postgresql://"):
            return url.replace("postgresql://", "db+postgresql://")
        return url


@lru_cache()
def get_settings() -> Settings:
    """
    取得應用程式設定（單例模式）

    使用 lru_cache 確保每個進程只建立一次 Settings 實例
    """
    return Settings()
