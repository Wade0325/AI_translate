import json
import os
from pathlib import Path
from typing import Optional, List
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, Session
from .models import Base, ModelConfiguration, TranscriptionLog
from app.schemas.schemas import ModelConfigurationSchema
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# --- Database Setup ---
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://user:password@localhost:5432/mydatabase"
)
logger.info(f"Connecting to database...")

engine = create_engine(
    SQLALCHEMY_DATABASE_URL
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """初始化資料庫，建立資料表並插入預設資料"""
    logger.info(f"Initializing database...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # 檢查是否有任何記錄
        result = db.execute(select(ModelConfiguration).limit(1)).first()
        if result is None:
            # 插入預設的 'Google', 'Anthropic', 'OpenAI' 記錄
            default_providers = ['Google', 'Anthropic', 'OpenAI']
            for provider in default_providers:
                default_config = ModelConfiguration(interface_name=provider)
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
