"""
整合測試：資料庫出錯時，SQL 參數與資料庫附上的資料列不進 log，也不傳回瀏覽器（#157、#168）
測試範圍：
  POST /api/v1/setting/models             存檔失敗：回固定的錯誤訊息，log 只記例外類型與原因
  GET  /api/v1/setting/models/{provider}  讀取失敗：同上
  單檔任務（run_transcription）            任務紀錄或片段寫不進去：log 只記例外類型與原因，
                                          畫面與任務紀錄給固定的訊息
  沒開始的任務（abandon_transcription）     任務紀錄寫不進去：log 只記例外類型與原因
  兩種執行模式的 engine                     例外文字都不附 SQL 參數，含 Celery 的結果後端

漏洞重現：SQLAlchemy 的例外文字預設附上 SQL 參數。設定存檔時資料庫出錯（例如 SQLite 的
database is locked），明文 API 金鑰跟著例外寫進 log，也放進 HTTP 500 的 detail、顯示在
畫面上；任務紀錄寫不進去時，轉錄結果與檔名一樣進了 log。任務失敗時 log 記下完整的
traceback：Postgres 在例外訊息第一行之後附上的 DETAIL 是寫不進去的整列，轉錄結果跟著
進了 log；畫面的狀態文字與任務紀錄的錯誤訊息則是使用者看不懂的 SQL 原文。排查只能靠
使用者附上的 log（ADR-0005），log 一附到 GitHub Issues 就公開了。

資料庫出錯用 SQLite 的 trigger 模擬：測試期間擋下某張表的 INSERT 或 UPDATE。
"""
import traceback
import uuid
from contextlib import contextmanager

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from app.core.task_status import TaskStatus
from app.database import session
from app.database.models import ModelConfiguration, TranscriptionLog
from app.exceptions import TaskDatabaseError
from app.tasks.transcribe_core import abandon_transcription, run_transcription
from tests.support.db_faults import DISK_FULL, writes_fail
from tests.support.fake_provider import FAKE_MODEL, FakeProvider

KEY = "AIzaSyLEAK-0123456789-abcdefghij-QRST"
NOT_NULL = "violates not-null constraint"


def rejected_row(table: str, row: str) -> str:
    """Postgres 回報違反約束的訊息：第一行是原因，之後的 DETAIL 是寫不進去的那一整列。

    SQLite 不會附上資料列，用 trigger 的錯誤訊息模擬。
    """
    return (f'null value in column "created_at" of relation "{table}" {NOT_NULL}\n'
            f'DETAIL:  Failing row contains ({row}).')


NOT_NULL_WITH_ROW = rejected_row(
    "model_configurations", f'Leak157Row, ["{KEY}"], null, null, 2026-10-20 12:00:00')


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
def broadcasts(in_process_run_mode, monkeypatch):
    """任務廣播給畫面的狀態訊息，依廣播的順序。"""
    messages: list[dict] = []
    monkeypatch.setattr(in_process_run_mode, "publish", messages.append)
    return messages


def task_params(uploads) -> dict:
    """一個單檔任務的參數：原始檔名是 FILENAME，輸入音檔是一秒的合成音。

    上傳檔另外命名，FILENAME 只出現在任務紀錄裡。
    """
    t = np.arange(SAMPLE_RATE) / SAMPLE_RATE
    audio = uploads / "upload-0001.wav"
    sf.write(audio, (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), SAMPLE_RATE)
    return {
        "file_path": str(audio),
        "provider": "fake",
        "model": FAKE_MODEL,
        "api_keys": "",
        "source_lang": "ja",
        "original_filename": FILENAME,
        "client_id": "uid-157",
        "file_uid": "uid-157",
    }


def run_task(uploads, fake: FakeProvider, task_uuid: str | None = None) -> None:
    """跑一個單檔任務（見 :func:`task_params`），假供應商把音檔轉錄成 TRANSCRIPT。"""
    fake.script = [[(0.2, 0.8, 0, TRANSCRIPT)]]
    run_transcription(task_params(uploads), task_uuid or str(uuid.uuid4()))


def failure_shown(broadcasts: list[dict]) -> str:
    """畫面上看到的失敗原因：宣告失敗時的狀態文字。"""
    [failed] = [m for m in broadcasts if m["status_code"] == TaskStatus.FAILED]
    return failed["status_text"]


