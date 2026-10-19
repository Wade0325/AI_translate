"""接縫 1：透過 API 跑完一個單檔任務，只把供應商換成假供應商（#106）。

其他都走真的：TestClient、sqlite、行程內執行模式、WebSocket 狀態廣播，以及
用 numpy／soundfile 產生的合成音檔經真實的 ffmpeg 轉檔、去靜音、切音檔、取得長度。
測試只從外部觀察：狀態廣播、API 回應、存下來的片段與可以下載的輸出格式。
"""
import io
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import replace

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.task_status import TaskStatus
from app.provider import registry
from tests.support.fake_provider import FAKE_MODEL, Fail, FakeProvider

SAMPLE_RATE = 16000
TIMEOUT = 30
TERMINAL = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
# 合成音檔的有聲段（秒）：有聲 2、靜音 3 交錯，共 12 秒
VOICED = [(0.0, 2.0), (5.0, 7.0), (10.0, 12.0)]


def synthetic_audio(fmt: str = "WAV") -> bytes:
    """有聲段（正弦波）與靜音段交錯的合成音檔，見 VOICED。"""
    samples = np.zeros(12 * SAMPLE_RATE, dtype=np.float32)
    for start, end in VOICED:
        t = np.arange(int((end - start) * SAMPLE_RATE)) / SAMPLE_RATE
        samples[int(start * SAMPLE_RATE):int(end * SAMPLE_RATE)] = 0.3 * np.sin(2 * np.pi * 440 * t)
    buffer = io.BytesIO()
    sf.write(buffer, samples, SAMPLE_RATE, format=fmt)
    return buffer.getvalue()


# ─── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def settings():
    from app.core.config import get_settings
    return get_settings()


@pytest.fixture
def data_dir(tmp_path, monkeypatch, settings):
    """上傳檔、保留音檔、去靜音產物都寫進暫存資料夾。"""
    from app.api import transcription, upload

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
    """包住行程內轉接器，記下 revoke 的參數，其餘照轉。

    行程內執行模式不能強制終止執行緒、會忽略 terminate，「依模型能力決定要不要強制終止」
    只在執行模式的介面上看得到，所以在這個接縫上記錄。
    """

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
    previous = registry.register("fake", provider)
    yield provider
    if provider.hold is not None:
        provider.hold.set()
    registry.register("fake", previous)


@pytest.fixture
def api(test_engine, data_dir, task_db, run_mode_spy, fake):
    """啟動時選行程內執行模式、啟動 WebSocket 狀態監聽器的 TestClient。"""
    from sqlalchemy.orm import sessionmaker

    from app.database.session import get_db
    from app.websocket.manager import manager
    from main import app

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
    fmt, content_type = ("FLAC", "audio/flac") if name.endswith(".flac") else ("WAV", "audio/wav")
    response = api.post(
        "/api/v1/upload", files={"file": (name, synthetic_audio(fmt), content_type)})
    assert response.status_code == 200, response.text
    return response.json()["filename"]


def submit(ws, filename: str, provider: str = "fake", model: str = FAKE_MODEL):
    ws.send_json({
        "filename": filename,
        "original_filename": filename,
        "provider": provider,
        "model": model,
        "source_lang": "ja",
    })


def transcribe(api, file_uid: str, name: str = "voice.wav") -> list[dict]:
    """上傳、送出，收下這個任務的所有廣播直到結束。"""
    filename = upload(api, name)
    with api.websocket_connect(f"/api/v1/ws/{file_uid}") as ws:
        submit(ws, filename)
        return receive_until_terminal(ws)


def stored_segments(api, task_uuid: str) -> list[dict]:
    return api.get(f"/api/v1/transcripts/{task_uuid}").json()["segments"]


def in_voiced_region(t: float) -> bool:
    return any(lo - 0.5 <= t <= hi + 0.5 for lo, hi in VOICED)


def codes(messages: list[dict]) -> list[str]:
    return [m["status_code"] for m in messages]


# ─── 單檔任務跑完 ───────────────────────────────────────────────────────────

SCRIPT = [[
    (0.2, 1.5, 0, "おはよう。"),
    (2.3, 3.6, 1, "こんにちは。"),
    (4.4, 5.6, 0, "またね。"),
]]
TEXTS = ["おはよう。", "こんにちは。", "またね。"]


