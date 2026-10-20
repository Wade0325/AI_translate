"""接縫 1：透過 API 跑完一個單檔任務，只把供應商換成假供應商（#106、#113）。

其他都走真的：TestClient、sqlite、行程內執行模式、WebSocket 狀態廣播，以及
用 numpy／soundfile 產生的合成音檔經真實的 ffmpeg 轉檔、去靜音、切音檔、取得長度。
測試只從外部觀察：狀態廣播、API 回應、存下來的任務紀錄與片段、可以下載的輸出格式與
保留音檔，以及暫存資料夾裡有沒有留下檔案。
"""
import io
import os
import re
import subprocess
import sys
import textwrap
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from urllib.parse import unquote

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from gevent import GreenletExit
from starlette.websockets import WebSocketDisconnect

from app.core.task_status import TaskStatus
from app.exceptions import TransientError
from app.provider import registry
from app.runtime import run_mode
from app.runtime.run_mode import TRANSIENT_RETRIES
from tests.support.fake_provider import FAKE_MODEL, Fail, FakeProvider

SAMPLE_RATE = 16000
TIMEOUT = 30
TERMINAL = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
# 合成音檔的有聲段（秒）：有聲 2、靜音 3 交錯，共 12 秒
VOICED = [(0.0, 2.0), (5.0, 7.0), (10.0, 12.0)]


def synthetic_audio(fmt: str = "WAV", voiced=VOICED) -> bytes:
    """有聲段（正弦波）與靜音段交錯的合成音檔，到最後一個有聲段結束；預設見 VOICED。"""
    samples = np.zeros(int(voiced[-1][1] * SAMPLE_RATE), dtype=np.float32)
    for start, end in voiced:
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


class RevokesLost:
    """撤銷送不到（Docker 模式的 worker 離線），其餘照轉；用 ``run_mode.use`` 換上。"""

    def __init__(self, inner):
        self._inner = inner

    def revoke(self, task_id, terminate=False):
        pass

    def __getattr__(self, name):
        return getattr(self._inner, name)


class CancelFlagsDown:
    """取消旗標清不掉（Docker 模式的 Redis 剛好斷線），其餘照轉；用 ``run_mode.use`` 換上。"""

    def __init__(self, inner):
        self._inner = inner

    def clear_cancel(self, file_uid):
        raise ConnectionError("Redis 連不上")

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


def upload(api: TestClient, name: str = "voice.wav", voiced=VOICED) -> str:
    fmt, content_type = ("FLAC", "audio/flac") if name.endswith(".flac") else ("WAV", "audio/wav")
    response = api.post(
        "/api/v1/upload", files={"file": (name, synthetic_audio(fmt, voiced), content_type)})
    assert response.status_code == 200, response.text
    return response.json()["filename"]


def submit(ws, filename: str, provider: str = "fake", model: str = FAKE_MODEL, **fields):
    """送出單檔任務；fields 是請求的其他欄位，例如提示詞與使用者文稿。"""
    ws.send_json({
        "filename": filename,
        "original_filename": filename,
        "provider": provider,
        "model": model,
        "source_lang": "ja",
        **fields,
    })


def transcribe(api, file_uid: str, name: str = "voice.wav", voiced=VOICED,
               **fields) -> list[dict]:
    """上傳（音檔的有聲段見 synthetic_audio）、送出，收下這個任務的所有廣播直到結束。"""
    filename = upload(api, name, voiced)
    with api.websocket_connect(f"/api/v1/ws/{file_uid}") as ws:
        submit(ws, filename, **fields)
        return receive_until_terminal(ws)


