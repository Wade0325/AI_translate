"""Docker 模式的單檔任務與批次：Celery 任務包裝層接上 Celery＋Redis 執行模式（#113、#115）。

Celery 任務在測試行程裡以 eager 方式執行（``apply``），Redis 換成 fakeredis，供應商換成假供應商；任務生命週期、分段轉錄、ffmpeg 與 SQLite
測試資料庫都走真的。經 broker 的派送不在 CI 測。

測試只從外部觀察：Celery 回報的結果、執行模式廣播的狀態訊息、供應商被呼叫幾次，
以及 API 查到的任務紀錄。
"""
import json
import uuid
from dataclasses import replace

import fakeredis
import fakeredis.aioredis
import pytest

from app.core.task_status import TaskStatus
from app.exceptions import TransientError
from app.runtime import run_mode
from app.runtime.celery_redis import CHANNEL, CeleryRedisRunMode
from tests.support.fake_provider import FAKE_MODEL, Fail, Restart
from tests.support.older_batches import (
    SPANS,
    OlderFile,
    sent_by_previous_release,
    unreadable_older_batch,
)
from tests.support.synthetic_audio import synthetic_audio
from tests.support.task_api import file_results
from tests.support.waiting import cancel_when_dispatched

LINES = [(0.2, 1.5, 0, "おはよう。"), (2.3, 3.6, 1, "こんにちは。")]
TERMINAL = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}


# ─── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def redis_server():
    return fakeredis.FakeServer()


@pytest.fixture
def redis_run_mode(redis_server):
    """Docker 模式的執行模式：Celery＋Redis 轉接器，Redis 換成 fakeredis。"""
    mode = CeleryRedisRunMode(
        fakeredis.FakeRedis(server=redis_server),
        lambda: fakeredis.aioredis.FakeRedis(server=redis_server, decode_responses=True))
    previous = run_mode.use(mode)
    yield mode
    run_mode.use(previous)
    mode.close()


@pytest.fixture
def broadcasts(redis_server):
    """回傳一個函式：取出到目前為止廣播的狀態訊息（Redis 的狀態頻道）。"""
    pubsub = fakeredis.FakeRedis(server=redis_server).pubsub()
    pubsub.subscribe(CHANNEL)
    pubsub.get_message(timeout=1)  # 訂閱確認

    def drain() -> list[dict]:
        messages = []
        while (message := pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)):
            messages.append(json.loads(message["data"]))
        return messages

    yield drain
    pubsub.close()


@pytest.fixture
def celery_in_memory(monkeypatch, uploads, task_db, redis_run_mode, fake):
    """eager 執行 Celery 任務：broker 與結果後端都放記憶體。

    預設的結果後端是 Postgres：測試不能連它，也不能寫進開發者本機的資料庫。
    """
    from app.celery.celery import celery_app
    from app.core.config import get_settings

    assert not get_settings().is_standalone, "這裡測的是 Docker 模式"

    monkeypatch.setitem(celery_app.conf, "broker_url", "memory://")
    monkeypatch.setitem(celery_app.conf, "result_backend", "cache+memory://")
    # 這個執行緒之前建立過的結果後端用的是舊設定，換掉
    monkeypatch.delattr(celery_app._local, "backend", raising=False)


@pytest.fixture
def transcribe_media_task(celery_in_memory):
    """eager 執行的單檔 Celery 任務。"""
    from app.celery.task import transcribe_media_task as task

    return task


def task_params(uploads, file_uid: str) -> dict:
    """上傳一個合成音檔，回傳 API 派送給 Celery 任務的參數。"""
    path = uploads / f"{file_uid}.wav"
    path.write_bytes(synthetic_audio())
    return {
        "file_path": str(path),
        "provider": "fake",
        "model": FAKE_MODEL,
        "api_keys": "",
        "source_lang": "ja",
        "original_filename": path.name,
        "client_id": file_uid,
        "file_uid": file_uid,
    }


def retry_notices(messages: list[dict]) -> int:
    """分段轉錄等待重試前的廣播有幾則。"""
    return sum(m["status_code"] == TaskStatus.PROCESSING and "遇到暫時錯誤" in m["status_text"]
               for m in messages)



