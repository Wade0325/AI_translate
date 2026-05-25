"""
測試全域 Fixture 設定
- 在所有 app 模組匯入前，先 mock 重量級依賴（torch、torchaudio 等）
- SQLite in-memory 資料庫（取代 PostgreSQL）
- 輕量 lifespan（略過 Redis / VAD 初始化）
"""
import sys
import pytest
from contextlib import asynccontextmanager
from unittest.mock import MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ─── 1. 在所有 app 模組被匯入之前，先 mock 重量級依賴 ──────────────────────
# 避免 torch / torchaudio / silero_vad 在測試環境進行緩慢的首次匯入
_HEAVY_MODULES = [
    "torch",
    "torchaudio",
    "torchaudio.transforms",
    "torchaudio.functional",
    "silero_vad",
    "soundfile",
]
for _mod in _HEAVY_MODULES:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()


# ─── 2. SQLite In-Memory 測試資料庫 ─────────────────────────────────────────
TEST_DB_URL = "sqlite:///:memory:"


@pytest.fixture(scope="session")
def test_engine():
    """建立 session 級別的 SQLite in-memory engine，整個測試 session 共用。"""
    from app.database.models import Base
    engine = create_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(test_engine):
    """
    每個測試函數獨立的 DB session。
    測試結束後自動 rollback，確保測試間資料隔離。
    """
    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=test_engine
    )
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# ─── 3. FastAPI TestClient ───────────────────────────────────────────────────

def _make_override_get_db(test_engine):
    """建立一個覆蓋 get_db 的 generator，綁定到測試 SQLite engine。"""
    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=test_engine
    )

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    return override_get_db


@pytest.fixture(scope="module")
def client(test_engine):
    """
    提供整合測試用的 FastAPI TestClient。
    - 替換 lifespan：略過 PostgreSQL init_db / Redis 監聽 / VAD 初始化
    - 使用 SQLite in-memory 取代 PostgreSQL
    """
    from app.database.session import get_db
    from main import app
    from fastapi.testclient import TestClient

    override_get_db = _make_override_get_db(test_engine)

    # 輕量 lifespan：不做任何外部連線，直接 yield
    @asynccontextmanager
    async def _test_lifespan(app_instance):
        yield

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = _test_lifespan
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c

    app.router.lifespan_context = original_lifespan
    app.dependency_overrides.clear()