def task_rejection(api, file_uid: str, **submit_args) -> str:
    """送出一個該被拒絕的單檔任務，回傳拒絕的訊息。

    被拒絕時只回一則 FAILED 就關閉連線（1008），而且沒有派送任何任務。
    """
    filename = upload(api)
    with api.websocket_connect(f"/api/v1/ws/{file_uid}") as ws:
        submit(ws, filename, **submit_args)
        message = receive(ws)
        with pytest.raises(WebSocketDisconnect) as closed:
            receive(ws)
    assert closed.value.code == 1008
    assert message["status_code"] == TaskStatus.FAILED
    assert api.post(f"/api/v1/transcription/{file_uid}/cancel").json()["cancelled"] is False
    return message["status_text"]


def batch_rejection(api, file_fields: dict | None = None, **fields) -> str:
    """送出只有一個檔案（f1）、該被拒絕的批次，回傳拒絕的訊息。

    fields 是批次層級的欄位（預設用假供應商），file_fields 是那個檔案的欄位。
    """
    with api.websocket_connect("/api/v1/batch/ws/batch-reject") as ws:
        ws.send_json({
            "files": [{"filename": "a.wav", "original_filename": "a.wav", "file_uid": "f1",
                       **(file_fields or {})}],
            "provider": "fake",
            "model": FAKE_MODEL,
            "source_lang": "ja",
            **fields,
        })
        message = receive(ws)
    assert message["file_uid"] == "f1"
    assert message["status_code"] == TaskStatus.FAILED
    return message["status_text"]


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


def kept_uploads(data_dir) -> list[bytes]:
    """暫存上傳資料夾裡還留著的檔案內容。"""
    return [(data_dir / "temp_uploads" / name).read_bytes() for name in leftovers(data_dir)]


def block_audio_store(data_dir) -> None:
    """保留區寫不進去：它的位置被一個檔案佔住，建不了資料夾。"""
    (data_dir / "audio_store").write_bytes(b"")


def run_startup_sweep(engine) -> None:
    """app 啟動時的清掃：卡在處理中的單檔任務記成失敗。

    門檻給 0 小時，當成任務已經逾時；例如 Docker 模式重啟 API 時，還在 GPU worker 上
    跑的長任務也會被記成失敗。
    """
    from sqlalchemy.orm import sessionmaker

    from app.repositories.transcription_log_repository import TranscriptionLogRepository

    with sessionmaker(bind=engine)() as db:
        TranscriptionLogRepository().mark_stale_processing_failed(db, max_age_hours=0)


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

    # 按 token 計價的假模型套用預設價：音訊輸入每百萬 token 1.00 美元、輸出 2.50 美元
    # → 0.20 + 0.10；模型能力寫明免費的（例如本機）不收費，用量照記
    @pytest.mark.parametrize("pricing, cost", [("per_token", 0.30), ("free", 0.0)])
    def test_completed_task_is_recorded_and_priced(self, api, fake, pricing, cost):
        fake.model_capabilities = replace(fake.model_capabilities, pricing=pricing)
        fake.usage = (200_000, 40_000)
        done = transcribe(api, "uid-priced")[-1]

        assert done["result"]["tokens_used"] == 240_000
        assert done["result"]["cost"] == pytest.approx(cost)
        record = api.get(f"/api/v1/history/{done['task_uuid']}").json()
        assert record["status"] == TaskStatus.COMPLETED
        assert record["total_tokens"] == 240_000
        assert record["cost"] == pytest.approx(cost)
        assert record["audio_duration_seconds"] == pytest.approx(12.0, abs=0.1)
        assert record["service_tier_used"] == "standard"

    def test_flex_tier_applies_the_discount(self, api, fake, settings, monkeypatch):
        monkeypatch.setattr(settings, "flex_cost_discount", 0.5)
        fake.model_capabilities = replace(fake.model_capabilities, pricing="per_token")
        fake.usage = (200_000, 40_000)
        fake.service_tier = "flex"
        done = transcribe(api, "uid-flex")[-1]

        assert done["result"]["cost"] == pytest.approx(0.15)
        record = api.get(f"/api/v1/history/{done['task_uuid']}").json()
        assert record["cost"] == pytest.approx(0.15)
        assert record["service_tier_used"] == "flex"

    def test_task_finishing_after_the_startup_sweep_is_recorded_as_completed(
            self, api, fake, test_engine):
        fake.hold = threading.Event()
        filename = upload(api)
        with api.websocket_connect("/api/v1/ws/uid-swept") as ws:
            submit(ws, filename)
            task_uuid = receive(ws)["task_uuid"]
            assert fake.started.wait(TIMEOUT)
            run_startup_sweep(test_engine)
            assert api.get(f"/api/v1/history/{task_uuid}").json()["status"] == TaskStatus.FAILED
            fake.hold.set()
            end = receive_until_terminal(ws)[-1]

        # 任務其實跑完了：照實記成完成，紀錄、片段與輸出格式都和宣告的結果一致
        assert end["status_code"] == TaskStatus.COMPLETED
        assert api.get(f"/api/v1/history/{task_uuid}").json()["status"] == TaskStatus.COMPLETED
        assert [s["text"] for s in stored_segments(api, task_uuid)] == TEXTS
        lrc = api.get(f"/api/v1/history/{task_uuid}/download/lrc").text
        assert all(text in lrc for text in TEXTS)

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