def worker_discards_revoked(task, params: dict, task_id: str, *, terminated: bool = False) -> None:
    """worker 丟掉被撤銷的任務時送出的訊號：還沒執行的（在佇列中）照樣送，執行中被強制終止的帶
    ``terminated``。訊號帶的 request 和 worker 的一樣，有任務參數。"""
    from celery.app.task import Context
    from celery.signals import task_revoked

    task_revoked.send(sender=task, request=Context(id=task_id, args=[params], kwargs={}),
                      terminated=terminated, signum=None, expired=False)


def results(messages: list[dict]) -> list[str]:
    return [m["status_code"] for m in messages if m["status_code"] in TERMINAL]


# ─── 暫時錯誤在分段轉錄裡重試那一段，Celery 不重試整個任務 ──────────────────

@pytest.mark.parametrize("transient_errors", [1, 2, 3])
def test_transient_errors_retry_only_that_chunk_and_the_task_completes(
        transcribe_media_task, uploads, fake, broadcasts, client, quick_transient_retries,
        transient_errors):
    # 單次只能處理 5 秒：去靜音之後 7.2 秒的語音視圖切成 4.9 秒與 2.3 秒兩段。第二段遇到暫時錯誤時，
    # 在任務裡等一段時間再轉那一段：第一段不重送，和免安裝模式一樣
    fake.model_capabilities = replace(fake.model_capabilities, single_pass_seconds=5.0)
    fake.script = ([[(0.2, 0.8, 0, "おはよう。")]]
                   + [TransientError("503 服務暫時無法使用")] * transient_errors
                   + [[(0.2, 0.8, 1, "こんにちは。")]])
    task_id = str(uuid.uuid4())

    result = transcribe_media_task.apply(args=[task_params(uploads, "uid-recovers")],
                                         task_id=task_id)

    messages = broadcasts()
    assert result.state == "SUCCESS"
    assert fake.durations == pytest.approx([4.9] + [2.3] * (transient_errors + 1), abs=0.01)
    assert retry_notices(messages) == transient_errors
    assert results(messages) == [TaskStatus.COMPLETED]
    assert client.get(f"/api/v1/history/{task_id}").json()["status"] == TaskStatus.COMPLETED


def test_task_fails_when_the_retries_run_out_and_celery_does_not_rerun_it(
        transcribe_media_task, uploads, fake, broadcasts, client, quick_transient_retries):
    fake.script = [TransientError("503 服務暫時無法使用")] * 4
    task_id = str(uuid.uuid4())

    result = transcribe_media_task.apply(args=[task_params(uploads, "uid-gives-up")],
                                         task_id=task_id)

    # 重試 3 次都失敗：照失敗處理，任務不會一直停在處理中；Celery 也不再重試整個任務
    messages = broadcasts()
    assert result.state == "FAILURE"
    assert len(fake.calls) == 4
    assert retry_notices(messages) == 3
    assert results(messages) == [TaskStatus.FAILED]
    record = client.get(f"/api/v1/history/{task_id}").json()
    assert record["status"] == TaskStatus.FAILED
    assert "暫時錯誤重試 3 次仍失敗（503 服務暫時無法使用）" in record["error_message"]


def test_transient_error_reaching_the_task_is_a_failure_and_celery_does_not_rerun_it(
        transcribe_media_task, uploads, fake, broadcasts, client):
    # 萬一有暫時錯誤沒經過分段轉錄就漏到任務（這裡是建立轉接器時）：照失敗處理，Celery 不重試
    fake.open_error = TransientError("503 服務暫時無法使用")
    task_id = str(uuid.uuid4())

    result = transcribe_media_task.apply(args=[task_params(uploads, "uid-escaped")],
                                         task_id=task_id)

    assert result.state == "FAILURE"
    assert fake.opened == 1
    assert results(broadcasts()) == [TaskStatus.FAILED]
    assert client.get(f"/api/v1/history/{task_id}").json()["status"] == TaskStatus.FAILED


