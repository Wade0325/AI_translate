from pathlib import Path

from sqlalchemy import create_engine, event, select, text, inspect as sa_inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from .models import Base, ModelConfiguration
from app.core.config import get_settings
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

settings = get_settings()


def _create_engine(url: str):
    if url.startswith("sqlite"):
        # SQLite（standalone 模式）：QueuePool 參數不適用；
        # check_same_thread=False 允許 API 與 worker 執行緒共用連線池
        db_path = make_url(url).database
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        sqlite_engine = create_engine(
            url,
            connect_args={"check_same_thread": False, "timeout": 30},
        )

        @event.listens_for(sqlite_engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _record):
            # WAL 讓讀寫不互斥；busy_timeout 讓併發寫入等待而非立即失敗
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

        return sqlite_engine

    return create_engine(
        url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,  # 自動檢測斷線
    )


engine = _create_engine(settings.sync_database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _migrate_add_missing_columns():
    """檢查並自動新增 models 中有但 DB 表中缺少的欄位。

    僅處理 ADD COLUMN，無法處理改型別、改約束、刪欄。需要結構性變更時
    請手寫 SQL 並透過 ``migrations/*.sql`` 套用。
    """
    inspector = sa_inspect(engine)
    for table_name, table in Base.metadata.tables.items():
        if not inspector.has_table(table_name):
            continue  # 新表由 create_all 處理
        existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
        for column in table.columns:
            if column.name not in existing_columns:
                col_type = column.type.compile(engine.dialect)
                sql = f'ALTER TABLE {table_name} ADD COLUMN {column.name} {col_type}'
                logger.info(f"Auto-migrate column: {sql}")
                with engine.begin() as conn:
                    conn.execute(text(sql))


def _migrate_add_missing_indexes():
    """檢查並自動建立 ORM 上已宣告但 DB 中缺少的 index。

    僅做 CREATE INDEX IF NOT EXISTS；不處理重新命名或刪除。
    """
    inspector = sa_inspect(engine)
    for table_name, table in Base.metadata.tables.items():
        if not inspector.has_table(table_name):
            continue
        existing = {idx.get("name") for idx in inspector.get_indexes(table_name)}
        for index in table.indexes:
            if index.name in existing:
                continue
            columns = ", ".join(col.name for col in index.columns)
            sql = f'CREATE INDEX IF NOT EXISTS {index.name} ON {table_name} ({columns})'
            logger.info(f"Auto-migrate index: {sql}")
            with engine.begin() as conn:
                conn.execute(text(sql))


def init_db():
    """初始化資料庫，建立資料表並插入預設資料"""
    logger.info("Initializing database...")
    Base.metadata.create_all(bind=engine)

    # 自動補齊 ORM 與 DB 之間的欄位 / index 差異
    _migrate_add_missing_columns()
    _migrate_add_missing_indexes()

    db = SessionLocal()
    try:
        # 空資料庫時預先建立支援的 provider 設定列（save 為 upsert，此處僅為方便）
        result = db.execute(select(ModelConfiguration).limit(1)).first()
        if result is None:
            default_providers = ['Google', 'Local']
            for provider in default_providers:
                db.add(ModelConfiguration(provider=provider))
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
