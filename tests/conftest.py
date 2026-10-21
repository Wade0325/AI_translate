"""
測試全域 Fixture 設定
- 在所有 app 模組匯入前，先 mock 重量級依賴（torch、torchaudio 等）
- SQLite 檔案資料庫（取代 PostgreSQL），引擎設定與免安裝模式相同
- 輕量 lifespan（略過 Redis / VAD 初始化）
- 收集 app 寫進 log 的內容
- 單檔任務的暫存資料夾、任務用的資料庫與假供應商
"""
import logging
import sys
import pytest
from contextlib import asynccontextmanager
from unittest.mock import MagicMock
from sqlalchemy.orm import sessionmaker

# ─── 1. 在所有 app 模組被匯入之前，先 mock 重量級依賴 ──────────────────────
# 避免 torch / torchaudio 在測試環境進行緩慢的首次匯入。
# soundfile 用真的：它在 base 依賴裡，測試要用它產生合成音檔（#103）
_HEAVY_MODULES = [
    "torch",
    "torchaudio",
    "torchaudio.transforms",
    "torchaudio.functional",
]
for _mod in _HEAVY_MODULES:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

# Silero 在測試環境明確視為無法使用：CI 不裝 ML 依賴，import 直接失敗，
# 切點只來自去靜音找出的靜音邊界；Silero 這條後備路徑由本機的 GPU 驗證涵蓋
sys.modules["silero_vad"] = None


# ─── 2. SQLite 測試資料庫 ───────────────────────────────────────────────────

@pytest.fixture(scope="session")
def test_engine(tmp_path_factory):
    """整個測試 session 共用的 SQLite 檔案資料庫，引擎與免安裝模式用同一個工廠建立。

    每個 session 各用自己的連線，和真的資料庫一樣：背景任務的執行緒與 API 請求不會
    共用交易，一邊收尾的 rollback 不會丟掉另一邊還沒 commit 的寫入。in-memory 資料庫
    得靠 StaticPool 讓所有執行緒共用一條連線，就會出這種事（見
    tests/integration/test_test_database.py）。
    """
    from app.database.models import Base
    from app.database.session import _create_engine

    path = tmp_path_factory.mktemp("db") / "test.db"
    engine = _create_engine(f"sqlite:///{path.as_posix()}")
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


# ─── 3. 執行模式 ─────────────────────────────────────────────────────────────

@pytest.fixture
def in_process_run_mode():
    """換上行程內轉接器（免安裝模式），測試結束後還原並關閉。"""
    from app.runtime import run_mode
    from app.runtime.in_process import InProcessRunMode

    # 測試不等暫時錯誤重試前的退避
    mode = InProcessRunMode(concurrency=1, retry_backoff_max=0)
    previous = run_mode.use(mode)
    yield mode
    run_mode.use(previous)
    mode.close()


# ─── 4. FastAPI TestClient ───────────────────────────────────────────────────

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
    - 使用 SQLite 測試資料庫（test_engine）取代 PostgreSQL
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


# ─── 5. app 的 log ───────────────────────────────────────────────────────────

class _Collector(logging.Handler):
    """每筆 log 收成寫出去的樣子：訊息，加上 exc_info 附的 traceback。"""

    def __init__(self):
        super().__init__()
        self.entries: list[str] = []

    def emit(self, record):
        self.entries.append(self.format(record))


@pytest.fixture
def app_log():
    """app 寫進 log 的內容，一筆一個字串。

    app 的 logger 不往上傳（app/utils/logger.py 設了 propagate=False），caplog 收不到，
    所以在每個 app 的 logger 上直接接一個收集的 handler。只接得到 fixture 啟動時已經
    建立的 logger：要看的模組在測試檔開頭 import。
    """
    handler = _Collector()
    loggers = [logger for name, logger in logging.Logger.manager.loggerDict.items()
               if name.startswith("app.") and isinstance(logger, logging.Logger)]
    for logger in loggers:
        logger.addHandler(handler)
    yield handler.entries
    for logger in loggers:
        logger.removeHandler(handler)


# ─── 6. 單檔任務 ─────────────────────────────────────────────────────────────

@pytest.fixture
def uploads(tmp_path, monkeypatch):
    """上傳檔、保留音檔、去靜音產物都寫進暫存資料夾；回傳上傳資料夾。"""
    from app.core.config import get_settings

    settings = get_settings()
    folder = tmp_path / "temp_uploads"
    folder.mkdir()
    monkeypatch.setattr(settings, "temp_uploads_dir", str(folder))
    monkeypatch.setattr(settings, "audio_store_dir", str(tmp_path / "audio_store"))
    monkeypatch.setattr(settings, "vad_artifacts_dir", str(tmp_path / "vad_artifacts"))
    return folder


@pytest.fixture
def data_dir(uploads, monkeypatch):
    """同 :func:`uploads`，上傳端點也收進同一個上傳資料夾；回傳放這些資料夾的暫存資料夾。"""
    from app.api import batch, transcription, upload

    for module in (transcription, upload, batch):
        monkeypatch.setattr(module, "TEMP_UPLOADS_DIR", uploads)
    return uploads.parent


@pytest.fixture
def task_db(test_engine):
    """任務（含在 worker 執行緒裡的）用 SessionLocal 寫紀錄；指到測試資料庫。"""
    from app.database.session import SessionLocal, engine

    SessionLocal.configure(bind=test_engine)
    yield
    SessionLocal.configure(bind=engine)


@pytest.fixture
def fake():
    """換上假供應商「fake」，測試結束後換回原本的。"""
    from app.provider import registry
    from tests.support.fake_provider import FakeProvider

    provider = FakeProvider()
    previous = registry.register("fake", provider)
    yield provider
    if provider.hold is not None:
        # 放行還停在 hold 的轉錄，worker 執行緒才結束得了
        provider.hold.set()
    registry.register("fake", previous)