class TestSingleFileTask:
    @pytest.fixture(autouse=True)
    def _script(self, fake):
        fake.script = list(SCRIPT)

    def test_broadcasts_processing_then_completed(self, api, fake):
        messages = transcribe(api, "uid-complete")

        assert codes(messages)[-1] == TaskStatus.COMPLETED
        assert set(codes(messages)[:-1]) == {TaskStatus.PROCESSING}
        assert len(messages) > 1
        result = messages[-1]["result"]
        assert result["model"] == FAKE_MODEL
        assert result["audio_duration_seconds"] == pytest.approx(12.0, abs=0.1)
        # 沒超過單次能處理的長度：整個語音視圖一次送進供應商
        assert len(fake.calls) == 1

    def test_stores_segments_on_the_original_timeline(self, api):
        task_uuid = transcribe(api, "uid-complete")[-1]["task_uuid"]

        segments = stored_segments(api, task_uuid)
        assert [(s["speaker"], s["text"]) for s in segments] == [
            ("S0", "おはよう。"), ("S1", "こんにちは。"), ("S0", "またね。")]
        # 去靜音後的時間還原回原音檔：每一句都落在原本的有聲段、不在被剪掉的靜音裡，
        # 而且比送進供應商的時間晚
        starts = [s["start"] for s in segments]
        assert all(in_voiced_region(t) for t in starts)
        assert starts == sorted(starts)
        assert starts[-1] > SCRIPT[0][-1][0]

    @pytest.mark.parametrize("fmt", ["srt", "vtt", "lrc", "txt"])
    def test_every_output_format_downloads(self, api, fmt):
        task_uuid = transcribe(api, "uid-complete")[-1]["task_uuid"]

        response = api.get(f"/api/v1/history/{task_uuid}/download/{fmt}")
        assert response.status_code == 200
        for text in TEXTS:
            assert text in response.text

    def test_provider_releases_its_resources(self, api, fake):
        transcribe(api, "uid-complete")
        # 收尾在完成廣播之後才跑
        deadline = time.monotonic() + TIMEOUT
        while fake.released == 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert (fake.opened, fake.released) == (1, 1)

    @pytest.mark.parametrize("step", [Fail("模型壞掉了"), RuntimeError("模型壞掉了")],
                             ids=["failed-result", "raised"])
    def test_failure_is_reported_as_failed(self, api, fake, step):
        fake.script = [step]
        messages = transcribe(api, "uid-fail")

        assert codes(messages)[-1] == TaskStatus.FAILED
        assert "模型壞掉了" in messages[-1]["status_text"]


# ─── 分段轉錄改讀模型能力 ───────────────────────────────────────────────────

class TestChunkedTranscriptionFollowsCapabilities:
    def test_longer_than_single_pass_is_split_at_silence(self, api, fake):
        # 語音視圖約 7 秒，單次只能處理 5 秒 → 在靜音邊界切成兩段。
        # FLAC 先經 ffmpeg 轉成 wav，切段也由 ffmpeg 完成
        fake.model_capabilities = replace(fake.model_capabilities, single_pass_seconds=5.0)
        fake.script = [
            [(0.2, 1.5, 0, "一つ目。")],
            [(0.2, 0.9, 1, "二つ目。"), (1.2, 2.0, 0, "三つ目。")],
        ]
        messages = transcribe(api, "uid-chunked", "voice.flac")

        assert codes(messages)[-1] == TaskStatus.COMPLETED
        assert len(fake.calls) == 2
        segments = stored_segments(api, messages[-1]["task_uuid"])
        assert [s["text"] for s in segments] == ["一つ目。", "二つ目。", "三つ目。"]
        starts = [s["start"] for s in segments]
        assert starts == sorted(starts)
        assert all(in_voiced_region(t) for t in starts)

    def test_without_silence_removal_provider_times_are_kept(self, api, fake):
        fake.model_capabilities = replace(fake.model_capabilities, remove_silence=False)
        fake.script = list(SCRIPT)
        messages = transcribe(api, "uid-no-vad")

        segments = stored_segments(api, messages[-1]["task_uuid"])
        assert [s["start"] for s in segments] == pytest.approx([line[0] for line in SCRIPT[0]])

    @pytest.mark.parametrize("allowed, reported", [
        (False, "模型壞掉了"),
        # 測試環境沒有 Silero，找不到切點；之後分段轉錄會改成切在正中間
        (True, "無法分割音訊檔案"),
    ])
    def test_split_retry_after_failure_follows_capabilities(
            self, api, fake, settings, monkeypatch, allowed, reported):
        # 失敗後切段重試只給夠長的音檔；把門檻降到合成音檔以下
        monkeypatch.setattr(settings, "transcription_max_duration_seconds", 5)
        fake.model_capabilities = replace(
            fake.model_capabilities, split_retry_on_failure=allowed)
        fake.script = [Fail("模型壞掉了")]
        messages = transcribe(api, f"uid-retry-{allowed}")

        assert codes(messages)[-1] == TaskStatus.FAILED
        assert reported in messages[-1]["status_text"]
        assert len(fake.calls) == 1


