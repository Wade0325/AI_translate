"""Gemini 的單檔任務與批次透過 API 跑完：Gemini 轉接器接上假的 google-genai 用戶端（#107）。

這裡不換供應商，只換掉 google-genai 用戶端：批次目前只有 Gemini 支援，遠端檔也只有
Gemini 會留下。其他都走真的：TestClient、sqlite、行程內執行模式、WebSocket 狀態廣播、
ffmpeg 與去靜音。測試只從外部觀察：狀態廣播、API 回應，以及遠端還留著哪些檔案。
"""
import io
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from google.genai import types

from app.core.task_status import TaskStatus
from app.provider import registry
from app.provider.google.provider import GeminiProvider
from tests.support.fake_genai import FakeGenaiClient, Reply, invalid_argument, unavailable

MODEL = "gemini-2.5-flash"
SAMPLE_RATE = 16000
TIMEOUT = 30


def synthetic_audio() -> bytes:
    """有聲 2 秒、靜音 3 秒交錯的合成 wav，共 12 秒。"""
    samples = np.zeros(12 * SAMPLE_RATE, dtype=np.float32)
    for start in (0, 5, 10):
        t = np.arange(2 * SAMPLE_RATE) / SAMPLE_RATE
        samples[start * SAMPLE_RATE:(start + 2) * SAMPLE_RATE] = 0.3 * np.sin(2 * np.pi * 440 * t)
    buffer = io.BytesIO()
    sf.write(buffer, samples, SAMPLE_RATE, format="WAV")
    return buffer.getvalue()


# ─── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def genai():
    return FakeGenaiClient()


class _GeminiWithFakeClient:
    """供應商「google」：建立的 Gemini 轉接器都接上同一個假用戶端，也不真的等。"""

    def __init__(self, genai: FakeGenaiClient):
        self._genai = genai
        self.withdrawn: set[str] = set()
        """不再提供的模型，例如升級後從模型清單拿掉的。"""

    def capabilities(self):
        return {model: capabilities for model, capabilities in GeminiProvider.capabilities().items()
                if model not in self.withdrawn}

    def __call__(self, model: str, api_key: str) -> GeminiProvider:
        return GeminiProvider(model, api_key, client=self._genai, sleep=lambda seconds: None)


@pytest.fixture
def gemini(genai):
    provider = _GeminiWithFakeClient(genai)
    previous = registry.register("google", provider)
    yield provider
    registry.register("google", previous)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """上傳檔、保留音檔、去靜音產物都寫進暫存資料夾。"""
    from app.api import batch, transcription, upload
    from app.core.config import get_settings

    settings = get_settings()
    uploads = tmp_path / "temp_uploads"
    uploads.mkdir()
    monkeypatch.setattr(settings, "temp_uploads_dir", str(uploads))
    monkeypatch.setattr(settings, "audio_store_dir", str(tmp_path / "audio_store"))
    monkeypatch.setattr(settings, "vad_artifacts_dir", str(tmp_path / "vad_artifacts"))
    monkeypatch.setattr(upload, "TEMP_UPLOADS_DIR", uploads)
    monkeypatch.setattr(transcription, "TEMP_UPLOADS_DIR", uploads)
    monkeypatch.setattr(batch, "TEMP_UPLOADS_DIR", uploads)


@pytest.fixture
def task_db(test_engine):
    """任務在 worker 執行緒裡用 SessionLocal 寫紀錄；指到測試的 sqlite。"""
    from app.database.session import SessionLocal, engine

    SessionLocal.configure(bind=test_engine)
    yield
    SessionLocal.configure(bind=engine)


@pytest.fixture
def api(test_engine, data_dir, task_db, in_process_run_mode, gemini):
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
    # 先等任務跑完再換回執行模式與資料庫
    in_process_run_mode.close(wait=True)
    app.router.lifespan_context = original
    app.dependency_overrides.clear()


# ─── helpers ─────────────────────────────────────────────────────────────────

_reader = ThreadPoolExecutor(max_workers=2)


