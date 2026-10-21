"""Docker 模式的單檔任務：Celery 任務包裝層接上 Celery＋Redis 執行模式（#113）。

Celery 任務在測試行程裡以 eager 方式執行（``apply``：autoretry 照樣重試，不等退避），
Redis 換成 fakeredis，供應商換成假供應商；任務生命週期、分段轉錄、ffmpeg 與 SQLite
測試資料庫都走真的。經 broker 的派送不在 CI 測。

測試只從外部觀察：Celery 回報的結果、執行模式廣播的狀態訊息、供應商被呼叫幾次，
以及 API 查到的任務紀錄。
"""
import io
import json
import uuid

import fakeredis
import fakeredis.aioredis
import numpy as np
import pytest
import soundfile as sf

from app.core.task_status import TaskStatus
from app.exceptions import TransientError
from app.provider import registry
from app.runtime import run_mode
from app.runtime.celery_redis import CHANNEL, CeleryRedisRunMode
from app.runtime.run_mode import TRANSIENT_RETRIES
from tests.support.fake_provider import FAKE_MODEL, FakeProvider
from tests.support.waiting import cancel_when_dispatched

LINES = [(0.2, 1.5, 0, "おはよう。"), (2.3, 3.6, 1, "こんにちは。")]
WILL_RETRY = "暫時性錯誤，將重試"
TERMINAL = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}


def synthetic_audio() -> bytes:
    """有聲 2 秒、靜音 3 秒交錯的合成 wav，共 12 秒。"""
    rate = 16000
    samples = np.zeros(12 * rate, dtype=np.float32)
    for start in (0, 5, 10):
        t = np.arange(2 * rate) / rate
        samples[start * rate:(start + 2) * rate] = 0.3 * np.sin(2 * np.pi * 440 * t)
    buffer = io.BytesIO()
    sf.write(buffer, samples, rate, format="WAV")
    return buffer.getvalue()


# ─── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def uploads(tmp_path, monkeypatch):
    """上傳檔、保留音檔、去靜音產物都寫進暫存資料夾。"""
    from app.core.config import get_settings

    settings = get_settings()
    assert not settings.is_standalone, "這裡測的是 Docker 模式"
    folder = tmp_path / "temp_uploads"
    folder.mkdir()
    monkeypatch.setattr(settings, "temp_uploads_dir", str(folder))
    monkeypatch.setattr(settings, "audio_store_dir", str(tmp_path / "audio_store"))
    monkeypatch.setattr(settings, "vad_artifacts_dir", str(tmp_path / "vad_artifacts"))
    return folder


@pytest.fixture
def task_db(test_engine):
    """任務用 SessionLocal 寫紀錄；指到測試資料庫。"""
    from app.database.session import SessionLocal, engine

    SessionLocal.configure(bind=test_engine)
    yield
    SessionLocal.configure(bind=engine)


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
def fake():
    provider = FakeProvider()
    previous = registry.register("fake", provider)
    yield provider
    registry.register("fake", previous)


@pytest.fixture
def transcribe_media_task(monkeypatch, uploads, task_db, redis_run_mode, fake):
    """eager 執行的單檔 Celery 任務；broker 與結果後端都放記憶體。

    預設的結果後端是 Postgres：測試不能連它，也不能寫進開發者本機的資料庫。
    """
    from app.celery.celery import celery_app
    from app.celery.task import transcribe_media_task as task

    monkeypatch.setitem(celery_app.conf, "broker_url", "memory://")
    monkeypatch.setitem(celery_app.conf, "result_backend", "cache+memory://")
    # 這個執行緒之前建立過的結果後端用的是舊設定，換掉
    monkeypatch.delattr(celery_app._local, "backend", raising=False)
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
    return sum(WILL_RETRY in m["status_text"] for m in messages)


def worker_discards_revoked(task, params: dict, task_id: str, *, terminated: bool = False) -> None:
    """worker 丟掉被撤銷的任務時送出的訊號：還沒執行的（在佇列中、或等著重試）照樣送，
    執行中被強制終止的帶 ``terminated``。訊號帶的 request 和 worker 的一樣，有任務參數。"""
    from celery.app.task import Context
    from celery.signals import task_revoked

    task_revoked.send(sender=task, request=Context(id=task_id, args=[params], kwargs={}),
                      terminated=terminated, signum=None, expired=False)