def test_cancel_after_the_task_completed_finds_nothing_to_cancel(
        transcribe_media_task, uploads, fake, redis_run_mode, client):
    fake.script = [list(LINES)]
    task_id = str(uuid.uuid4())
    redis_run_mode.register_task("uid-done", task_id, can_terminate=False)  # 派送時登記

    transcribe_media_task.apply(args=[task_params(uploads, "uid-done")], task_id=task_id)

    # 任務結束時清掉登記：之後按取消，不會找到這個早已結束的任務，紀錄維持完成
    response = client.post("/api/v1/transcription/uid-done/cancel").json()
    assert response == {"file_uid": "uid-done", "cancelled": False, "reason": "not-started"}
    assert client.get(f"/api/v1/history/{task_id}").json()["status"] == TaskStatus.COMPLETED


# ─── 撤銷之後不會再執行的任務 ────────────────────────────────────────────────

@pytest.mark.parametrize("retain_audio", [True, False], ids=["retain", "no-retain"])
def test_task_revoked_before_it_runs_is_recorded_and_its_upload_handled(
        transcribe_media_task, uploads, fake, redis_run_mode, client, monkeypatch, retain_audio):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "retain_audio", retain_audio)
    task_id = str(uuid.uuid4())
    params = task_params(uploads, "uid-revoked")
    # 取消端點設好旗標、送出撤銷；worker 收到這個還在佇列裡的任務時直接丟掉
    redis_run_mode.register_task("uid-revoked", task_id, can_terminate=True)
    redis_run_mode.request_cancel("uid-revoked")

    worker_discards_revoked(transcribe_media_task, params, task_id)

    # 和免安裝模式一樣照樣收尾：記成已取消，上傳檔照保留設定處理，登記與旗標清掉
    assert fake.calls == []
    assert client.get(f"/api/v1/history/{task_id}").json()["status"] == TaskStatus.CANCELLED
    audio = client.get(f"/api/v1/transcripts/{task_id}/audio")
    if retain_audio:
        assert audio.content == synthetic_audio()
    else:
        assert audio.status_code == 404
    assert list(uploads.iterdir()) == []
    again = client.post("/api/v1/transcription/uid-revoked/cancel").json()
    assert again["reason"] == "not-started"
    assert redis_run_mode.is_cancel_requested("uid-revoked") is False


class QueuedInBroker:
    """派送的任務都還排在 broker 裡、沒有 worker 拿走；撤銷只記下參數，其餘照轉。

    Celery 本身的派送與撤銷不在 CI 測：取消端點依登記決定要不要強制終止，在這個接縫上看。
    """

    def __init__(self, inner):
        self._inner = inner
        self.revoked = []

    def submit_transcription(self, task_id, task_params_dict, queue):
        pass

    def revoke(self, task_id, terminate=False):
        self.revoked.append((task_id, terminate))

    def __getattr__(self, name):
        return getattr(self._inner, name)


def test_cancelling_a_queued_gemini_task_still_terminates_it(
        transcribe_media_task, uploads, redis_run_mode, client, monkeypatch):
    from app.api import transcription, upload

    monkeypatch.setattr(transcription, "TEMP_UPLOADS_DIR", uploads)
    monkeypatch.setattr(upload, "TEMP_UPLOADS_DIR", uploads)
    queued = QueuedInBroker(redis_run_mode)
    run_mode.use(queued)  # redis_run_mode 收尾時換回原本的
    name = "gemini-queued.wav"
    uploaded = client.post("/api/v1/upload", files={"file": (name, synthetic_audio(), "audio/wav")})

    with client.websocket_connect("/api/v1/ws/uid-gemini-queued") as ws:
        ws.send_json({"filename": uploaded.json()["filename"], "original_filename": name,
                      "provider": "Google", "model": "gemini-2.5-flash", "source_lang": "ja"})
        cancel_when_dispatched(client, "uid-gemini-queued")

    # 任務紀錄還沒建立（任務可能下一刻就開始）：照派送時登記的模型能力送出強制終止
    assert [terminate for _, terminate in queued.revoked] == [True]


