"""
整合測試：資料庫出錯時，SQL 參數與資料庫附上的資料列不進 log，也不傳回瀏覽器（#157、#168）
測試範圍：
  POST /api/v1/setting/models             存檔失敗：回固定的錯誤訊息，log 只記例外類型與原因
  GET  /api/v1/setting/models/{provider}  讀取失敗：同上
  單檔任務（run_transcription）            任務紀錄或片段寫不進去：log 只記例外類型與原因，
                                          畫面與任務紀錄給固定的訊息
  沒開始的任務（abandon_transcription）     任務紀錄寫不進去：log 只記例外類型與原因
  下載時回寫 lrc_content                    寫不進去：照樣下載得到，log 只記例外類型與原因
  啟動清掃（main.end_stale_processing）      寫不進去：log 只記例外類型與原因
  HTTP 端點                                 資料庫出錯：回固定的錯誤訊息，log 只記例外類型與原因，
                                          例外不離開應用程式（uvicorn 不記 traceback）
  WebSocket 端點                            派送前讀不到設定：log 只記例外類型與原因
  兩種執行模式的 engine                     例外文字都不附 SQL 參數，含 Celery 的結果後端

漏洞重現：SQLAlchemy 的例外文字預設附上 SQL 參數。設定存檔時資料庫出錯（例如 SQLite 的
database is locked），明文 API 金鑰跟著例外寫進 log，也放進 HTTP 500 的 detail、顯示在
畫面上；任務紀錄寫不進去時，轉錄結果與檔名一樣進了 log。任務失敗時 log 記下完整的
traceback：Postgres 在例外訊息第一行之後附上的 DETAIL 是寫不進去的整列，轉錄結果跟著
進了 log；畫面的狀態文字與任務紀錄的錯誤訊息則是使用者看不懂的 SQL 原文。排查只能靠
使用者附上的 log（ADR-0005），log 一附到 GitHub Issues 就公開了。

資料庫出錯用 SQLite 的 trigger 模擬：測試期間擋下某張表的 INSERT 或 UPDATE。
"""
import json
import traceback
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import main
from app.core.task_status import TaskStatus
from app.database import session
from app.database.models import BatchJob, ModelConfiguration, TranscriptionLog
from app.exceptions import TaskDatabaseError
from app.tasks.transcribe_core import abandon_transcription, run_transcription
from tests.support.db_faults import (
    DISK_FULL,
    NOT_NULL,
    assert_logged_without,
    rejected_row,
    writes_fail,
)
from tests.support.fake_provider import FAKE_MODEL, FakeProvider
from tests.support.task_api import upload

KEY = "AIzaSyLEAK-0123456789-abcdefghij-QRST"


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


# ─── 下載時回寫 lrc_content ──────────────────────────────────────────────────

class TestBackfillingTheStoredLrcFails:
    def test_download_still_works_and_the_log_keeps_the_reason_but_not_the_row(
            self, client: TestClient, db_session, test_engine, app_log):
        # #115 之前的批次：任務紀錄沒存 LRC，下載時從批次的結果讀出，順手回寫進任務紀錄。回寫的是
        # 整列 UPDATE，Postgres 附上的那一列有原始檔名與轉錄結果
        task_uuid = uuid.uuid4()
        batch_id = f"batch-{task_uuid.hex[:8]}"
        lrc = f"[00:00.20]{TRANSCRIPT}"
        db_session.add(BatchJob(
            batch_id=batch_id,
            results_json=json.dumps({"f1": {"transcripts": {"lrc": lrc}}}, ensure_ascii=False),
            file_log_uuids_json=json.dumps({"f1": str(task_uuid)})))
        db_session.commit()
        db_session.add(TranscriptionLog(task_uuid=task_uuid, status=TaskStatus.COMPLETED,
                                        original_filename=FILENAME, is_batch=True,
                                        batch_id=batch_id))
        db_session.commit()

        row = rejected_row("transcription_logs", f"{task_uuid}, COMPLETED, {FILENAME}, {lrc}")
        with writes_fail(test_engine, "transcription_logs", "UPDATE", row):
            response = client.get(f"/api/v1/history/{task_uuid}/download/lrc")

        assert response.status_code == 200
        assert response.text == lrc
        assert_logged_without(app_log, FILENAME, TRANSCRIPT)


# ─── 啟動清掃 ────────────────────────────────────────────────────────────────

