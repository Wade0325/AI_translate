from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from .models import Base, ModelConfiguration
from app.core.config import get_settings
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# 取得集中管理的設定
settings = get_settings()

# --- Database Setup ---
logger.info("Creating database engine...")

engine = create_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,  # 自動檢測斷線
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """初始化資料庫，建立資料表並插入預設資料"""
    logger.info("Initializing database...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # 檢查是否有任何記錄
        result = db.execute(select(ModelConfiguration).limit(1)).first()
        if result is None:
            # 插入預設的 'Google', 'Anthropic', 'OpenAI' 記錄
            default_providers = ['Google', 'Anthropic', 'OpenAI']
            for provider in default_providers:
                default_config = ModelConfiguration(provider=provider)
                db.add(default_config)
            db.commit()
            logger.info(
                f"Inserted default records {default_providers} into 'model_configurations' table."
            )
        logger.info("Database initialization complete.")
    finally:
        db.close()


def get_db():
    """FastAPI 依賴注入，提供資料庫 session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
