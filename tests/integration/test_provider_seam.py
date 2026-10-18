"""接縫 1：透過 API 跑完一個單檔任務，只把供應商換成假供應商（#106）。

其他都走真的：TestClient、sqlite、行程內執行模式、WebSocket 狀態廣播，以及
用 numpy／soundfile 產生的合成 wav 經真實的 ffmpeg 去靜音、轉檔、取得長度。
測試只從外部觀察：狀態廣播、API 回應、存下來的片段與可以下載的輸出格式。
"""
import io
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.task_status import TaskStatus
from app.provider import registry
from tests.support.fake_provider import FAKE_MODEL, FAKE_TERMINABLE_MODEL, FakeProvider

SAMPLE_RATE = 16000
TIMEOUT = 30
TERMINAL = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}


def synthetic_wav(pattern=(2.0, 3.0, 2.0, 3.0, 2.0)) -> bytes:
    """有聲段（正弦波）與靜音段交錯：pattern 依序是有聲、靜音、有聲…的秒數。"""
    parts = []
    for i, seconds in enumerate(pattern):
        t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
        if i % 2 == 0:
            parts.append(0.3 * np.sin(2 * np.pi * 440 * t))
        else:
            parts.append(np.zeros_like(t))
    buffer = io.BytesIO()
    sf.write(buffer, np.concatenate(parts).astype(np.float32), SAMPLE_RATE, format="WAV")
    return buffer.getvalue()


# ─── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """上傳檔、保留音檔、去靜音產物都寫進暫存資料夾。"""
    from app.api import transcription, upload
    from app.core.config import get_settings

    settings = get_settings()
    uploads = tmp_path / "temp_uploads"
    uploads.mkdir()
    monkeypatch.setattr(settings, "temp_uploads_dir", str(uploads))
    monkeypatch.setattr(settings, "audio_store_dir", str(tmp_path / "audio_store"))
    monkeypatch.setattr(settings, "vad_artifacts_dir", str(tmp_path / "vad_artifacts"))
    monkeypatch.setattr(transcription, "TEMP_UPLOADS_DIR", uploads)
    monkeypatch.setattr(upload, "TEMP_UPLOADS_DIR", uploads)
    return tmp_path


@pytest.fixture
def task_db(test_engine):
    """任務在 worker 執行緒裡用 SessionLocal 寫紀錄；指到測試的 sqlite。"""
    from app.database.session import SessionLocal, engine

    SessionLocal.configure(bind=test_engine)
    yield
    SessionLocal.configure(bind=engine)


class RecordingRunMode:
    """包住行程內轉接器，記下 revoke 的參數；其餘照轉。"""

    def __init__(self, inner):
        self._inner = inner
        self.revoked = []

    def revoke(self, task_id, terminate=False):
        self.revoked.append((task_id, terminate))
        self._inner.revoke(task_id, terminate)

    def __getattr__(self, name):
        return getattr(self._inner, name)


@pytest.fixture
def run_mode_spy(in_process_run_mode):
    from app.runtime import run_mode

    spy = RecordingRunMode(in_process_run_mode)
    previous = run_mode.use(spy)
    yield spy
    # 先等任務跑完再換回：任務的取消檢查會呼叫 run_mode.get()
    in_process_run_mode.close(wait=True)
    run_mode.use(previous)


@pytest.fixture
def fake():
    provider = FakeProvider()
    previous = registry.register("fake", lambda api_key: provider)
    yield provider
    if provider.hold is not None:
        provider.hold.set()
    registry.register("fake", previous)


@pytest.fixture
def api(test_engine, data_dir, task_db, run_mode_spy, fake):
    """啟動時選行程內執行模式、啟動 WebSocket 狀態監聽器的 TestClient。"""
    from app.database.session import get_db
    from app.websocket.manager import manager
    from main import app
    from sqlalchemy.orm import sessionmaker

    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    @asynccontextmanager
    async def lifespan(_app):
        manager.start()
        yield
        await manager.shutdown()

    original = app.router.lifespan_context
    app.router.lifespan_context = lifespan
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.router.lifespan_context = original
    app.dependency_overrides.clear()