def test_revoked_signal_leaves_a_terminated_task_to_its_own_finishing(
        transcribe_media_task, uploads, fake, redis_run_mode, client):
    task_id = str(uuid.uuid4())
    params = task_params(uploads, "uid-terminated")

    worker_discards_revoked(transcribe_media_task, params, task_id, terminated=True)

    # 執行中被強制終止的任務，由它自己的生命週期在 finally 收尾：訊號這邊不重複收尾
    assert client.get(f"/api/v1/history/{task_id}").status_code == 404
    assert [p.name for p in uploads.iterdir()] == ["uid-terminated.wav"]


# ─── 批次 ────────────────────────────────────────────────────────────────────

@pytest.fixture
def batch_tasks(celery_in_memory, fake):
    """eager 執行的批次 Celery 任務（執行與復原）；假供應商支援批次。"""
    from app.celery.batch_task import batch_recover_task, batch_transcribe_task

    fake.model_capabilities = replace(fake.model_capabilities, supports_batch=True)
    return batch_transcribe_task, batch_recover_task


def batch_params(uploads, batch_id: str, file_uids: list[str]) -> dict:
    """上傳合成音檔，回傳 API 派送給批次 Celery 任務的參數。"""
    files = []
    for file_uid in file_uids:
        path = uploads / f"{file_uid}.wav"
        path.write_bytes(synthetic_audio())
        files.append({"file_path": str(path), "original_filename": path.name, "file_uid": file_uid})
    return {"files": files, "provider": "fake", "model": FAKE_MODEL, "api_keys": "",
            "source_lang": "ja", "client_id": batch_id, "batch_id": batch_id}


def test_batch_files_end_like_tasks_in_docker_mode(batch_tasks, uploads, fake, broadcasts, client):
    # 和免安裝模式一樣：每個檔案的結果廣播到 Redis 的狀態頻道，存下任務紀錄與片段；一個檔案失敗
    # 不影響另一個，Celery 照樣回報批次跑完
    run, _ = batch_tasks
    fake.script = [list(LINES), Fail("音檔無法解碼")]

    result = run.apply(args=[batch_params(uploads, "batch-docker", ["docker-a", "docker-b"])],
                       task_id=str(uuid.uuid4()))

    messages = broadcasts()
    assert result.state == "SUCCESS"
    ends = file_results(messages)
    assert {uid: m["status_code"] for uid, m in ends.items()} == {
        "docker-a": TaskStatus.COMPLETED, "docker-b": TaskStatus.FAILED}
    segments = client.get(f"/api/v1/transcripts/{ends['docker-a']['task_uuid']}").json()["segments"]
    assert [s["text"] for s in segments] == ["おはよう。", "こんにちは。"]
    failed = client.get(f"/api/v1/history/{ends['docker-b']['task_uuid']}").json()
    assert (failed["status"], failed["is_batch"]) == (TaskStatus.FAILED, True)
    assert messages[-1]["status_code"] == TaskStatus.BATCH_COMPLETED
    assert list(uploads.iterdir()) == []


def test_batch_restarted_while_polling_recovers_in_docker_mode(
        batch_tasks, uploads, fake, broadcasts, client, monkeypatch):
    # worker 在查詢批次時重啟：檔案停在處理中，Celery 還把那次執行當成在跑。復原端點照樣接手，派送的
    # Celery 任務（這裡 eager 執行）把同一個任務結束成完成
    from app.celery.celery import celery_app

    run, _ = batch_tasks
    fake.script = [list(LINES)]
    fake.batch_polls = [Restart()]
    run_id = str(uuid.uuid4())
    with pytest.raises(Restart):
        run.apply(args=[batch_params(uploads, "batch-docker-restart", ["docker-restart"])],
                  task_id=run_id)
    started = [m for m in broadcasts() if m.get("file_uid") == "docker-restart"]
    assert {m["status_code"] for m in started} == {TaskStatus.PROCESSING}
    # 被砍掉的 worker 來不及回報：結果後端還記著那次執行在跑（task_track_started）
    celery_app.backend.store_result(run_id, None, "STARTED")
    monkeypatch.setitem(celery_app.conf, "task_always_eager", True)

    response = client.post("/api/v1/batch/batch-docker-restart/recover",
                           json={"api_keys": "test-key"})

    assert response.status_code == 200, response.text
    recovered = file_results(broadcasts())["docker-restart"]
    assert (recovered["status_code"], recovered["task_uuid"]) == (
        TaskStatus.COMPLETED, started[-1]["task_uuid"])
    segments = client.get(f"/api/v1/transcripts/{recovered['task_uuid']}").json()["segments"]
    assert [(s["start"], s["text"]) for s in segments] == [
        (pytest.approx(0.2), "おはよう。"), (pytest.approx(4.7), "こんにちは。")]
    assert list(uploads.iterdir()) == []