def assert_fixed_message(shown: str) -> None:
    """給使用者看的是看得懂、告訴他怎麼做的固定訊息：不轉述例外，SQL 與原因只在 log。"""
    assert "INSERT" not in shown
    assert "UPDATE" not in shown
    assert NOT_NULL not in shown
    assert DISK_FULL not in shown
    assert "重新轉錄" in shown


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
            with pytest.raises(TaskDatabaseError):
                run_task(uploads, fake)

        log = "\n".join(app_log)
        assert DISK_FULL in log
        assert private not in log

    # Postgres 附上的那一列也一樣：開始時建立的有原始檔名，完成時寫入的有轉錄結果。完成時
    # 寫不進去，記成失敗與記下保留音檔也寫不進去
    @pytest.mark.parametrize("statement, private", [
        pytest.param("INSERT", FILENAME, id="start-filename"),
        pytest.param("UPDATE", TRANSCRIPT, id="complete-transcript"),
    ])
    def test_log_keeps_the_reason_but_not_the_row_the_database_attached(
            self, uploads, task_db, in_process_run_mode, fake, test_engine, app_log,
            statement, private):
        row = rejected_row("transcription_logs", f"0f5c, PROCESSING, {private}, null")
        with writes_fail(test_engine, "transcription_logs", statement, row):
            with pytest.raises(TaskDatabaseError):
                run_task(uploads, fake)

        log = "\n".join(app_log)
        assert private not in log
        assert "[SQL:" not in log
        # 排查只能靠 log（ADR-0005）：記下例外類型與資料庫回報的原因
        assert "IntegrityError" in log
        assert NOT_NULL in log

    @pytest.mark.parametrize("statement", ["INSERT", "UPDATE"])
    def test_user_sees_a_fixed_message(
            self, uploads, task_db, broadcasts, fake, test_engine, statement):
        with writes_fail(test_engine, "transcription_logs", statement):
            with pytest.raises(TaskDatabaseError):
                run_task(uploads, fake)

        assert_fixed_message(failure_shown(broadcasts))

    def test_task_that_never_started_logs_the_reason_but_not_the_row(
            self, uploads, task_db, in_process_run_mode, test_engine, app_log):
        # 在佇列中被撤銷的任務也留下任務紀錄；那一列有原始檔名
        row = rejected_row("transcription_logs", f"0f5c, CANCELLED, {FILENAME}, null")
        with writes_fail(test_engine, "transcription_logs", "INSERT", row):
            abandon_transcription(task_params(uploads), str(uuid.uuid4()), cancelled=True)

        log = "\n".join(app_log)
        assert FILENAME not in log
        assert "[SQL:" not in log
        assert NOT_NULL in log


# ─── 片段寫不進去 ────────────────────────────────────────────────────────────

# 片段和任務記成完成在同一個交易（#114）：片段寫不進去，任務照失敗處理。Postgres 附上的
# 那一列有轉錄結果
SEGMENT_ROW = rejected_row("transcript_segments", f"1, 0f5c, 0-0, 0, 0.2, 0.8, S0, {TRANSCRIPT}")


class TestSegmentsCannotBeWritten:
    def test_log_keeps_the_reason_but_not_the_row_or_the_sql(
            self, uploads, task_db, in_process_run_mode, fake, test_engine, app_log):
        with writes_fail(test_engine, "transcript_segments", "INSERT", SEGMENT_ROW):
            with pytest.raises(TaskDatabaseError):
                run_task(uploads, fake)

        log = "\n".join(app_log)
        assert TRANSCRIPT not in log
        assert "[SQL:" not in log
        assert "INSERT INTO" not in log
        assert "IntegrityError" in log
        assert NOT_NULL in log

    def test_user_sees_a_fixed_message_on_screen_and_in_the_task_record(
            self, uploads, task_db, broadcasts, fake, test_engine, db_session):
        task_uuid = str(uuid.uuid4())
        with writes_fail(test_engine, "transcript_segments", "INSERT", SEGMENT_ROW):
            with pytest.raises(TaskDatabaseError):
                run_task(uploads, fake, task_uuid)

        record = db_session.get(TranscriptionLog, uuid.UUID(task_uuid))
        assert record.status == TaskStatus.FAILED
        for shown in (failure_shown(broadcasts), record.error_message):
            assert TRANSCRIPT not in shown
            assert_fixed_message(shown)


# ─── 往上拋給執行模式的例外 ──────────────────────────────────────────────────

# 執行模式記下任務往上拋的例外：Docker 模式的 Celery worker 連同 traceback 寫進 log，
# 也存進結果後端
@pytest.mark.parametrize("table, statement, private", [
    pytest.param("transcription_logs", "INSERT", FILENAME, id="start-filename"),
    pytest.param("transcription_logs", "UPDATE", TRANSCRIPT, id="complete-transcript"),
    pytest.param("transcript_segments", "INSERT", TRANSCRIPT, id="segments-transcript"),
])
def test_run_mode_gets_the_reason_but_not_the_row_or_the_sql(
        uploads, task_db, in_process_run_mode, fake, test_engine, table, statement, private):
    with writes_fail(test_engine, table, statement, rejected_row(table, f"0f5c, {private}")):
        with pytest.raises(TaskDatabaseError) as raised:
            run_task(uploads, fake)

    reported = "".join(traceback.format_exception(raised.value))
    assert private not in reported
    assert "[SQL:" not in reported
    assert NOT_NULL in reported


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