# ─── 模型不屬於供應商 ───────────────────────────────────────────────────────

MISMATCHES = [
    ("fake", "gemini-2.5-flash"),
    ("local", FAKE_MODEL),
    ("google", "moss-align"),
    ("no-such-provider", FAKE_MODEL),
]


class TestModelMustBelongToProvider:
    @pytest.mark.parametrize("provider, model", MISMATCHES)
    def test_single_file_rejected_with_clear_error(self, api, fake, provider, model):
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
        assert fake.opened == 0

    @pytest.mark.parametrize("provider, model, reason", [
        ("local", "gemini-2.5-flash", "不屬於"),
        ("fake", FAKE_MODEL, "不支援批次"),
    ])
    def test_batch_rejected_with_clear_error(self, api, fake, provider, model, reason):
        with api.websocket_connect("/api/v1/batch/ws/batch-reject") as ws:
            ws.send_json({
                "files": [{"filename": "a.wav", "original_filename": "a.wav", "file_uid": "f1"}],
                "provider": provider,
                "model": model,
                "source_lang": "ja",
            })
            message = receive(ws)
        assert message["file_uid"] == "f1"
        assert message["status_code"] == TaskStatus.FAILED
        assert reason in message["status_text"]
        assert fake.opened == 0


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
    @pytest.mark.parametrize("terminate", [False, True])
    def test_cancel_queued_and_running_without_provider(
            self, api, fake, run_mode_spy, terminate):
        running_uid, queued_uid = f"uid-running-{terminate}", f"uid-queued-{terminate}"
        fake.model_capabilities = replace(fake.model_capabilities, can_terminate=terminate)
        fake.hold = threading.Event()
        fake.script = list(SCRIPT)
        running_file, queued_file = upload(api, "a.wav"), upload(api, "b.wav")

        with api.websocket_connect(f"/api/v1/ws/{running_uid}") as running, \
                api.websocket_connect(f"/api/v1/ws/{queued_uid}") as queued:
            submit(running, running_file)
            assert fake.started.wait(TIMEOUT)
            # GPU 佇列只有一個 worker：第二個任務排在佇列裡，任務紀錄還沒建立
            submit(queued, queued_file)

            cancel_when_dispatched(api, queued_uid)
            queued_end = receive_until_terminal(queued)[-1]
            assert queued_end["status_code"] == TaskStatus.CANCELLED

            cancel_when_dispatched(api, running_uid)
            # 放行之後，不理會取消的供應商會把任務跑完；理會的話任務自己回報已取消
            fake.hold.set()
            endpoint_end = receive_until_terminal(running)[-1]
            task_end = receive_until_terminal(running)[-1]
            assert codes([endpoint_end, task_end]) == [TaskStatus.CANCELLED] * 2

        # 能不能強制終止看任務的供應商的模型能力；佇列中的任務撤銷就好，不必終止
        queued_revoke, running_revoke = run_mode_spy.revoked
        assert queued_revoke[1] is False
        assert running_revoke[1] is terminate

        assert len(fake.calls) == 1  # 佇列中的那個從沒開始
        running_log = api.get(f"/api/v1/history/{task_end['task_uuid']}").json()
        assert running_log["status"] == TaskStatus.CANCELLED
        assert stored_segments(api, task_end["task_uuid"]) == []
        assert api.get(f"/api/v1/history/{queued_end['task_uuid']}").status_code == 404