# ─── 輸出格式從片段產生 ─────────────────────────────────────────────────────

class TestOutputFormatsFromSegments:
    @pytest.fixture
    def completed(self, api, fake):
        """片段帶逐字時間的任務；不去靜音，時間軸就是送進供應商的時間。"""
        fake.model_capabilities = replace(fake.model_capabilities, remove_silence=False)
        # 供應商自己的 LRC 是一段一行：「[00:00.20][S0] おはよう。こんにちは。」
        fake.script = [[(0.2, 2.6, 0, "おはよう。こんにちは。",
                         [("おはよう", 0.24, 0.9), ("こんにちは", 1.5, 2.56)])]]
        messages = transcribe(api, "uid-words")
        assert codes(messages)[-1] == TaskStatus.COMPLETED
        return messages[-1]

    @staticmethod
    def download(api, task_uuid: str, fmt: str) -> str:
        response = api.get(f"/api/v1/history/{task_uuid}/download/{fmt}")
        assert response.status_code == 200
        return response.text

    @pytest.mark.parametrize("fmt, expected", [
        ("lrc", "[00:00.24][S0] おはよう。\n[00:01.50][S0] こんにちは。"),
        ("srt", "1\n00:00:00,240 --> 00:00:01,500\n[S0] おはよう。\n\n"
                "2\n00:00:01,500 --> 00:00:06,500\n[S0] こんにちは。\n"),
        ("vtt", "WEBVTT\n\n00:00:00.240 --> 00:00:01.500\n[S0] おはよう。\n\n"
                "00:00:01.500 --> 00:00:06.500\n[S0] こんにちは。\n"),
        ("txt", "[S0] おはよう。\n[S0] こんにちは。"),
    ])
    def test_downloads_break_lines_at_sentences_using_word_timings(
            self, api, completed, fmt, expected):
        assert self.download(api, completed["task_uuid"], fmt) == expected

    @pytest.mark.parametrize("fmt", ["lrc", "srt", "vtt", "txt"])
    def test_completion_broadcast_matches_the_download(self, api, completed, fmt):
        broadcast = completed["result"]["transcripts"][fmt]
        assert broadcast == self.download(api, completed["task_uuid"], fmt)

    def test_silence_removed_inside_a_sentence_counts_toward_12_seconds(self, api, fake):
        # 有聲 0–6 秒、靜音 6–14 秒、有聲 14–20 秒：去靜音剪掉 6.3–13.7 秒（有聲段前後各留 0.3 秒），
        # 語音視圖 12.6 秒。送進供應商的「今日は、ありがとう。」從 1.0 到 8.0 秒，只有 7 秒；
        # 還原回原音檔是 1.0 到 15.4 秒，超過 12 秒，在讀點斷開，第二行落在剪掉的靜音之後
        fake.script = [[(0.8, 8.2, 0, "今日は、ありがとう。",
                         [("今", 1.0, 1.2), ("日", 1.2, 1.4), ("は", 1.4, 1.8),
                          ("ありがとう", 7.0, 8.0)])]]
        messages = transcribe(api, "uid-gap", voiced=[(0.0, 6.0), (14.0, 20.0)])

        assert codes(messages)[-1] == TaskStatus.COMPLETED
        assert self.download(api, messages[-1]["task_uuid"], "lrc") == (
            "[00:01.00][S0] 今日は、\n[00:14.40][S0] ありがとう。")

    def test_segment_without_text_and_word_without_a_time(self, api, fake):
        # 沒有文字的片段不產生行；有詞缺時間的片段不知道怎麼對到句子，整段一行
        fake.model_capabilities = replace(fake.model_capabilities, remove_silence=False)
        fake.script = [[(0.2, 0.9, 0, None),
                        (1.0, 2.6, 1, "おはよう。こんにちは。",
                         [("おはよう", 1.04, 1.6), ("こんにちは", None, 2.56)])]]
        messages = transcribe(api, "uid-untimed")

        assert codes(messages)[-1] == TaskStatus.COMPLETED
        assert self.download(api, messages[-1]["task_uuid"], "lrc") == (
            "[00:01.00][S1] おはよう。こんにちは。")


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
        reason = task_rejection(api, "uid-reject", provider=provider, model=model)

        assert model in reason or provider in reason
        # 沒有跑到任何供應商
        assert fake.opened == 0

    @pytest.mark.parametrize("provider, model, reason", [
        ("local", "gemini-2.5-flash", "不屬於"),
        ("fake", FAKE_MODEL, "不支援批次"),
    ])
    def test_batch_rejected_with_clear_error(self, api, fake, provider, model, reason):
        assert reason in batch_rejection(api, provider=provider, model=model)
        assert fake.opened == 0