# ─── helpers ─────────────────────────────────────────────────────────────────

_reader = ThreadPoolExecutor(max_workers=4)


def receive(ws) -> dict:
    """收下一則廣播；逾時直接失敗，不讓 CI 卡住。"""
    return _reader.submit(ws.receive_json).result(timeout=TIMEOUT)


def receive_until_terminal(ws) -> list[dict]:
    messages = []
    while True:
        message = receive(ws)
        messages.append(message)
        if message["status_code"] in TERMINAL:
            return messages


def upload(api: TestClient, name: str = "voice.wav") -> str:
    response = api.post(
        "/api/v1/upload", files={"file": (name, synthetic_wav(), "audio/wav")})
    assert response.status_code == 200, response.text
    return response.json()["filename"]


def submit(ws, filename: str, provider: str = "fake", model: str = FAKE_MODEL):
    ws.send_json({
        "filename": filename,
        "original_filename": "voice.wav",
        "provider": provider,
        "model": model,
        "source_lang": "ja",
    })


def codes(messages: list[dict]) -> list[str]:
    return [m["status_code"] for m in messages]


# ─── 單檔任務跑完 ───────────────────────────────────────────────────────────

SCRIPT = [[
    (0.2, 1.5, 0, "おはよう。"),
    (2.3, 3.6, 1, "こんにちは。"),
    (4.4, 5.6, 0, "またね。"),
]]


def run_to_completion(api, fake, file_uid="uid-complete"):
    fake.script = list(SCRIPT)
    filename = upload(api)
    with api.websocket_connect(f"/api/v1/ws/{file_uid}") as ws:
        submit(ws, filename)
        return receive_until_terminal(ws)


class TestSingleFileTask:
    def test_broadcasts_processing_then_completed(self, api, fake):
        messages = run_to_completion(api, fake)

        assert codes(messages)[-1] == TaskStatus.COMPLETED
        assert set(codes(messages)[:-1]) == {TaskStatus.PROCESSING}
        assert len(messages) > 1
        result = messages[-1]["result"]
        assert result["model"] == FAKE_MODEL
        assert result["audio_duration_seconds"] == pytest.approx(12.0, abs=0.1)

    def test_stores_segments_on_the_original_timeline(self, api, fake):
        task_uuid = run_to_completion(api, fake)[-1]["task_uuid"]

        transcript = api.get(f"/api/v1/transcripts/{task_uuid}").json()
        segments = transcript["segments"]
        assert [(s["speaker"], s["text"]) for s in segments] == [
            ("S0", "おはよう。"), ("S1", "こんにちは。"), ("S0", "またね。")]
        # 去靜音後的時間還原回原音檔：每一句都落在原本的有聲段（0–2、5–7、10–12 秒），
        # 不會落在被剪掉的靜音裡，而且比送進供應商的時間晚
        voiced = [(0.0, 2.0), (5.0, 7.0), (10.0, 12.0)]
        for segment in segments:
            assert any(lo - 0.5 <= segment["start"] <= hi + 0.5 for lo, hi in voiced)
        sent = [line[0] for line in SCRIPT[0]]
        assert [s["start"] for s in segments] == sorted(s["start"] for s in segments)
        assert segments[-1]["start"] > sent[-1]

    @pytest.mark.parametrize("fmt", ["srt", "vtt", "lrc", "txt"])
    def test_every_output_format_downloads(self, api, fake, fmt):
        task_uuid = run_to_completion(api, fake)[-1]["task_uuid"]

        response = api.get(f"/api/v1/history/{task_uuid}/download/{fmt}")
        assert response.status_code == 200
        for text in ("おはよう。", "こんにちは。", "またね。"):
            assert text in response.text

    def test_provider_releases_its_resources(self, api, fake):
        run_to_completion(api, fake)
        # 收尾在完成廣播之後才跑
        deadline = time.monotonic() + TIMEOUT
        while fake.released == 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert fake.released == 1

    def test_failure_is_reported_as_failed(self, api, fake):
        from tests.support.fake_provider import Fail

        fake.script = [Fail("模型壞掉了")]
        filename = upload(api)
        with api.websocket_connect("/api/v1/ws/uid-fail") as ws:
            submit(ws, filename)
            messages = receive_until_terminal(ws)

        assert codes(messages)[-1] == TaskStatus.FAILED
        assert "模型壞掉了" in messages[-1]["status_text"]