@pytest.fixture
def stale_task(db_session):
    """一個一個月前開始、還停在處理中的單檔任務：應用程式啟動時清掃會把它記成失敗。

    原始檔名是 FILENAME；測試結束後刪掉，別的測試列出處理中的任務時才不會看到它。
    """
    task_uuid = uuid.uuid4()
    db_session.add(TranscriptionLog(
        task_uuid=task_uuid, status=TaskStatus.PROCESSING, original_filename=FILENAME,
        is_batch=False, request_timestamp=datetime.now() - timedelta(days=30)))
    db_session.commit()
    yield task_uuid
    db_session.query(TranscriptionLog).filter_by(task_uuid=task_uuid).delete()
    db_session.commit()


def test_startup_sweep_logs_the_reason_but_not_the_row(task_db, stale_task, test_engine, app_log):
    # 記成失敗的是整列 UPDATE，Postgres 附上的那一列有原始檔名與轉錄結果
    row = rejected_row("transcription_logs", f"{stale_task}, FAILED, {FILENAME}, null")
    with writes_fail(test_engine, "transcription_logs", "UPDATE", row):
        main.end_stale_processing()

    assert_logged_without(app_log, FILENAME)


# ─── HTTP 端點 ───────────────────────────────────────────────────────────────

@pytest.fixture
def finished_batch(db_session):
    """一個完成的批次：那一列有原始檔名（任務參數）與轉錄結果。回傳批次 id。"""
    batch_id = f"batch-{uuid.uuid4().hex[:8]}"
    db_session.add(BatchJob(
        batch_id=batch_id, status="COMPLETED",
        task_params_json=json.dumps({"files": [{"original_filename": FILENAME}]},
                                    ensure_ascii=False),
        results_json=json.dumps({"f1": {"transcripts": {"lrc": TRANSCRIPT}}}, ensure_ascii=False)))
    db_session.commit()
    return batch_id


class TestEndpointHitsADatabaseError:
    """沒有自己接住資料庫例外的端點（例如任務頁的「關閉」、刪除歷史紀錄）。

    例外離開應用程式時，uvicorn 把它連同 traceback 記進 log（免安裝版的主控台也印出來），畫面只收到
    Internal Server Error。TestClient 則把離開應用程式的例外拋回測試，所以這裡的請求沒有拋出例外，
    就表示 uvicorn 不會記下它。
    """

    def test_dismissing_a_batch_gives_a_fixed_message_and_logs_the_reason_but_not_the_row(
            self, client: TestClient, finished_batch, test_engine, app_log):
        row = rejected_row("batch_jobs", f"{finished_batch}, RETRIEVED, {FILENAME}, {TRANSCRIPT}")
        with writes_fail(test_engine, "batch_jobs", "UPDATE", row):
            response = client.post(f"/api/v1/batch/{finished_batch}/dismiss")

        assert response.status_code == 500
        for leaked in (FILENAME, TRANSCRIPT, NOT_NULL, "UPDATE", "batch_jobs"):
            assert leaked not in response.text
        assert_logged_without(app_log, FILENAME, TRANSCRIPT)

    def test_deleting_a_record_gives_a_fixed_message_and_logs_the_reason(
            self, client: TestClient, stale_task, test_engine, app_log):
        with writes_fail(test_engine, "transcription_logs", "DELETE",
                         rejected_row("transcription_logs", str(stale_task))):
            response = client.delete(f"/api/v1/history/{stale_task}")

        assert response.status_code == 500
        assert "DELETE" not in response.text
        assert NOT_NULL not in response.text
        assert_logged_without(app_log, FILENAME)


# ─── WebSocket 端點 ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", ["/api/v1/ws/uid-178", "/api/v1/batch/ws/batch-178"],
                         ids=["single-file", "batch"])
def test_websocket_logs_the_reason_but_not_the_sql(api, fake, test_engine, app_log, path):
    # 派送前從設定讀金鑰與提示詞範本：讀不到時（例如資料庫檔壞掉後重建，少了這張表）例外裡有 SQL 原文
    fake.model_capabilities = replace(fake.model_capabilities, supports_batch=True)
    filename = upload(api, "ws-178.wav")
    item = {"filename": filename, "original_filename": "ws-178.wav", "file_uid": "uid-178"}
    payload = ({"files": [item]} if "batch" in path else item) | {
        "provider": "fake", "model": FAKE_MODEL, "source_lang": "ja"}
    with table_missing(test_engine, "model_configurations"):
        with api.websocket_connect(path) as ws:
            ws.send_json(payload)
            # 端點記下錯誤之後關掉這條連線
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()

    log = "\n".join(app_log)
    assert "OperationalError" in log
    assert "no such table" in log
    assert "[SQL:" not in log
    assert "SELECT" not in log


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