def test_a_batch_sent_by_the_previous_release_recovers_in_docker_mode(
        batch_tasks, fake, broadcasts, client, db_session):
    # 上一個發布版本送出的批次只有舊的 JSON 欄位。升級時舊版的 worker 在 API 啟動之後才送出，啟動時沒
    # 補到列：復原的 Celery 任務當場補上，把舊版開始的任務結束成完成，片段落在原音檔的時間軸上
    _, recover = batch_tasks
    fake.script = [list(LINES)]
    name = fake.submit_batch([(None, "")], "older")  # 舊版送出的請求
    task_uuids = sent_by_previous_release(db_session, "batch-docker-older", name,
                                          [OlderFile("docker-older", SPANS)])

    result = recover.apply(args=["batch-docker-older", "test-key"])

    recovered = file_results(broadcasts())["docker-older"]
    assert result.state == "SUCCESS"
    assert (recovered["status_code"], recovered["task_uuid"]) == (
        TaskStatus.COMPLETED, task_uuids["docker-older"])
    segments = client.get(f"/api/v1/transcripts/{task_uuids['docker-older']}").json()["segments"]
    # 去靜音之後 2.3 秒是第二個有聲段的開頭
    assert [(s["start"], s["text"]) for s in segments] == [
        (pytest.approx(0.2), "おはよう。"), (pytest.approx(4.7), "こんにちは。")]


def test_an_older_batch_whose_file_list_cannot_be_read_is_left_alone_in_docker_mode(
        batch_tasks, fake, broadcasts, db_session):
    # 舊版的檔案清單讀不懂（這裡沒有記下任務紀錄 id），補不了列：復原的 Celery 任務不接手、不開
    # 供應商，批次的狀態不動
    from app.database.models import BatchJob

    _, recover = batch_tasks
    unreadable_older_batch(db_session, "batch-docker-unreadable", "FAILED")

    result = recover.apply(args=["batch-docker-unreadable", "test-key"])

    assert result.state == "SUCCESS"
    assert "讀不出它的檔案清單" in broadcasts()[-1]["status_text"]
    assert fake.opened == 0
    db_session.expire_all()
    assert db_session.get(BatchJob, "batch-docker-unreadable").status == "FAILED"


def test_batch_recovers_in_docker_mode(batch_tasks, uploads, fake, broadcasts, client):
    # 輪詢中斷，檔案先記成失敗；復原的 Celery 任務接著把它結束成完成，片段落在原音檔的時間軸上
    run, recover = batch_tasks
    fake.script = [list(LINES)]
    fake.batch_polls = [RuntimeError("連線中斷")]
    run.apply(args=[batch_params(uploads, "batch-docker-recover", ["docker-recover"])],
              task_id=str(uuid.uuid4()))
    first = file_results(broadcasts())["docker-recover"]
    assert first["status_code"] == TaskStatus.FAILED

    result = recover.apply(args=["batch-docker-recover", "test-key"])

    recovered = file_results(broadcasts())["docker-recover"]
    assert result.state == "SUCCESS"
    assert (recovered["status_code"], recovered["task_uuid"]) == (
        TaskStatus.COMPLETED, first["task_uuid"])
    segments = client.get(f"/api/v1/transcripts/{first['task_uuid']}").json()["segments"]
    # 去靜音之後 2.3 秒是第二個有聲段的開頭（有聲段前後各留 0.3 秒）
    assert [(s["start"], s["text"]) for s in segments] == [
        (pytest.approx(0.2), "おはよう。"), (pytest.approx(4.7), "こんにちは。")]
