"""接縫 1：透過 API 跑完一個單檔任務，只把供應商換成假供應商（#106、#113）。

其他都走真的：TestClient、sqlite、行程內執行模式、WebSocket 狀態廣播，以及
用 numpy／soundfile 產生的合成音檔經真實的 ffmpeg 轉檔、去靜音、切音檔、取得長度。
測試只從外部觀察：狀態廣播、API 回應、存下來的任務紀錄與片段、可以下載的輸出格式與
保留音檔，以及暫存資料夾裡有沒有留下檔案。
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
from app.exceptions import TransientError
from app.provider import registry
from app.runtime.run_mode import TRANSIENT_RETRIES
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
    只在執行模式的介面上看得到，所以在這個接縫上記錄。``revokes_delivered`` 設成 False
    時 revoke 不轉給轉接器，模擬 Docker 模式的 worker 離線、收不到 revoke。
    """

    def __init__(self, inner):
        self._inner = inner
        self.revoked = []
        self.revokes_delivered = True

    def revoke(self, task_id, terminate=False):
        self.revoked.append((task_id, terminate))
        if self.revokes_delivered:
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


def leftovers(data_dir) -> list[str]:
    """暫存上傳資料夾裡還留著的檔案：上傳檔，以及去靜音、分段產生的暫存檔。"""
    return sorted(p.name for p in (data_dir / "temp_uploads").iterdir())


def retained_files(data_dir) -> list[str]:
    """保留區裡的檔案。"""
    store = data_dir / "audio_store"
    return sorted(p.name for p in store.iterdir()) if store.exists() else []


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
        # 宣告結果之前就已釋放
        assert (fake.opened, fake.released) == (1, 1)

    @pytest.mark.parametrize("step", [Fail("模型壞掉了"), RuntimeError("模型壞掉了")],
                             ids=["failed-result", "raised"])
    def test_failure_is_reported_as_failed(self, api, fake, step):
        fake.script = [step]
        messages = transcribe(api, "uid-fail")

        assert codes(messages)[-1] == TaskStatus.FAILED
        assert "模型壞掉了" in messages[-1]["status_text"]
        record = api.get(f"/api/v1/history/{messages[-1]['task_uuid']}").json()
        assert record["status"] == TaskStatus.FAILED
        assert "模型壞掉了" in record["error_message"]

    def test_completed_task_is_recorded_and_priced(self, api, fake):
        fake.usage = (200_000, 40_000)
        done = transcribe(api, "uid-priced")[-1]

        # 假模型套用預設價：音訊輸入每百萬 token 1.00 美元、輸出 2.50 美元 → 0.20 + 0.10
        assert done["result"]["tokens_used"] == 240_000
        assert done["result"]["cost"] == pytest.approx(0.30)
        record = api.get(f"/api/v1/history/{done['task_uuid']}").json()
        assert record["status"] == TaskStatus.COMPLETED
        assert record["total_tokens"] == 240_000
        assert record["cost"] == pytest.approx(0.30)
        assert record["audio_duration_seconds"] == pytest.approx(12.0, abs=0.1)
        assert record["service_tier_used"] == "standard"

    def test_flex_tier_applies_the_discount(self, api, fake, settings, monkeypatch):
        monkeypatch.setattr(settings, "flex_cost_discount", 0.5)
        fake.usage = (200_000, 40_000)
        fake.service_tier = "flex"
        done = transcribe(api, "uid-flex")[-1]

        assert done["result"]["cost"] == pytest.approx(0.15)
        record = api.get(f"/api/v1/history/{done['task_uuid']}").json()
        assert record["cost"] == pytest.approx(0.15)
        assert record["service_tier_used"] == "flex"

    def test_provider_progress_reaches_the_screen_before_the_result(self, api, fake):
        fake.reports = ["假供應商：上傳中", "假供應商：轉錄中"]
        messages = transcribe(api, "uid-progress")

        texts = [m["status_text"] for m in messages]
        assert texts.index("假供應商：上傳中") < texts.index("假供應商：轉錄中") < len(texts) - 1
        assert messages[texts.index("假供應商：轉錄中")]["status_code"] == TaskStatus.PROCESSING


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
            # 不放行：假供應商只能從進度與取消物件得知取消，停下之後任務自己回報已取消
            endpoint_end = receive_until_terminal(running)[-1]
            task_end = receive_until_terminal(running)[-1]
            assert codes([endpoint_end, task_end]) == [TaskStatus.CANCELLED] * 2
            assert fake.cancelled == 1

        # 能不能強制終止看任務的供應商的模型能力；佇列中的任務撤銷就好，不必終止
        queued_revoke, running_revoke = run_mode_spy.revoked
        assert queued_revoke[1] is False
        assert running_revoke[1] is terminate

        assert len(fake.calls) == 1  # 佇列中的那個從沒開始
        running_log = api.get(f"/api/v1/history/{task_end['task_uuid']}").json()
        assert running_log["status"] == TaskStatus.CANCELLED
        assert stored_segments(api, task_end["task_uuid"]) == []
        assert api.get(f"/api/v1/history/{queued_end['task_uuid']}").status_code == 404

    def test_cancelled_before_start_is_recorded_without_calling_the_provider(
            self, api, fake, run_mode_spy, data_dir):
        # worker 離線、收不到 revoke：佇列中的任務照樣會開始，開始時從取消旗標得知已取消
        run_mode_spy.revokes_delivered = False
        fake.hold = threading.Event()
        fake.script = list(SCRIPT)
        first_file, second_file = upload(api, "a.wav"), upload(api, "b.wav")

        with api.websocket_connect("/api/v1/ws/uid-first") as first, \
                api.websocket_connect("/api/v1/ws/uid-second") as second:
            submit(first, first_file)
            assert fake.started.wait(TIMEOUT)
            submit(second, second_file)
            cancel_when_dispatched(api, "uid-second")
            receive_until_terminal(second)  # 取消端點的廣播
            fake.hold.set()
            assert receive_until_terminal(first)[-1]["status_code"] == TaskStatus.COMPLETED
            second_end = receive_until_terminal(second)[-1]

        # 任務紀錄是已取消、不是失敗；供應商只轉錄了第一個任務；上傳的音檔照樣保留
        assert second_end["status_code"] == TaskStatus.CANCELLED
        record = api.get(f"/api/v1/history/{second_end['task_uuid']}").json()
        assert record["status"] == TaskStatus.CANCELLED
        assert len(fake.calls) == 1
        audio = api.get(f"/api/v1/transcripts/{second_end['task_uuid']}/audio")
        assert audio.content == synthetic_audio()
        assert leftovers(data_dir) == []