class TestStoredProviderName:
    def test_task_record_stores_the_listed_name_whatever_the_request_spelling(
            self, api, fake, db_session):
        # 任務紀錄存的是供應商清單上的名稱，不是請求的原樣：舊前端送 Google、直接呼叫 API
        # 的人可能送 GOOGLE，存下來都要是同一個值（#97）
        from app.repositories.transcription_log_repository import TranscriptionLogRepository

        fake.script = list(SCRIPT)
        task_uuid = transcribe(api, "uid-spelling", provider="FAKE")[-1]["task_uuid"]

        db_session.expire_all()
        assert TranscriptionLogRepository().get(db_session, task_uuid).provider == "fake"


# ─── 模型能力端點（#108） ───────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
# 前端只在這裡讀端點的欄位（供應商、模型與模型能力）
FRONTEND_PROVIDER_LIST_READER = REPO_ROOT / "frontend" / "src" / "utils" / "providerList.js"


def listed_capabilities(api) -> dict:
    """GET /providers 攤平成 {(供應商, 模型): 模型能力}。"""
    response = api.get("/api/v1/providers")
    assert response.status_code == 200
    return {(entry["provider"], item["model"]): item["capabilities"]
            for entry in response.json() for item in entry["models"]}


def listed_providers(api) -> dict:
    """GET /providers 依供應商名稱排成 {供應商: 清單上的那一項}。"""
    response = api.get("/api/v1/providers")
    assert response.status_code == 200
    return {entry["provider"]: entry for entry in response.json()}


def listed_fields(api) -> set:
    """GET /providers 回的所有欄位名稱：供應商、模型與模型能力三層。"""
    fields = set()
    for entry in api.get("/api/v1/providers").json():
        fields |= entry.keys()
        for item in entry["models"]:
            fields |= item.keys() | item["capabilities"].keys()
    return fields


