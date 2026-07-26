from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# 設定檔搜尋順序：backend/.env → 專案根目錄/.env
# Docker 啟動時環境變數由 docker-compose 直接注入，此處為原生執行的備援。
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent

def _find_env_file() -> Path | None:
    for candidate in [_BACKEND_DIR / ".env", _PROJECT_ROOT / ".env"]:
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
        if self.database_url:
            return self.database_url

        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_server}:{self.postgres_port}/{self.postgres_db}"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379

    # Celery
    celery_timezone: str = "Asia/Taipei"
    celery_result_expires: int = 86400

    # App
    temp_uploads_dir: str = "temp_uploads"
    # VAD 除錯：保留切割產物供本機试听檢查（預設關閉）
    vad_keep_artifacts: bool = False
    vad_artifacts_dir: str = "vad_artifacts"

    # Transcription tuning
    # 單檔轉錄的最大可接受時長（秒）；超過此值且轉錄失敗時，會嘗試 VAD 分割重試
    transcription_max_duration_seconds: int = 180
    # Batch / Flex 推論的費用折扣率（0.5 表示原價 50%）
    batch_cost_discount: float = 0.5
    flex_cost_discount: float = 0.5
    # 語音佔比 >= 此閾值（預設 0.9）時跳過 VAD 預處理，直接用原檔轉錄；
    # 空白超過 10%（語音佔比 < 90%）才執行 VAD 靜音移除
    vad_speech_ratio_skip_threshold: float = 0.90
    # VAD 前處理後（或跳過 VAD 時的原檔）仍超過此時長（秒）的音檔，
    # 轉錄前先在最接近中點的靜音處對半切，遞迴直到每段低於閾值；0 = 停用
    long_audio_split_threshold_seconds: float = 900.0
    # 單檔紀錄卡在 PROCESSING 超過此時數即視為孤兒（worker 中斷後不會回寫狀態），
    # 後端啟動時標記為 FAILED；需大於最長的合理轉錄時間（本地模型長檔可達數小時）
    stale_processing_max_age_hours: int = 12

    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH if ENV_FILE_PATH else None,
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def redis_url(self) -> str:
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