# ─── 模型不屬於供應商 ───────────────────────────────────────────────────────

class TestModelMustBelongToProvider:
    @pytest.mark.parametrize("provider, model", [
        ("fake", "gemini-2.5-flash"),
        ("local", FAKE_MODEL),
        ("google", "moss-align"),
        ("no-such-provider", FAKE_MODEL),
    ])
    def test_rejected_with_clear_error(self, api, fake, provider, model):
        filename = upload(api)
        with api.websocket_connect("/api/v1/ws/uid-reject") as ws:
            submit(ws, filename, provider=provider, model=model)
            message = receive(ws)
            assert message["status_code"] == TaskStatus.FAILED
            assert model in message["status_text"] or provider in message["status_text"]
            with pytest.raises(WebSocketDisconnect) as closed:
                receive(ws)
        assert closed.value.code == 1008

        # 沒有派送任何任務，也沒有跑到任何供應商
        cancel = api.post("/api/v1/transcription/uid-reject/cancel").json()
        assert cancel["cancelled"] is False
        assert fake.calls == []


# ─── 取消 ────────────────────────────────────────────────────────────────────

def cancel_when_dispatched(api, file_uid) -> dict:
    """派送本身不廣播：輪詢取消端點，直到任務登記好、取消真的送出。"""
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        response = api.post(f"/api/v1/transcription/{file_uid}/cancel")
        assert response.status_code == 200
        if response.json()["cancelled"]:
            return response.json()
        time.sleep(0.02)
    raise AssertionError(f"{file_uid} 一直沒有派送")


class TestCancel:
    @pytest.mark.parametrize("model, terminate", [
        (FAKE_MODEL, False),
        (FAKE_TERMINABLE_MODEL, True),
    ])
    def test_cancel_queued_and_running_without_provider(
            self, api, fake, run_mode_spy, model, terminate):
        running_uid, queued_uid = f"uid-running-{model}", f"uid-queued-{model}"
        fake.hold = threading.Event()
        fake.script = list(SCRIPT)
        running_file, queued_file = upload(api, "a.wav"), upload(api, "b.wav")

        with api.websocket_connect(f"/api/v1/ws/{running_uid}") as running, \
                api.websocket_connect(f"/api/v1/ws/{queued_uid}") as queued:
            submit(running, running_file, model=model)
            assert fake.started.wait(TIMEOUT)
            # GPU 佇列只有一個 worker：第二個任務排在佇列裡，任務紀錄還沒建立
            submit(queued, queued_file, model=model)

            cancel_when_dispatched(api, queued_uid)
            queued_end = receive_until_terminal(queued)[-1]
            assert queued_end["status_code"] == TaskStatus.CANCELLED

            cancel_when_dispatched(api, running_uid)
            running_end = receive_until_terminal(running)[-1]
            assert running_end["status_code"] == TaskStatus.CANCELLED

        # 能不能強制終止看任務的供應商的模型能力；佇列中的任務撤銷就好，不必終止
        queued_revoke, running_revoke = run_mode_spy.revoked
        assert queued_revoke[1] is False
        assert running_revoke[1] is terminate

        assert len(fake.calls) == 1  # 佇列中的那個從沒開始

        running_log = api.get(f"/api/v1/history/{running_end['task_uuid']}")
        assert running_log.json()["status"] == TaskStatus.CANCELLED
        assert api.get(f"/api/v1/history/{queued_end['task_uuid']}").status_code == 404