def transcribe(api: TestClient, run_mode, name: str) -> list[dict]:
    """上傳、送出單檔任務，收下所有廣播直到任務結束。file_uid 就是檔名。"""
    response = api.post("/api/v1/upload", files={"file": (name, synthetic_audio(), "audio/wav")})
    assert response.status_code == 200, response.text

    with api.websocket_connect(f"/api/v1/ws/{name}") as ws:
        ws.send_json({"filename": response.json()["filename"], "original_filename": name,
                      "provider": "Google", "model": MODEL, "source_lang": "ja"})
        messages = receive_until(ws, TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
    # 結束的廣播之後任務還在收尾（刪遠端檔就在這裡），等它整個跑完
    wait_until(lambda: not run_mode.is_alive(messages[-1]["task_uuid"]))
    return messages


def run_batch(api: TestClient, run_mode, batch_id: str, names: list[str]) -> list[dict]:
    """上傳、送出批次，收下所有廣播直到批次結束。檔案的 file_uid 就是檔名。"""
    files = []
    for name in names:
        response = api.post("/api/v1/upload", files={"file": (name, synthetic_audio(), "audio/wav")})
        assert response.status_code == 200, response.text
        files.append({"filename": response.json()["filename"], "original_filename": name,
                      "file_uid": name})

    with api.websocket_connect(f"/api/v1/batch/ws/{batch_id}") as ws:
        ws.send_json({"files": files, "provider": "Google", "model": MODEL, "source_lang": "ja"})
        messages = receive_until(ws, TaskStatus.BATCH_COMPLETED)
    # 結束的廣播之後批次還在收尾。等它整個跑完再查 API：
    # 測試的 sqlite 只有一條連線，和 worker 同時用會互相蓋掉交易
    wait_until(lambda: not run_mode.is_alive(messages[-1]["task_uuid"]))
    return messages


def receive_until(ws, *end: TaskStatus) -> list[dict]:
    """收廣播直到收到其中一種結束狀態；逾時直接失敗，不讓 CI 卡住。"""
    messages = []
    while not messages or messages[-1]["status_code"] not in end:
        messages.append(_reader.submit(ws.receive_json).result(timeout=TIMEOUT))
    return messages


def final_status(messages: list[dict]) -> dict[str, dict]:
    """每個檔案最後一則完成或失敗的廣播。"""
    return {m["file_uid"]: m for m in messages
            if m.get("file_uid") and m["status_code"] in (TaskStatus.COMPLETED, TaskStatus.FAILED)}


def history(api: TestClient, original_filename: str) -> dict:
    items = api.get("/api/v1/history", params={"keyword": original_filename}).json()["items"]
    assert len(items) == 1, items
    return items[0]


def wait_until(condition) -> None:
    deadline = time.monotonic() + TIMEOUT
    while not condition():
        assert time.monotonic() < deadline, "等太久"
        time.sleep(0.02)


# ─── 單檔 ────────────────────────────────────────────────────────────────────

def test_single_file_completes_and_its_remote_file_is_deleted(api, in_process_run_mode, genai):
    genai.replies = [Reply(text="[00:01.00]おはよう。")]

    end = transcribe(api, in_process_run_mode, "gemini-single-ok.wav")[-1]

    assert end["status_code"] == TaskStatus.COMPLETED
    assert "おはよう。" in end["result"]["transcripts"]["srt"]
    assert genai.stored == {}  # 任務結束時刪掉上傳到 Gemini 的檔案


def test_single_file_failure_still_deletes_its_remote_file(api, in_process_run_mode, genai):
    # 假用戶端只在檔案已經上傳、處理完時才回這個錯：失敗之前遠端確實有檔案
    genai.replies = [invalid_argument("音檔無法解碼")]

    end = transcribe(api, in_process_run_mode, "gemini-single-fail.wav")[-1]

    assert end["status_code"] == TaskStatus.FAILED
    assert "音檔無法解碼" in end["status_text"]
    assert genai.stored == {}


def test_single_file_is_retried_after_a_transient_error(api, in_process_run_mode, genai):
    # 503 是暫時錯誤：分段轉錄不把它當成這一段失敗，交給執行模式重試整個任務
    genai.replies = [unavailable(), Reply(text="[00:01.00]おはよう。")]

    messages = transcribe(api, in_process_run_mode, "gemini-single-transient.wav")

    assert TaskStatus.FAILED not in [m["status_code"] for m in messages]
    assert messages[-1]["status_code"] == TaskStatus.COMPLETED
    assert "おはよう。" in messages[-1]["result"]["transcripts"]["srt"]
    assert history(api, "gemini-single-transient.wav")["status"] == TaskStatus.COMPLETED
    assert genai.stored == {}  # 兩次執行上傳的遠端檔都刪掉了


# ─── 批次 ────────────────────────────────────────────────────────────────────

def test_every_file_completes_and_remote_files_are_deleted(api, in_process_run_mode, genai):
    genai.batch_outcomes = {0: Reply(text="[00:01.00]おはよう。"), 1: Reply(text="[00:01.00]こんにちは。")}

    messages = run_batch(api, in_process_run_mode, "batch-gemini-ok",
                         ["gemini-ok-a.wav", "gemini-ok-b.wav"])

    assert TaskStatus.BATCH_SUBMITTED in [m["status_code"] for m in messages]
    results = final_status(messages)
    assert {uid: m["status_code"] for uid, m in results.items()} == {
        "gemini-ok-a.wav": TaskStatus.COMPLETED, "gemini-ok-b.wav": TaskStatus.COMPLETED}
    assert "おはよう。" in results["gemini-ok-a.wav"]["result"]["transcripts"]["srt"]
    assert "こんにちは。" in results["gemini-ok-b.wav"]["result"]["transcripts"]["srt"]
    assert genai.stored == {}  # 批次結束時刪掉上傳到 Gemini 的檔案


def test_a_failed_file_does_not_stop_the_others(api, in_process_run_mode, genai):
    genai.batch_outcomes = {0: types.JobError(code=3, message="音檔無法解碼")}

    messages = run_batch(api, in_process_run_mode, "batch-gemini-partial",
                         ["gemini-bad.wav", "gemini-good.wav"])

    results = final_status(messages)
    assert results["gemini-bad.wav"]["status_code"] == TaskStatus.FAILED
    assert results["gemini-bad.wav"]["status_text"].startswith("轉錄失敗")
    assert "音檔無法解碼" in results["gemini-bad.wav"]["status_text"]
    assert results["gemini-good.wav"]["status_code"] == TaskStatus.COMPLETED
    failed = history(api, "gemini-bad.wav")
    assert failed["status"] == TaskStatus.FAILED
    assert "音檔無法解碼" in failed["error_message"]


@pytest.mark.parametrize("model_withdrawn", [False, True], ids=["model-offered", "model-withdrawn"])
def test_recover_fetches_results_after_polling_broke_off(
        api, in_process_run_mode, genai, gemini, model_withdrawn):
    batch_id, name = f"batch-gemini-recover-{model_withdrawn}", f"gemini-recover-{model_withdrawn}.wav"
    # 查詢批次狀態失敗：這一輪把批次標成失敗，但 Gemini 那邊照樣跑完
    genai.failing["batches.get"] = invalid_argument("連線中斷")
    genai.batch_outcomes = {0: Reply(text="[00:01.00]おかえり。")}
    messages = run_batch(api, in_process_run_mode, batch_id, [name])
    assert final_status(messages)[name]["status_code"] == TaskStatus.FAILED
    del genai.failing["batches.get"]
    if model_withdrawn:
        # 批次還在 Gemini 跑的時候升級，新版的模型清單拿掉了送出時的模型
        gemini.withdrawn.add(MODEL)

    # 復原的進度一樣廣播給這個批次
    with api.websocket_connect(f"/api/v1/batch/ws/{batch_id}") as ws:
        response = api.post(f"/api/v1/batch/{batch_id}/recover", json={"api_keys": "test-key"})
        assert response.status_code == 200, response.text
        recovered = final_status(receive_until(ws, TaskStatus.BATCH_COMPLETED))[name]

    assert recovered["status_code"] == TaskStatus.COMPLETED
    assert "おかえり。" in recovered["result"]["transcripts"]["srt"]
    in_process_run_mode.close(wait=True)  # 等復原整個跑完再查 API，理由見 run_batch
    assert history(api, name)["status"] == TaskStatus.COMPLETED