# ─── 收尾 ────────────────────────────────────────────────────────────────────

def cancel_while_transcribing(api, fake, file_uid: str) -> dict:
    """上傳、送出，在供應商轉錄途中取消；回傳任務自己宣告的結果。"""
    fake.hold = threading.Event()
    filename = upload(api)
    with api.websocket_connect(f"/api/v1/ws/{file_uid}") as ws:
        submit(ws, filename)
        assert fake.started.wait(TIMEOUT)
        cancel_when_dispatched(api, file_uid)
        receive_until_terminal(ws)  # 取消端點的廣播
        return receive_until_terminal(ws)[-1]


def run_to_completion(api, fake) -> dict:
    fake.script = list(SCRIPT)
    return transcribe(api, "uid-finish")[-1]


def run_to_failure(api, fake) -> dict:
    fake.script = [Fail("模型壞掉了")]
    return transcribe(api, "uid-finish")[-1]


def run_to_cancellation(api, fake) -> dict:
    return cancel_while_transcribing(api, fake, "uid-finish")


FINISHED_RUNS = pytest.mark.parametrize(
    "run_task", [run_to_completion, run_to_failure, run_to_cancellation],
    ids=["completed", "failed", "cancelled"])


class TestFinishing:
    @FINISHED_RUNS
    def test_audio_is_retained_and_temp_files_cleaned_before_the_result(
            self, api, fake, data_dir, run_task):
        end = run_task(api, fake)

        # 宣告結果時收尾已經做完：上傳的音檔原封不動搬進保留區、可以重播，暫存檔都清掉了
        audio = api.get(f"/api/v1/transcripts/{end['task_uuid']}/audio")
        assert audio.status_code == 200
        assert audio.content == synthetic_audio()
        assert leftovers(data_dir) == []

    @FINISHED_RUNS
    def test_without_retention_no_copy_of_the_audio_is_left(
            self, api, fake, settings, monkeypatch, data_dir, run_task):
        monkeypatch.setattr(settings, "retain_audio", False)
        end = run_task(api, fake)

        # 使用者關掉保留音檔時，任務一結束，上傳的音檔與暫存檔都不留在電腦上
        assert api.get(f"/api/v1/transcripts/{end['task_uuid']}/audio").status_code == 404
        assert retained_files(data_dir) == []
        assert leftovers(data_dir) == []


# ─── 暫時錯誤 ────────────────────────────────────────────────────────────────

class TestTransientError:
    @pytest.fixture(autouse=True)
    def _no_backoff(self, monkeypatch):
        # 執行模式重試前會退避等待真實的時間；測試裡不等
        monkeypatch.setattr("app.runtime.executor.time.sleep", lambda seconds: None)

    @pytest.mark.parametrize("retain_audio", [True, False], ids=["retain", "no-retain"])
    def test_retry_reads_the_kept_input_and_completes(
            self, api, fake, settings, monkeypatch, data_dir, retain_audio):
        monkeypatch.setattr(settings, "retain_audio", retain_audio)
        fake.script = [TransientError("503 服務暫時無法使用"), list(SCRIPT[0])]
        messages = transcribe(api, "uid-transient")

        # 暫時錯誤不算失敗：執行模式重試，重試讀到同一份輸入音檔後完成
        assert TaskStatus.FAILED not in codes(messages)
        assert codes(messages)[-1] == TaskStatus.COMPLETED
        assert len(fake.calls) == 2
        task_uuid = messages[-1]["task_uuid"]
        assert api.get(f"/api/v1/history/{task_uuid}").json()["status"] == TaskStatus.COMPLETED
        # 任務結束時才照保留設定處理輸入音檔；兩次執行的暫存檔都沒留下來
        assert retained_files(data_dir) == ([f"{task_uuid}.wav"] if retain_audio else [])
        assert leftovers(data_dir) == []

    def test_failed_when_retries_run_out(self, api, fake):
        attempts = 1 + TRANSIENT_RETRIES
        fake.script = [TransientError("503 服務暫時無法使用")] * attempts
        messages = transcribe(api, "uid-transient-final")

        # 最後一次也遇到暫時錯誤：照失敗處理，不會一直停在處理中
        assert codes(messages)[-1] == TaskStatus.FAILED
        assert "503" in messages[-1]["status_text"]
        assert len(fake.calls) == attempts
        record = api.get(f"/api/v1/history/{messages[-1]['task_uuid']}").json()
        assert record["status"] == TaskStatus.FAILED
        assert "503" in record["error_message"]
