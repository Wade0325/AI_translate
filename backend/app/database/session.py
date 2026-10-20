from pathlib import Path

from sqlalchemy import create_engine, event, select, text, inspect as sa_inspect
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from .models import Base, ModelConfiguration
from app.core.config import get_settings
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

settings = get_settings()


def _create_engine(url: str):
    # 兩種執行模式都設 hide_parameters：SQLAlchemy 的例外文字預設附上 SQL 參數，裡面有
    # 明文 API 金鑰、轉錄結果與檔名，例外一寫進 log 或回應就跟著出去（#157）。
    # 排查只能靠使用者附上的 log（ADR-0005），log 會被貼到公開的 GitHub Issues
    if url.startswith("sqlite"):
        # SQLite（免安裝模式）：QueuePool 參數不適用；
        # check_same_thread=False 允許 API 與 worker 執行緒共用連線池
        db_path = make_url(url).database
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        sqlite_engine = create_engine(
            url,
            connect_args={"check_same_thread": False, "timeout": 30},
            hide_parameters=True,
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
        hide_parameters=True,
    )


engine = _create_engine(settings.sync_database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def describe_db_error(error: Exception) -> str:
    """寫進 log 用的資料庫例外描述：例外類型與資料庫回報的原因，不含 SQL 參數與資料列。

    給讀寫使用者資料（例如 API 金鑰）的地方記錯誤用；HTTP 回應則給固定的訊息，不轉述例外。
    原因只取資料庫訊息的第一行：Postgres 在第一行之後附上的 DETAIL 可能是寫不進去的
    整列資料（例如 ``Failing row contains (…)``），裡面有金鑰或轉錄結果。

    不是資料庫回報的例外只記類型：它的訊息可能帶著請求的內容，例如 pydantic 的
    ValidationError 附上輸入值。這是隱私優先於排查方便的取捨：排查只能靠 log（ADR-0005），
    這類錯誤在 log 裡只看得到類型，要在本機重現才查得到位置。
    """
    if not isinstance(error, DBAPIError) or error.orig is None:
        return type(error).__name__
    cause = error.orig
    reason = next(iter(str(cause).splitlines()), "").strip()
    return f"{type(error).__name__}: ({type(cause).__module__}.{type(cause).__name__}) {reason}"


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