def results(messages: list[dict]) -> list[str]:
    return [m["status_code"] for m in messages if m["status_code"] in TERMINAL]


# ─── 暫時錯誤交給 Celery 重試 ────────────────────────────────────────────────

# 每一次執行都要知道之後還剩幾次重試（3、2、1、0）：還有重試就宣告「將重試」、交給
# Celery；剩 0 次時照失敗處理。連續幾次暫時錯誤之後成功，就能看出每一次剩下的次數
@pytest.mark.parametrize("transient_errors", [1, 2, 3])
def test_retries_until_the_provider_recovers(
        transcribe_media_task, uploads, fake, broadcasts, client, transient_errors):
    fake.script = [TransientError("503 服務暫時無法使用")] * transient_errors + [list(LINES)]
    task_id = str(uuid.uuid4())

    result = transcribe_media_task.apply(args=[task_params(uploads, "uid-recovers")],
                                         task_id=task_id)

    messages = broadcasts()
    assert result.state == "SUCCESS"
    assert len(fake.calls) == transient_errors + 1
    assert retry_notices(messages) == transient_errors
    assert results(messages) == [TaskStatus.COMPLETED]
    assert client.get(f"/api/v1/history/{task_id}").json()["status"] == TaskStatus.COMPLETED


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


@pytest.mark.parametrize("retain_audio", [True, False], ids=["retain", "no-retain"])
def test_task_revoked_while_waiting_to_retry_is_recorded_and_its_upload_handled(
        transcribe_media_task, uploads, fake, redis_run_mode, client, monkeypatch, retain_audio):
    from app.core.config import get_settings
    from app.tasks.transcribe_core import run_transcription

    monkeypatch.setattr(get_settings(), "retain_audio", retain_audio)
    task_id = str(uuid.uuid4())
    params = task_params(uploads, "uid-retry-revoked")
    redis_run_mode.register_task("uid-retry-revoked", task_id, can_terminate=True)
    fake.script = [TransientError("503 服務暫時無法使用")]
    # 第一次執行遇到暫時錯誤：輸入音檔與旗標留給重試，Celery 排好重試
    with pytest.raises(TransientError):
        run_transcription(params, task_id, retries_left=1)

    # 等重試的期間使用者按下取消：worker 丟掉被撤銷的重試，任務不會再執行
    redis_run_mode.request_cancel("uid-retry-revoked")
    worker_discards_revoked(transcribe_media_task, params, task_id)

    assert len(fake.calls) == 1
    assert client.get(f"/api/v1/history/{task_id}").json()["status"] == TaskStatus.CANCELLED
    audio = client.get(f"/api/v1/transcripts/{task_id}/audio")
    if retain_audio:
        assert audio.content == synthetic_audio()
    else:
        assert audio.status_code == 404
    assert list(uploads.iterdir()) == []
    again = client.post("/api/v1/transcription/uid-retry-revoked/cancel").json()
    assert again["reason"] == "not-started"
    assert redis_run_mode.is_cancel_requested("uid-retry-revoked") is False


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


def test_last_transient_error_is_a_failure(
        transcribe_media_task, uploads, fake, broadcasts, client):
    attempts = 1 + TRANSIENT_RETRIES
    fake.script = [TransientError("503 服務暫時無法使用")] * attempts
    task_id = str(uuid.uuid4())

    result = transcribe_media_task.apply(args=[task_params(uploads, "uid-gives-up")],
                                         task_id=task_id)

    # 前三次宣告將重試；最後一次照失敗處理，任務不會一直停在處理中
    messages = broadcasts()
    assert result.state == "FAILURE"
    assert len(fake.calls) == attempts
    assert retry_notices(messages) == TRANSIENT_RETRIES
    assert results(messages) == [TaskStatus.FAILED]
    record = client.get(f"/api/v1/history/{task_id}").json()
    assert record["status"] == TaskStatus.FAILED
    assert "503" in record["error_message"]
