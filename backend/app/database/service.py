import json
from pathlib import Path
from typing import Optional, List
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from .models import Base, ModelConfiguration
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

# --- Repository Functions ---


def get_by_name(db: Session, interface_name: str) -> Optional[ModelConfiguration]:
    """根據 interface_name 獲取模型配置"""
    return db.query(ModelConfiguration).filter(ModelConfiguration.interface_name == interface_name).first()


def get_by_model_name(db: Session, model_name: str) -> Optional[ModelConfiguration]:
    """根據 model_name 獲取模型配置"""
    return db.query(ModelConfiguration).filter(ModelConfiguration.model_name == model_name).first()


def get_all_configs(db: Session) -> List[ModelConfiguration]:
    """獲取所有模型配置"""
    return db.query(ModelConfiguration).all()


def save_config(db: Session, config: ModelConfigurationSchema) -> ModelConfiguration:
    """保存或更新模型配置"""
    db_config = get_by_name(db, config.interface_name)
    if db_config:
        # 更新現有記錄
        db_config.api_keys_json = config.api_keys_json
        db_config.model_name = config.model_name
        db_config.prompt = config.prompt
    else:
        # 建立新記錄
        db_config = ModelConfiguration(
            interface_name=config.interface_name,
            api_keys_json=config.api_keys_json,
            model_name=config.model_name,
            prompt=config.prompt,
        )
        db.add(db_config)
    db.commit()
    db.refresh(db_config)
    return db_config