class TestModelCapabilitiesEndpoint:
    def test_lists_each_model_of_each_provider_with_its_capabilities(self, api, fake):
        # 回的是供應商當下回報的模型能力，不是寫死的副本
        fake.model_capabilities = replace(
            fake.model_capabilities, single_pass_seconds=42.0, accepts_prompt=False)

        assert listed_capabilities(api)[("fake", FAKE_MODEL)] == {
            "single_pass_seconds": 42.0,
            "queue": "local_asr",
            "can_terminate": False,
            "split_retry_on_failure": False,
            "accepts_prompt": False,
            "accepts_user_text": True,
            "supports_batch": False,
            "pricing": "free",
            "remove_silence": True,
        }

    def test_local_models_take_no_prompt_or_user_text_gemini_models_do(self, api):
        listed = listed_capabilities(api)
        local = {model: c for (provider, model), c in listed.items() if provider == "local"}
        gemini = {model: c for (provider, model), c in listed.items() if provider == "google"}

        assert set(local) == {"moss-align", "moss-qwen3-asr", "vibevoice-qwen3-asr"}
        assert {"gemini-3.5-flash", "gemini-2.5-flash"} <= set(gemini)
        assert not any(c["accepts_prompt"] or c["accepts_user_text"] for c in local.values())
        assert all(c["accepts_prompt"] and c["accepts_user_text"] for c in gemini.values())

    def test_says_which_providers_need_the_users_api_key(self, api):
        # 轉錄頁送出前依這一項確認設定了金鑰，不再寫死哪個供應商不用（#97）
        listed = listed_providers(api)

        assert listed["google"]["requires_api_key"] is True
        assert listed["local"]["requires_api_key"] is False

    def test_names_providers_and_models_for_the_screen_default_model_first(self, api):
        # 轉錄頁先選供應商、再選它的模型，名稱與預設（清單上的第一個）都從這裡來（#97）
        listed = listed_providers(api)

        assert (listed["local"]["label"], listed["google"]["label"]) == ("本機", "Gemini")
        assert [(m["model"], m["label"]) for m in listed["local"]["models"]] == [
            ("moss-align", "MOSS-Transcribe-Diarize"),
            ("moss-qwen3-asr", "MOSS + Qwen3-ASR"),
            ("vibevoice-qwen3-asr", "VibeVoice + Qwen3-ASR（舊版）"),
        ]
        gemini = listed["google"]["models"]
        assert gemini[0]["model"] == "gemini-3.5-flash"
        assert all(m["label"] == m["model"] for m in gemini)

    def test_listing_does_not_import_torch(self):
        # 列模型能力的是 API 行程（Docker 模式的 API 容器沒有顯卡，也不裝 torch）：
        # 依顯卡容量收斂的單次長度只在真的要轉錄的轉接器裡算。另開一個行程，記下任何
        # import torch 的嘗試（沒裝 torch 的 CI 上也抓得到），只看呼叫端點的那一段
        probe = textwrap.dedent("""
            import sys

            attempts = []

            class RecordTorch:
                def find_spec(self, name, path=None, target=None):
                    if name.split(".")[0] == "torch":
                        attempts.append(name)
                        raise ImportError("probe: torch blocked")
                    return None

            sys.meta_path.insert(0, RecordTorch())
            from fastapi.testclient import TestClient
            from main import app

            attempts.clear()
            response = TestClient(app).get("/api/v1/providers")
            print("PROBE", response.status_code, sorted(set(attempts)))
        """)
        result = subprocess.run(
            [sys.executable, "-c", probe], cwd=BACKEND_DIR, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=120,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"})

        assert result.returncode == 0, result.stderr
        probe_lines = [line for line in result.stdout.splitlines() if line.startswith("PROBE ")]
        assert probe_lines == ["PROBE 200 []"], result.stdout

    def test_frontend_reads_only_fields_the_endpoint_lists(self, api):
        # 前端讀不到的欄位一律當成支援、不用金鑰（還沒載入時不限制）：欄位一改名，畫面就
        # 默默全部開放。端點的欄位是 snake_case，前端自己的名稱是 camelCase
        source = FRONTEND_PROVIDER_LIST_READER.read_text(encoding="utf-8")
        read = set(re.findall(r"\.([a-z]+(?:_[a-z]+)+)\b", source))

        assert {"accepts_prompt", "accepts_user_text", "supports_batch",
                "requires_api_key"} <= read
        assert read <= listed_fields(api)


# ─── 模型不吃的輸入（#108） ─────────────────────────────────────────────────

class TestInputsTheModelDoesNotTake:
    @pytest.mark.parametrize("fields, reported", [
        ({"prompt": "語助詞也要寫出來"}, "提示詞"),
        ({"original_text": "おはよう。こんにちは。"}, "使用者文稿"),
    ], ids=["prompt", "user-text"])
    def test_local_model_rejects_them_with_clear_error(self, api, fields, reported):
        reason = task_rejection(
            api, "uid-local-input", provider="local", model="moss-align", **fields)

        assert "moss-align" in reason
        assert reported in reason

    def test_model_that_takes_them_runs_as_usual(self, api, fake):
        fake.script = list(SCRIPT)

        messages = transcribe(api, "uid-with-inputs",
                              prompt="語助詞也要寫出來", original_text="おはよう。")

        assert codes(messages)[-1] == TaskStatus.COMPLETED
        assert len(fake.calls) == 1

    @pytest.mark.parametrize("fields", [
        {"prompt": None, "original_text": None},
        {"prompt": "", "original_text": ""},
        {"prompt": " \n", "original_text": "\t"},
    ], ids=["null", "empty", "blank"])
    def test_unfilled_inputs_are_submitted_as_usual(self, api, fake, fields):
        fake.model_capabilities = replace(
            fake.model_capabilities, accepts_prompt=False, accepts_user_text=False)
        fake.script = list(SCRIPT)

        messages = transcribe(api, "uid-unfilled", **fields)

        assert codes(messages)[-1] == TaskStatus.COMPLETED

    @pytest.mark.parametrize("batch_prompt, file_prompt", [
        ("語助詞也要寫出來", None),
        (None, "語助詞也要寫出來"),
    ], ids=["batch-prompt", "file-prompt"])
    def test_batch_rejects_them_with_clear_error(self, api, fake, batch_prompt, file_prompt):
        fake.model_capabilities = replace(
            fake.model_capabilities, supports_batch=True, accepts_prompt=False)

        reason = batch_rejection(api, file_fields={"prompt": file_prompt}, prompt=batch_prompt)

        assert "提示詞" in reason
        assert fake.opened == 0

    def test_batch_on_model_without_batch_reports_that_first(self, api, fake):
        # 整批都跑不了時先說批次：先說提示詞的話，使用者清掉之後還會再被拒一次
        fake.model_capabilities = replace(
            fake.model_capabilities, supports_batch=False, accepts_prompt=False)

        reason = batch_rejection(api, prompt="語助詞也要寫出來")

        assert "不支援批次" in reason
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

    def test_provider_that_ignores_the_cancel_does_not_complete_the_task(self, api, fake):
        fake.ignores_cancel = True
        fake.hold = threading.Event()
        fake.script = list(SCRIPT)
        filename = upload(api)
        with api.websocket_connect("/api/v1/ws/uid-ignores-cancel") as ws:
            submit(ws, filename)
            assert fake.started.wait(TIMEOUT)
            cancel_when_dispatched(api, "uid-ignores-cancel")
            endpoint_end = receive_until_terminal(ws)[-1]
            fake.hold.set()  # 供應商不理會取消，照樣轉完
            task_end = receive_until_terminal(ws)[-1]

        # 使用者已經取消：任務維持已取消，畫面不會從已取消跳回完成，也不存片段
        assert codes([endpoint_end, task_end]) == [TaskStatus.CANCELLED] * 2
        record = api.get(f"/api/v1/history/{task_end['task_uuid']}").json()
        assert record["status"] == TaskStatus.CANCELLED
        assert stored_segments(api, task_end["task_uuid"]) == []

    @pytest.mark.parametrize("error", [TransientError("503 服務暫時無法使用"), RuntimeError("連線中斷")],
                             ids=["transient", "failure"])
    def test_error_after_the_cancel_is_a_cancellation(self, api, fake, error):
        fake.raises_when_cancelled = error
        fake.hold = threading.Event()
        filename = upload(api)
        with api.websocket_connect("/api/v1/ws/uid-error-after-cancel") as ws:
            submit(ws, filename)
            assert fake.started.wait(TIMEOUT)
            cancel_when_dispatched(api, "uid-error-after-cancel")
            endpoint_end = receive_until_terminal(ws)[-1]
            task_end = receive_until_terminal(ws)[-1]

        # 使用者取消之後才冒出的錯誤（例如 503 剛好回來）：不重試，也不算失敗
        assert codes([endpoint_end, task_end]) == [TaskStatus.CANCELLED] * 2
        assert len(fake.calls) == 1
        record = api.get(f"/api/v1/history/{task_end['task_uuid']}").json()
        assert record["status"] == TaskStatus.CANCELLED

    def test_cancelled_before_start_is_recorded_without_calling_the_provider(
            self, api, fake, data_dir):
        fake.hold = threading.Event()
        fake.script = list(SCRIPT)
        first_file, second_file = upload(api, "a.wav"), upload(api, "b.wav")

        with api.websocket_connect("/api/v1/ws/uid-first") as first, \
                api.websocket_connect("/api/v1/ws/uid-second") as second:
            submit(first, first_file)
            assert fake.started.wait(TIMEOUT)
            submit(second, second_file)
            # worker 離線、收不到撤銷：佇列中的任務照樣會開始，開始時才從取消旗標得知已取消
            reachable = run_mode.use(RevokesLost(run_mode.get()))
            try:
                cancel_when_dispatched(api, "uid-second")
            finally:
                run_mode.use(reachable)
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


def run_to_termination(api, fake) -> dict:
    """在轉錄途中取消，執行模式強制終止任務；等任務整個結束，回傳取消端點的廣播。

    Docker 模式的 gevent worker 強制終止時在任務裡丟 GreenletExit（BaseException，不是
    Exception），被終止的任務自己不會再宣告結果。行程內執行模式不能強制終止，由假供應商
    在看到取消時代為丟出。
    """
    fake.raises_when_cancelled = GreenletExit()
    fake.hold = threading.Event()
    filename = upload(api)
    with api.websocket_connect("/api/v1/ws/uid-finish") as ws:
        submit(ws, filename)
        assert fake.started.wait(TIMEOUT)
        cancel_when_dispatched(api, "uid-finish")
        end = receive_until_terminal(ws)[-1]
    # 沒有結果可等：關閉執行模式，等裡面的任務整個跑完
    run_mode.get().close(wait=True)
    return end


FINISHED_RUNS = pytest.mark.parametrize(
    "run_task", [run_to_completion, run_to_failure, run_to_cancellation, run_to_termination],
    ids=["completed", "failed", "cancelled", "terminated"])


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

    @FINISHED_RUNS
    def test_upload_is_kept_when_the_audio_store_cannot_be_written(
            self, api, fake, data_dir, run_task):
        block_audio_store(data_dir)
        end = run_task(api, fake)

        # 保留音檔開著卻保留不成：上傳檔是唯一的一份，不刪，留在暫存區；暫存檔照樣清掉
        assert api.get(f"/api/v1/transcripts/{end['task_uuid']}/audio").status_code == 404
        assert kept_uploads(data_dir) == [synthetic_audio()]

    def test_a_failing_step_does_not_stop_the_rest_or_change_the_result(self, api, fake, data_dir):
        fake.hold = threading.Event()
        fake.script = list(SCRIPT)
        filename = upload(api)
        with api.websocket_connect("/api/v1/ws/uid-flags-down") as ws:
            submit(ws, filename)
            assert fake.started.wait(TIMEOUT)
            healthy = run_mode.use(CancelFlagsDown(run_mode.get()))
            try:
                fake.hold.set()
                end = receive_until_terminal(ws)[-1]
            finally:
                run_mode.use(healthy)

        # 清不掉取消旗標，任務照樣完成；音檔照樣保留，暫存檔與供應商資源照樣清掉
        assert end["status_code"] == TaskStatus.COMPLETED
        assert api.get(f"/api/v1/transcripts/{end['task_uuid']}/audio").content == synthetic_audio()
        assert leftovers(data_dir) == []
        assert fake.released == 1


# ─── 暫時錯誤 ────────────────────────────────────────────────────────────────

class TestTransientError:
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

    def test_retry_with_an_unwritable_audio_store_keeps_the_upload(self, api, fake, data_dir):
        block_audio_store(data_dir)
        fake.script = [TransientError("503 服務暫時無法使用"), list(SCRIPT[0])]
        messages = transcribe(api, "uid-transient-store-blocked")

        # 兩次執行都保留不成：重試從暫存區讀到同一份輸入完成，結束時也不刪它
        assert codes(messages)[-1] == TaskStatus.COMPLETED
        assert len(fake.calls) == 2
        assert kept_uploads(data_dir) == [synthetic_audio()]

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


# ─── 非 ASCII 檔名 ───────────────────────────────────────────────────────────

def download_filename(response) -> str:
    """Content-Disposition 標頭給的檔名；非 ASCII 的檔名照 RFC 5987 寫成 filename*=utf-8''…。"""
    header = response.headers["content-disposition"]
    match = re.search(r"filename\*=utf-8''([^;]+)", header, re.IGNORECASE)
    assert match, header
    return unquote(match.group(1))


class TestNonAsciiFilename:
    """日文、中文檔名的音檔走完上傳 → ffmpeg → 下載。

    CI 的 Windows job 刻意不開 UTF-8 模式（PYTHONUTF8），和使用者的電腦一樣用系統碼頁：
    檔名經過暫存路徑、ffmpeg 的參數與輸出、任務紀錄與下載，哪一處用了系統碼頁就會在那裡出錯。
    """

    @pytest.mark.parametrize("name, srt_name", [
        ("おはようの録音.flac", "おはようの録音.srt"),
        ("會議錄音.flac", "會議錄音.srt"),
    ], ids=["ja", "zh"])
    def test_goes_through_ffmpeg_and_downloads(self, api, fake, data_dir, name, srt_name):
        # FLAC 先經 ffmpeg 轉成 wav 再去靜音；單次只能處理 5 秒，再由 ffmpeg 在靜音處切成兩段
        fake.model_capabilities = replace(fake.model_capabilities, single_pass_seconds=5.0)
        fake.script = [
            [(0.2, 1.5, 0, "一つ目。")],
            [(0.2, 0.9, 1, "二つ目。"), (1.2, 2.0, 0, "三つ目。")],
        ]
        done = transcribe(api, "uid-non-ascii", name)[-1]

        assert done["status_code"] == TaskStatus.COMPLETED
        assert len(fake.calls) == 2
        assert done["result"]["audio_duration_seconds"] == pytest.approx(12.0, abs=0.1)
        # 歷史紀錄列出原本的檔名，輸出格式照它命名下載
        task_uuid = done["task_uuid"]
        assert api.get(f"/api/v1/history/{task_uuid}").json()["original_filename"] == name
        srt = api.get(f"/api/v1/history/{task_uuid}/download/srt")
        assert srt.status_code == 200
        assert all(text in srt.text for text in ["一つ目。", "二つ目。", "三つ目。"])
        assert download_filename(srt) == srt_name
        # 上傳的音檔原封不動保留下來、可以重播，轉檔與切段的暫存檔都清掉了
        audio = api.get(f"/api/v1/transcripts/{task_uuid}/audio")
        assert audio.content == synthetic_audio("FLAC")
        assert download_filename(audio) == name
        assert leftovers(data_dir) == []
