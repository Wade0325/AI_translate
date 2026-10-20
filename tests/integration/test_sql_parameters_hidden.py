"""
整合測試：資料庫出錯時，SQL 參數不進 log，也不傳回瀏覽器（#157）
測試範圍：
  POST /api/v1/setting/models             存檔失敗：回固定的錯誤訊息，log 只記例外類型與原因
  GET  /api/v1/setting/models/{provider}  讀取失敗：同上
  單檔任務（run_transcription）            任務紀錄寫不進去
  兩種執行模式的 engine                     例外文字都不附 SQL 參數，含 Celery 的結果後端

漏洞重現：SQLAlchemy 的例外文字預設附上 SQL 參數。設定存檔時資料庫出錯（例如 SQLite 的
database is locked），明文 API 金鑰跟著例外寫進 log，也放進 HTTP 500 的 detail、顯示在
畫面上；任務紀錄寫不進去時，轉錄結果與檔名一樣進了 log。排查只能靠使用者附上的 log
（ADR-0005），log 一附到 GitHub Issues 就公開了。

資料庫出錯用 SQLite 的 trigger 模擬：測試期間擋下某張表的 INSERT 或 UPDATE。
"""
import uuid
from contextlib import contextmanager

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from app.core.config import get_settings
from app.database import session
from app.database.models import ModelConfiguration
from app.provider import registry
from app.tasks.transcribe_core import run_transcription
from tests.support.fake_provider import FAKE_MODEL, FakeProvider

KEY = "AIzaSyLEAK-0123456789-abcdefghij-QRST"
DISK_FULL = "database or disk is full"
# Postgres 回報違反約束時，在第一行之後附上 DETAIL：寫不進去的那一整列，含明文金鑰。
# SQLite 不會這樣做，用 trigger 的錯誤訊息模擬
NOT_NULL_WITH_ROW = (
    'null value in column "model" of relation "model_configurations" '
    'violates not-null constraint\n'
    f'DETAIL:  Failing row contains (Leak157Row, ["{KEY}"], null, null, 2026-10-20 12:00:00).'
)


@contextmanager
def writes_fail(engine, table: str, statement: str, message: str = DISK_FULL):
    """這段期間資料庫擋下 table 的 INSERT 或 UPDATE（statement），回報 message。"""
    trigger = f"{table}_{statement.lower()}_fails"
    literal = message.replace("'", "''")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            f"CREATE TRIGGER {trigger} BEFORE {statement} ON {table} "
            f"BEGIN SELECT RAISE(ABORT, '{literal}'); END")
    try:
        yield
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f"DROP TRIGGER {trigger}")


def _save(client: TestClient, provider: str, key: str):
    return client.post("/api/v1/setting/models", json={
        "provider": provider,
        "apiKeys": [key],
        "model": "gemini-2.5-flash",
    })


# ─── 存檔失敗 ────────────────────────────────────────────────────────────────

@pytest.fixture(params=["INSERT", "UPDATE"])
def blocked_save(request, client: TestClient, db_session):
    """要存檔的供應商與存檔時會用到的寫入：沒存過的供應商是 INSERT，存過的是 UPDATE。

    測試結束後刪掉這筆設定。
    """
    statement = request.param
    provider = f"Leak157{statement.title()}"
    if statement == "UPDATE":
        assert _save(client, provider, "old-key-for-test-0000").status_code == 200
    yield provider, statement
    db_session.query(ModelConfiguration).filter_by(provider=provider).delete()
    db_session.commit()


class TestSavingSettingsFails:
    def test_response_is_a_fixed_message_without_the_key(
            self, client: TestClient, test_engine, blocked_save):
        provider, statement = blocked_save
        with writes_fail(test_engine, "model_configurations", statement):
            response = _save(client, provider, KEY)

        assert response.status_code == 500
        assert KEY not in response.text
        # 固定訊息：不轉述例外，資料庫回報的原因只記在 log
        assert DISK_FULL not in response.text

    def test_log_names_the_error_without_the_key(
            self, client: TestClient, test_engine, blocked_save, app_log):
        provider, statement = blocked_save
        with writes_fail(test_engine, "model_configurations", statement):
            _save(client, provider, KEY)

        log = "\n".join(app_log)
        assert KEY not in log
        # 排查只能靠 log（ADR-0005）：記下例外類型與資料庫回報的原因
        assert "IntegrityError" in log
        assert DISK_FULL in log

    def test_log_keeps_the_reason_but_not_the_row_the_database_attached(
            self, client: TestClient, test_engine, app_log):
        with writes_fail(test_engine, "model_configurations", "INSERT", NOT_NULL_WITH_ROW):
            response = _save(client, "Leak157Row", KEY)

        log = "\n".join(app_log)
        assert KEY not in response.text
        assert KEY not in log
        assert "violates not-null constraint" in log


# ─── 讀取失敗 ────────────────────────────────────────────────────────────────

