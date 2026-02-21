from sqlalchemy import create_engine, select, text, inspect as sa_inspect
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
    settings.sync_database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,  # 自動檢測斷線
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _migrate_add_missing_columns():
    """檢查並自動新增 models 中有但 DB 表中缺少的欄位"""
    inspector = sa_inspect(engine)
    for table_name, table in Base.metadata.tables.items():
        if not inspector.has_table(table_name):
            continue  # 新表由 create_all 處理
        existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
        for column in table.columns:
            if column.name not in existing_columns:
                col_type = column.type.compile(engine.dialect)
                sql = f'ALTER TABLE {table_name} ADD COLUMN {column.name} {col_type}'
                logger.info(f"Auto-migration: {sql}")
                with engine.begin() as conn:
                    conn.execute(text(sql))


def init_db():
    """初始化資料庫，建立資料表並插入預設資料"""
    logger.info("Initializing database...")
    Base.metadata.create_all(bind=engine)

    # 自動新增 models 中新增但 DB 中缺少的欄位
    _migrate_add_missing_columns()

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
