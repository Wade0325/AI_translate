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