@contextmanager
def table_missing(engine, table: str):
    """這段期間資料庫裡沒有這張表（例如資料庫檔壞掉後重建），讀它就失敗。"""
    with engine.begin() as conn:
        conn.exec_driver_sql(f"ALTER TABLE {table} RENAME TO {table}_away")
    try:
        yield
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f"ALTER TABLE {table}_away RENAME TO {table}")


class TestReadingSettingsFails:
    def test_response_is_a_fixed_message_and_the_reason_goes_to_the_log(
            self, client: TestClient, test_engine, app_log):
        with table_missing(test_engine, "model_configurations"):
            response = client.get("/api/v1/setting/models/Google")

        assert response.status_code == 500
        # 不轉述例外：畫面上不出現 SQL 與資料表
        assert "model_configurations" not in response.text
        log = "\n".join(app_log)
        assert "OperationalError" in log
        assert "no such table" in log


# ─── 任務紀錄寫不進去 ────────────────────────────────────────────────────────

FILENAME = "社長との面談_極秘.wav"
TRANSCRIPT = "来期の人事はまだ内密に。"
SAMPLE_RATE = 16000


@pytest.fixture
def uploads(tmp_path, monkeypatch):
    """上傳檔、保留音檔、去靜音產物都寫進暫存資料夾；回傳上傳資料夾。"""
    settings = get_settings()
    folder = tmp_path / "temp_uploads"
    folder.mkdir()
    monkeypatch.setattr(settings, "temp_uploads_dir", str(folder))
    monkeypatch.setattr(settings, "audio_store_dir", str(tmp_path / "audio_store"))
    monkeypatch.setattr(settings, "vad_artifacts_dir", str(tmp_path / "vad_artifacts"))
    return folder


@pytest.fixture
def task_db(test_engine):
    """任務用 SessionLocal 寫紀錄；指到測試資料庫。"""
    session.SessionLocal.configure(bind=test_engine)
    yield
    session.SessionLocal.configure(bind=session.engine)


@pytest.fixture
def fake():
    provider = FakeProvider()
    previous = registry.register("fake", provider)
    yield provider
    registry.register("fake", previous)


def run_task(uploads, fake: FakeProvider) -> None:
    """跑一個單檔任務：原始檔名是 FILENAME，假供應商把一秒的音檔轉錄成 TRANSCRIPT。

    上傳檔另外命名，FILENAME 只出現在任務紀錄的 SQL 參數裡。
    """
    t = np.arange(SAMPLE_RATE) / SAMPLE_RATE
    audio = uploads / "upload-0001.wav"
    sf.write(audio, (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), SAMPLE_RATE)
    fake.script = [[(0.2, 0.8, 0, TRANSCRIPT)]]
    run_transcription({
        "file_path": str(audio),
        "provider": "fake",
        "model": FAKE_MODEL,
        "api_keys": "",
        "source_lang": "ja",
        "original_filename": FILENAME,
        "client_id": "uid-157",
        "file_uid": "uid-157",
    }, str(uuid.uuid4()))


class TestTaskRecordCannotBeWritten:
    # 開始時建立任務紀錄（INSERT）的參數有原始檔名，完成時寫入任務紀錄（UPDATE）的參數有轉錄結果
    @pytest.mark.parametrize("statement, private", [
        pytest.param("INSERT", FILENAME, id="start-filename"),
        pytest.param("UPDATE", TRANSCRIPT, id="complete-transcript"),
    ])
    def test_log_has_the_failure_but_not_the_sql_parameters(
            self, uploads, task_db, in_process_run_mode, fake, test_engine, app_log,
            statement, private):
        with writes_fail(test_engine, "transcription_logs", statement):
            with pytest.raises(DBAPIError):
                run_task(uploads, fake)

        log = "\n".join(app_log)
        assert DISK_FULL in log
        assert private not in log


# ─── 兩種執行模式 ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    pytest.param("sqlite://", id="standalone-sqlite"),
    # 只建立 engine、不連線：CI 沒有 Postgres，上面經過資料庫的測試都跑在 SQLite 上
    pytest.param("postgresql://user:password@localhost:5432/db", id="docker-postgres"),
])
def test_engine_of_each_run_mode_hides_sql_parameters(url):
    engine = session._create_engine(url)
    try:
        assert engine.hide_parameters
    finally:
        engine.dispose()


def test_celery_result_backend_hides_sql_parameters(tmp_path):
    """Docker 模式的 Celery 用自己建的 engine 存任務的回傳值（含轉錄結果）。

    寫入失敗時 Celery 會把例外連同 traceback 記進 worker 的 log。
    """
    from celery.backends.database import DatabaseBackend

    from app.celery.celery import celery_app

    # 不連 Postgres：網址換成暫存資料夾裡的 SQLite，engine 的其他設定照 celery_app 的
    backend = DatabaseBackend(
        app=celery_app, url=f"sqlite:///{(tmp_path / 'results.db').as_posix()}")
    results = backend.ResultSession()
    try:
        assert results.get_bind().hide_parameters
    finally:
        results.close()
