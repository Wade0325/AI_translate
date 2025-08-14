import json
from pathlib import Path
from typing import Optional, List
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from .models import Base, ModelConfiguration, TranscriptionLog
from app.schemas.schemas import ModelConfigurationSchema
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# --- Database Setup ---
DATABASE_URL = Path(__file__).resolve(
).parent.parent.parent / "model_settings.db"
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DATABASE_URL}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """初始化資料庫，建立資料表並插入預設資料"""
    logger.info(f"Initializing database at {DATABASE_URL}...")
    DATABASE_URL.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # 檢查是否有任何記錄
        if db.query(ModelConfiguration).count() == 0:
            # 插入預設的 'Google' 記錄
            default_google = ModelConfiguration(interface_name='Google')
            db.add(default_google)
            db.commit()
            logger.info(
                "Inserted default 'Google' record into 'model_configurations' table.")
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
