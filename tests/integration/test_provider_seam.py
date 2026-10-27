"""接縫 1：透過 API 跑完一個單檔任務，只把供應商換成假供應商（#106、#111、#113）。

其他都走真的：TestClient、sqlite、行程內執行模式、WebSocket 狀態廣播，以及
用 numpy／soundfile 產生的合成音檔經真實的 ffmpeg 轉檔、去靜音、切音檔、取得長度。
測試只從外部觀察：狀態廣播、API 回應、存下來的任務紀錄與片段、可以下載的輸出格式與
保留音檔，以及暫存資料夾裡有沒有留下檔案。唯一的例外是凍結的原始轉錄副本（ADR-0007）：
還沒有讀它的介面，只能從任務紀錄看（見 :func:`frozen_original`）。
"""
import json
import os
import re
import subprocess
import sys
import textwrap
import threading
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from pathlib import Path
from urllib.parse import unquote

import pytest
import soundfile as sf
from gevent import GreenletExit
from starlette.websockets import WebSocketDisconnect

from app.core.default_prompt import build_prompt
from app.core.task_status import TaskStatus
from app.exceptions import TransientError
from app.runtime import run_mode
from tests.support.db_faults import writes_fail
from tests.support.fake_provider import FAKE_MODEL, Fail, ServedAs
from tests.support.synthetic_audio import VOICED, synthetic_audio
from tests.support.task_api import (
    download,
    flat_times,
    leftovers,
    ping,
    receive,
    stored_segments,
    upload,
)
from tests.support.waiting import cancel_when_dispatched, wait_until

TIMEOUT = 30
TERMINAL = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}


# ─── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def settings():
    from app.core.config import get_settings
    return get_settings()


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
    """任務結束時清不掉登記與取消旗標（Docker 模式的 Redis 剛好斷線），其餘照轉；
    用 ``run_mode.use`` 換上。"""

    def __init__(self, inner):
        self._inner = inner

    def task_ended(self, file_uid, task_id):
        raise ConnectionError("Redis 連不上")

    def __getattr__(self, name):
        return getattr(self._inner, name)


class FinishingHeld:
    """任務收尾到最後一步（清掉登記與取消旗標）時停住，直到測試放行；其餘照轉。

    只停第一次：之後（例如取消端點）的呼叫照常。用 ``run_mode.use`` 換上。
    """

    def __init__(self, inner):
        self._inner = inner
        self.reached = threading.Event()
        self.release = threading.Event()

    def task_ended(self, file_uid, task_id):
        if not self.reached.is_set():
            self.reached.set()
            self.release.wait(TIMEOUT)
        self._inner.task_ended(file_uid, task_id)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class DispatchHeld:
    """派送停在交給執行模式之前，直到測試放行；其餘照轉。用 ``run_mode.use`` 換上。"""

    def __init__(self, inner):
        self._inner = inner
        self.reached = threading.Event()
        self.release = threading.Event()

    def submit_transcription(self, task_id, task_params_dict, queue):
        self.reached.set()
        self.release.wait(TIMEOUT)
        self._inner.submit_transcription(task_id, task_params_dict, queue)

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
def api(api, run_mode_spy, fake):
    """換上記錄撤銷的執行模式與假供應商。結束時假供應商先放行還停著的轉錄，再等任務跑完。"""
    return api


# ─── helpers ─────────────────────────────────────────────────────────────────

def receive_until_terminal(ws) -> list[dict]:
    messages = []
    while True:
        message = receive(ws)
        messages.append(message)
        if message["status_code"] in TERMINAL:
            return messages


def submit(ws, filename: str, provider: str = "fake", model: str = FAKE_MODEL,
           original_filename: str | None = None, **fields):
    """送出單檔任務；沒給原檔名時用上傳後的檔名。fields 是請求的其他欄位，例如提示詞與使用者文稿。"""
    ws.send_json({
        "filename": filename,
        "original_filename": original_filename or filename,
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
        submit(ws, filename, original_filename=name, **fields)
        return receive_until_terminal(ws)


def cancel_after_the_provider_finished(api, fake, file_uid: str) -> dict:
    """上傳、送出，在供應商轉錄時取消；供應商不理會取消、照樣轉完手上這一段。回傳任務自己宣告的
    結果（取消端點的廣播之後那一則）。"""
    fake.ignores_cancel = True
    fake.hold = threading.Event()
    filename = upload(api)
    with api.websocket_connect(f"/api/v1/ws/{file_uid}") as ws:
        submit(ws, filename)
        assert fake.started.wait(TIMEOUT)
        cancel_when_dispatched(api, file_uid)
        receive_until_terminal(ws)  # 取消端點的廣播
        fake.hold.set()
        return receive_until_terminal(ws)[-1]


def task_rejection(api, file_uid: str, filename: str | None = None, **submit_args) -> str:
    """送出一個該被拒絕的單檔任務，回傳拒絕的訊息；沒給上傳檔名時先上傳一個音檔。

    被拒絕時只回一則 FAILED 就關閉連線（1008），而且沒有派送任何任務。
    """
    if filename is None:
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


def frozen_original(engine, task_uuid: str) -> str | None:
    """任務紀錄裡凍結的原始轉錄副本（ADR-0007）。

    下載不讀它，也還沒有讀它的介面（v0.2 的校正才會用到），只能從任務紀錄看。
    """
    from sqlalchemy.orm import sessionmaker

    from app.repositories.history_repository import HistoryRepository

    with sessionmaker(bind=engine)() as db:
        return HistoryRepository().get_log_by_uuid(db, task_uuid).lrc_content


def in_voiced_region(t: float) -> bool:
    return any(lo - 0.5 <= t <= hi + 0.5 for lo, hi in VOICED)


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


# ─── 去靜音：語音視圖（#111） ───────────────────────────────────────────────

MOSTLY_VOICED = [(0.0, 10.0), (11.5, 21.5)]
"""有聲 0–10、11.5–21.5 秒，中間靜音 1.5 秒：語音佔比約 96%，不低於門檻。"""

EARLY_GAP = [(0.0, 5.0), (6.5, 21.5)]
"""有聲 0–5、6.5–21.5 秒，中間靜音 1.5 秒：語音佔比約 96%，不低於門檻。靜音的正中間在 5.75 秒，
不在音檔的正中間（10.75 秒）。"""

LONG_GAP = [(0.0, 6.0), (14.0, 20.0)]
"""有聲 0–6 秒、靜音 6–14 秒、有聲 14–20 秒。去靜音剪掉 6.3–13.7 秒（有聲段前後各留 0.3 秒），
語音視圖 12.6 秒，兩個有聲段在語音視圖的 6.3 秒交界。"""

JUNCTIONS = pytest.mark.parametrize(
    "junction", [6.3 - 5e-7, 6.3 - 1e-9, 6.3, 6.3 + 1e-9, 6.3 + 5e-7],
    ids=["5e-7-before", "1e-9-before", "exactly", "1e-9-after", "5e-7-after"])
"""LONG_GAP 的交界，以及浮點誤差讓它差一點點的情況，都在容許的 1e-6 秒以內。"""


class TestSpeechView:
    """測試環境和 CI 一樣沒有 Silero（tests/conftest.py 讓它 import 直接失敗）：去靜音只看音量，
    剪靜音與找切點都用不到 Silero。"""

    def test_mostly_silent_audio_is_sent_without_its_silences(self, api, fake):
        # 語音佔比 60%（見 VOICED），低於門檻：剪掉靜音、有聲段前後各留 0.3 秒，送進供應商的是
        # 0–2.3、4.7–7.3、9.7–12 秒接成的 7.2 秒
        fake.script = [[(0.2, 1.5, 0, "おはよう。"), (3.0, 3.6, 1, "こんにちは。"),
                        (5.5, 6.2, 0, "またね。")]]
        messages = transcribe(api, "uid-speech-only")

        assert codes(messages)[-1] == TaskStatus.COMPLETED
        assert fake.durations == [pytest.approx(7.2, abs=0.01)]
        # 片段的時間還原回原音檔：第二句落在第二個有聲段，第三句落在第三個
        segments = stored_segments(api, messages[-1]["task_uuid"])
        assert [s["text"] for s in segments] == ["おはよう。", "こんにちは。", "またね。"]
        assert flat_times(segments) == pytest.approx([0.2, 1.5, 5.4, 6.0, 10.3, 11.0])

    def test_times_past_the_end_are_clamped_to_the_last_voiced_part(self, api, fake):
        # 模型給的時間超出 7.2 秒的語音視圖（例如浮點誤差）：還原成最後一個有聲段的結尾 12 秒，
        # 這一句不會被丟掉
        fake.script = [[(6.5, 7.6, 0, "またね。")]]
        messages = transcribe(api, "uid-past-the-end")

        assert flat_times(stored_segments(api, messages[-1]["task_uuid"])) == pytest.approx(
            [11.3, 12.0])

    def test_mostly_speech_audio_is_sent_as_it_is(self, api, fake):
        # 幾乎全是語音的音檔剪不到什麼：送原音檔，時間原樣存下
        fake.script = [[(0.5, 2.0, 0, "おはよう。"), (12.0, 13.5, 1, "こんにちは。")]]
        messages = transcribe(api, "uid-mostly-speech", voiced=MOSTLY_VOICED)

        assert codes(messages)[-1] == TaskStatus.COMPLETED
        assert fake.durations == [pytest.approx(21.5, abs=0.01)]
        assert flat_times(stored_segments(api, messages[-1]["task_uuid"])) == pytest.approx(
            [0.5, 2.0, 12.0, 13.5])

    def test_model_that_keeps_silences_gets_the_original_cut_at_silences(
            self, api, fake, data_dir):
        # 模型能力是不剪靜音：送原音檔，去靜音找到的靜音（2.3–4.7、7.3–9.7 秒）照樣當切點，
        # 切在正中間。單次只能處理 5 秒：12 秒的原音檔在 3.5 秒切開，後面 8.5 秒再在 8.5 秒切開
        fake.model_capabilities = replace(
            fake.model_capabilities, remove_silence=False, single_pass_seconds=5.0)
        fake.script = [[(0.5, 1.5, 0, "一つ目。")], [(2.0, 3.0, 1, "二つ目。")],
                       [(2.0, 3.0, 0, "三つ目。")]]
        messages = transcribe(api, "uid-keeps-silences")

        assert codes(messages)[-1] == TaskStatus.COMPLETED
        assert fake.durations == pytest.approx([3.5, 5.0, 3.5], abs=0.01)
        # 每一段平移回原音檔的時間軸就是原音檔的時間，沒有要還原的剪掉的靜音。後面 8.5 秒切了
        # 兩層，片段 key 的前綴由外往內接
        segments = stored_segments(api, messages[-1]["task_uuid"])
        assert flat_times(segments) == pytest.approx([0.5, 1.5, 5.5, 6.5, 10.5, 11.5])
        assert [s["seg_key"] for s in segments] == ["a.0000", "b.a.0000", "b.b.0000"]
        assert leftovers(data_dir) == []

    def test_model_that_keeps_silences_leaves_mostly_speech_audio_to_silero(self, api, fake):
        # 幾乎全是語音的音檔（見 EARLY_GAP）：不剪靜音的模型也不拿找到的靜音當切點，和剪靜音的模型
        # 一樣交給 Silero，這類音檔的切法不變（#95）。測試環境沒有 Silero，所以切在正中間，不在
        # 5.75 秒的靜音。單次只能處理 16 秒
        fake.model_capabilities = replace(
            fake.model_capabilities, remove_silence=False, single_pass_seconds=16.0)
        fake.script = [[(0.5, 2.0, 0, "前半。")], [(1.25, 2.75, 1, "後半。")]]
        messages = transcribe(api, "uid-keeps-silences-mostly-speech", voiced=EARLY_GAP)

        assert codes(messages)[-1] == TaskStatus.COMPLETED
        assert fake.durations == pytest.approx([10.75, 10.75], abs=0.01)
        assert flat_times(stored_segments(api, messages[-1]["task_uuid"])) == pytest.approx(
            [0.5, 2.0, 12.0, 13.5])

    @JUNCTIONS
    def test_times_on_a_junction_stay_out_of_the_removed_silence(self, api, fake, junction):
        # 一句在有聲段的交界說完，下一句在交界開始（見 LONG_GAP）。結束在交界的算前一段，在 6.3 秒
        # 結束；開始在交界的算後一段，在 13.7 秒開始：都不含中間剪掉的靜音（#109 的審查）。
        # 零長度的詞落在交界時，也不會結束得比開始早
        fake.script = [[(1.0, junction, 0, "前半。", [("前", 1.0, 3.0), ("半", 3.0, junction)]),
                        (junction, 8.0, 1, "後半。",
                         [("後", junction, junction), ("半", junction, 8.0)])]]
        task_uuid = transcribe(api, "uid-junction", voiced=LONG_GAP)[-1]["task_uuid"]

        first, second = stored_segments(api, task_uuid)
        assert flat_times([first, second]) == pytest.approx([1.0, 6.3, 13.7, 15.4])
        assert flat_times(first["words"] + second["words"]) == pytest.approx(
            [1.0, 3.0, 3.0, 6.3, 13.7, 13.7, 13.7, 15.4])
        assert download(api, task_uuid, "lrc") == "[00:01.00][S0] 前半。\n[00:13.70][S1] 後半。"
        srt = download(api, task_uuid, "srt")
        assert "00:00:01,000 --> 00:00:06,300\n[S0] 前半。" in srt
        assert "--> 00:00:15,400\n[S1] 後半。" in srt

    def test_times_just_outside_the_tolerance_are_restored_as_they_are(self, api, fake):
        # 離交界 1e-5 秒，超過容許的 1e-6 秒，就不算落在交界上：交界前 1e-5 秒開始的一句屬於前一段，
        # 交界後 1e-5 秒結束的一句屬於後一段
        fake.script = [[(1.0, 6.3 + 1e-5, 0, "前半。"), (6.3 - 1e-5, 8.0, 1, "後半。")]]
        task_uuid = transcribe(api, "uid-near-junction", voiced=LONG_GAP)[-1]["task_uuid"]

        assert flat_times(stored_segments(api, task_uuid)) == pytest.approx(
            [1.0, 13.7 + 1e-5, 6.3 - 1e-5, 15.4], abs=1e-9)

    @JUNCTIONS
    def test_sentence_ending_on_a_junction_is_not_split_at_its_reading_point(
            self, api, fake, junction):
        # 一句話在交界剛好說完：從 1.0 秒到 6.3 秒，不到 12 秒，不在讀點斷行。結束算到剪掉的
        # 靜音之後（13.7 秒）的話，這句會被當成超過 12 秒，在讀點多斷一行
        fake.script = [[(1.0, junction, 0, "今日は、ありがとう。",
                         [("今", 1.0, 1.2), ("日", 1.2, 1.4), ("は", 1.4, 1.8),
                          ("ありがとう", 5.3, junction)])]]
        task_uuid = transcribe(api, "uid-junction-end", voiced=LONG_GAP)[-1]["task_uuid"]

        assert download(api, task_uuid, "lrc") == "[00:01.00][S0] 今日は、ありがとう。"
        assert download(api, task_uuid, "srt") == (
            "1\n00:00:01,000 --> 00:00:06,300\n[S0] 今日は、ありがとう。\n")

    def test_kept_artifacts_record_what_was_sent(self, api, fake, settings, monkeypatch, data_dir):
        # 開了 VAD_KEEP_ARTIFACTS：送進模型的語音視圖與找到的有聲段存進 vad_artifacts/，給本機檢查
        # 切得對不對
        monkeypatch.setattr(settings, "vad_keep_artifacts", True)
        fake.script = list(SCRIPT)
        transcribe(api, "uid-artifacts")

        [kept] = (data_dir / "vad_artifacts").iterdir()
        assert sf.info(str(kept / "speech_only.wav")).duration == pytest.approx(7.2, abs=0.01)
        voiced = json.loads((kept / "segments.json").read_text(encoding="utf-8"))
        assert flat_times(voiced) == pytest.approx([0.0, 2.3, 4.7, 7.3, 9.7, 12.0])
        [operation] = json.loads((kept / "manifest.json").read_text(encoding="utf-8"))["operations"]
        assert operation["used_for_transcription"] is True
        assert operation["speech_duration_seconds"] == pytest.approx(7.2)
        assert operation["total_duration_seconds"] == pytest.approx(12.0)

    def test_artifacts_that_cannot_be_saved_do_not_fail_the_task(
            self, api, fake, settings, monkeypatch, data_dir):
        # 開了 VAD_KEEP_ARTIFACTS，產物卻存不進去（資料夾的位置被一個檔案佔住）：產物只是給本機
        # 檢查的，任務照樣完成，只剩語音的音檔照樣從暫存區清掉
        monkeypatch.setattr(settings, "vad_keep_artifacts", True)
        (data_dir / "vad_artifacts").write_bytes(b"")
        fake.script = list(SCRIPT)
        messages = transcribe(api, "uid-artifacts-blocked")

        assert codes(messages)[-1] == TaskStatus.COMPLETED
        assert leftovers(data_dir) == []


class TestVadTestEndpoint:
    """轉錄頁的去靜音與切點預覽：只跑去靜音與 Silero 的切點，不轉錄。

    是開發者工具（#13 Q6）：設定 ``DEV_TOOLS`` 沒開時，轉錄頁看不到，端點也不跑。
    """

    def test_is_off_unless_dev_tools_are_on(self, api, data_dir):
        # 一般使用者看不到，也不會在資料夾留下預覽產生的音檔
        filename = upload(api)

        assert api.get("/api/v1/vad/enabled").json() == {"enabled": False}
        response = api.post("/api/v1/vad/test", json={"filename": filename})

        assert response.status_code == 404
        assert "DEV_TOOLS" in response.json()["detail"]
        assert not (data_dir / "vad_artifacts").exists()

    @pytest.mark.parametrize("voiced, cut", [(VOICED, True), (MOSTLY_VOICED, False)],
                             ids=["mostly-silent", "mostly-speech"])
    def test_reports_silence_removal_without_silero(
            self, api, settings, monkeypatch, voiced, cut):
        monkeypatch.setattr(settings, "dev_tools", True)
        assert api.get("/api/v1/vad/enabled").json() == {"enabled": True}
        # 測試環境沒有 Silero：去靜音照樣回報找到的有聲段，會不會剪和轉錄時用同一個門檻；
        # 只有要 Silero 的切點那一段失敗
        filename = upload(api, voiced=voiced)
        response = api.post("/api/v1/vad/test",
                            json={"filename": filename, "original_filename": "voice.wav"})

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["success"] is True
        extraction = body["speech_extraction"]
        assert extraction["would_use_speech_only"] is cut
        assert extraction["segment_count"] == len(voiced)
        assert body["split"]["success"] is False


# ─── 分段轉錄改讀模型能力 ───────────────────────────────────────────────────

EDGE_GAP = [(0.0, 0.5), (5.0, 12.0)]
"""有聲 0–0.5 秒、靜音 0.5–5 秒、有聲 5–12 秒。去靜音之後的語音視圖 8.1 秒，唯一的交界在 0.8 秒，
離開頭不到 1 秒。"""


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
        # 片段 key 和以前一樣：前段加 a、後段加 b，重新轉錄時對得上使用者的校正（ADR-0007）
        assert [s["seg_key"] for s in segments] == ["a.0000", "b.0000", "b.0001"]

    def test_without_any_silence_the_audio_is_split_in_the_middle(self, api, fake):
        # 幾乎全是語音的音檔（見 MOSTLY_VOICED）不去靜音，語音視圖沒有靜音邊界，測試環境也沒有
        # Silero。單次只能處理 15 秒：21.5 秒的原音檔切在正中間，不整段送出
        fake.model_capabilities = replace(fake.model_capabilities, single_pass_seconds=15.0)
        fake.script = [[(0.5, 2.0, 0, "前半。")], [(1.25, 2.75, 1, "後半。")]]
        messages = transcribe(api, "uid-middle", voiced=MOSTLY_VOICED)

        assert codes(messages)[-1] == TaskStatus.COMPLETED
        assert fake.durations == pytest.approx([10.75, 10.75], abs=0.01)
        segments = stored_segments(api, messages[-1]["task_uuid"])
        assert flat_times(segments) == pytest.approx([0.5, 2.0, 12.0, 13.5])
        assert [s["seg_key"] for s in segments] == ["a.0000", "b.0000"]

    @pytest.mark.parametrize("second, recorded, cost", [
        ("flex", "flex", 0.30),
        ("standard", "standard", 0.60),
    ], ids=["every-chunk-on-flex", "one-chunk-fell-back"])
    def test_flex_discount_only_when_every_chunk_ran_on_flex(
            self, api, fake, settings, monkeypatch, second, recorded, cost):
        # 單次只能處理 5 秒，切成兩段。兩段都以 Flex 完成才算 Flex、打五折；有一段退回標準就算標準
        # （兩次各 0.30 美元，價目見 TestSingleFileTask 的計價測試）
        monkeypatch.setattr(settings, "flex_cost_discount", 0.5)
        fake.model_capabilities = replace(
            fake.model_capabilities, single_pass_seconds=5.0, pricing="per_token")
        fake.usage = (200_000, 40_000)
        fake.service_tier = "flex"
        fake.script = [[(0.2, 0.8, 0, "一つ目。")], ServedAs(second, [(0.2, 0.8, 1, "二つ目。")])]
        done = transcribe(api, "uid-flex-chunks")[-1]

        assert done["result"]["cost"] == pytest.approx(cost)
        record = api.get(f"/api/v1/history/{done['task_uuid']}").json()
        assert record["service_tier_used"] == recorded
        assert record["cost"] == pytest.approx(cost)

    @pytest.mark.parametrize("split_retry, script, end", [
        (False, [[(0.2, 0.8, 0, "一つ目。")], [(0.2, 0.8, 1, "二つ目。")]], TaskStatus.COMPLETED),
        (False, [[(0.2, 0.8, 0, "一つ目。")], Fail("模型壞掉了")], TaskStatus.FAILED),
        (True, [Fail("回應被阻擋"), [(0.2, 0.8, 0, "一つ目。")], [(0.2, 0.8, 1, "二つ目。")],
                [(0.2, 0.8, 0, "三つ目。")]], TaskStatus.COMPLETED),
    ], ids=["completed", "failed", "split-retried"])
    def test_chunks_leave_no_temp_files(
            self, api, fake, settings, monkeypatch, data_dir, split_retry, script, end):
        # 切出的段、為了 Silero 轉成的 wav 與語音視圖的暫存檔，任務結束後都不留在電腦上
        fake.model_capabilities = replace(
            fake.model_capabilities, single_pass_seconds=5.0, split_retry_on_failure=split_retry)
        monkeypatch.setattr(settings, "transcription_max_duration_seconds", 2)
        fake.script = script
        messages = transcribe(api, "uid-chunk-files")

        assert codes(messages)[-1] == end
        assert leftovers(data_dir) == []

    def test_a_silence_too_close_to_an_edge_is_not_a_split_point(self, api, fake):
        # 唯一的靜音交界離開頭不到 1 秒（見 EDGE_GAP）：切在那裡的話前一段幾乎是空的，不當切點。
        # 測試環境也沒有 Silero，所以切在正中間
        fake.model_capabilities = replace(fake.model_capabilities, single_pass_seconds=5.0)
        fake.script = [[(0.2, 0.4, 0, "一つ目。")], [(0.5, 1.5, 1, "二つ目。")]]
        messages = transcribe(api, "uid-edge-silence", voiced=EDGE_GAP)

        assert codes(messages)[-1] == TaskStatus.COMPLETED
        assert fake.durations == pytest.approx([4.05, 4.05], abs=0.01)

    def test_word_timings_follow_their_chunk(self, api, fake):
        # 逐字時間和片段一起平移、還原回原音檔：第二段是語音視圖的 4.9–7.2 秒，即第三個有聲段
        # 9.7–12 秒（見 TestSplitRetryAfterFailure）
        fake.model_capabilities = replace(fake.model_capabilities, single_pass_seconds=5.0)
        fake.script = [[(0.2, 0.8, 0, "一つ目。")],
                       [(0.2, 1.2, 1, "二つ目。", [("二つ", 0.2, 0.6), ("目。", 0.6, 1.2)])]]
        messages = transcribe(api, "uid-chunk-words")

        assert codes(messages)[-1] == TaskStatus.COMPLETED
        second = stored_segments(api, messages[-1]["task_uuid"])[1]
        assert flat_times([second]) == pytest.approx([9.9, 10.9])
        assert flat_times(second["words"]) == pytest.approx([9.9, 10.3, 10.3, 10.9])

    def test_without_silence_removal_provider_times_are_kept(self, api, fake):
        fake.model_capabilities = replace(fake.model_capabilities, remove_silence=False)
        fake.script = list(SCRIPT)
        messages = transcribe(api, "uid-no-vad")

        segments = stored_segments(api, messages[-1]["task_uuid"])
        assert [s["start"] for s in segments] == pytest.approx([line[0] for line in SCRIPT[0]])


class TestSplitRetryAfterFailure:
    """失敗後切段重試（#112）。去靜音之後 7.2 秒的語音視圖（見 VOICED）由三個有聲段接成，交界在 2.3 與
    4.9 秒；單次只能處理 5 秒，在 4.9 秒切成 4.9 秒與 2.3 秒兩段。失敗的段不短於 2 秒才切段重試。"""

    @pytest.fixture(autouse=True)
    def _two_chunks(self, fake, settings, monkeypatch):
        fake.model_capabilities = replace(
            fake.model_capabilities, single_pass_seconds=5.0, split_retry_on_failure=True)
        monkeypatch.setattr(settings, "transcription_max_duration_seconds", 2)

    def test_only_the_failed_chunk_is_split_and_retried(self, api, fake):
        # 第一段失敗：只把它切成兩段重試，切點照樣先找靜音，切在它之內的交界 2.3 秒；第二段沒有重送
        fake.script = [Fail("回應被阻擋"), [(0.2, 0.8, 0, "一つ目。")], [(0.2, 0.9, 1, "二つ目。")],
                       [(0.5, 1.5, 0, "三つ目。")]]
        messages = transcribe(api, "uid-split-retry")

        assert codes(messages)[-1] == TaskStatus.COMPLETED
        assert fake.durations == pytest.approx([4.9, 2.3, 2.6, 2.3], abs=0.01)
        segments = stored_segments(api, messages[-1]["task_uuid"])
        assert [s["seg_key"] for s in segments] == ["a.s0.0000", "a.s1.0000", "b.0000"]
        # 第二句在 a.s1 的 0.2 秒，是語音視圖的 2.5 秒，還原回原音檔是第二個有聲段的 4.9 秒；
        # 第三句在 b 的 0.5 秒，是語音視圖的 5.4 秒，是第三個有聲段的 10.2 秒
        assert flat_times(segments) == pytest.approx([0.2, 0.8, 4.9, 5.6, 10.2, 11.2])

    def test_chunk_without_any_silence_is_split_in_the_middle(self, api, fake):
        # 第二段（2.3 秒）之內沒有靜音邊界，測試環境也沒有 Silero：切段重試照樣切得開，切在正中間
        fake.script = [[(0.2, 0.8, 0, "一つ目。")], Fail("回應被阻擋"), [(0.2, 0.8, 1, "二つ目。")],
                       [(0.2, 0.8, 0, "三つ目。")]]
        messages = transcribe(api, "uid-split-retry-middle")

        assert codes(messages)[-1] == TaskStatus.COMPLETED
        assert fake.durations == pytest.approx([4.9, 2.3, 1.15, 1.15], abs=0.01)
        segments = stored_segments(api, messages[-1]["task_uuid"])
        assert [s["seg_key"] for s in segments] == ["a.0000", "b.s0.0000", "b.s1.0000"]
        assert flat_times(segments) == pytest.approx([0.2, 0.8, 9.9, 10.5, 11.05, 11.65])

    def test_the_replaced_attempt_is_billed_too(self, api, fake):
        # 失敗的那次照樣收費（例如 Gemini 的回應被阻擋）：四次呼叫的用量都記下，不只記成功的三次
        # （價目見 TestSingleFileTask 的計價測試，一次 0.30 美元）
        fake.model_capabilities = replace(fake.model_capabilities, pricing="per_token")
        fake.usage = (200_000, 40_000)
        fake.script = [Fail("回應被阻擋"), [(0.2, 0.8, 0, "一つ目。")], [(0.2, 0.9, 1, "二つ目。")],
                       [(0.5, 1.5, 0, "三つ目。")]]
        done = transcribe(api, "uid-split-retry-billed")[-1]

        assert done["result"]["tokens_used"] == 960_000
        assert done["result"]["cost"] == pytest.approx(1.20)
        record = api.get(f"/api/v1/history/{done['task_uuid']}").json()
        assert record["total_tokens"] == 960_000
        assert record["cost"] == pytest.approx(1.20)

    @pytest.mark.parametrize("split_retry, minimum", [(False, 2), (True, 3)],
                             ids=["model-without-split-retry", "chunk-under-the-minimum"])
    def test_failure_names_the_chunk_when_it_cannot_be_retried(
            self, api, fake, settings, monkeypatch, split_retry, minimum):
        # 模型能力不允許切段重試，或第二段（2.3 秒）短於下限：直接回報失敗，寫明是第幾段、在原音檔
        # 的哪裡（語音視圖的 4.9–7.2 秒是第三個有聲段 9.7–12 秒）
        fake.model_capabilities = replace(
            fake.model_capabilities, split_retry_on_failure=split_retry)
        monkeypatch.setattr(settings, "transcription_max_duration_seconds", minimum)
        fake.script = [[(0.2, 0.8, 0, "一つ目。")], Fail("模型壞掉了")]
        messages = transcribe(api, "uid-not-retried")

        assert codes(messages)[-1] == TaskStatus.FAILED
        assert len(fake.calls) == 2
        reason = "分段轉錄的第 2 段（00:09–00:12）：模型壞掉了"
        assert reason in messages[-1]["status_text"]
        assert reason in api.get(f"/api/v1/history/{messages[-1]['task_uuid']}").json()["error_message"]


# ─── 輸出格式從片段產生 ─────────────────────────────────────────────────────

class TestOutputFormatsFromSegments:
    @pytest.fixture
    def completed(self, api, fake):
        """片段帶逐字時間的任務；不去靜音，時間軸就是送進供應商的時間。"""
        fake.model_capabilities = replace(fake.model_capabilities, remove_silence=False)
        # 一個片段兩句，逐字時間讓下載在句尾斷行
        fake.script = [[(0.2, 2.6, 0, "おはよう。こんにちは。",
                         [("おはよう", 0.24, 0.9), ("こんにちは", 1.5, 2.56)])]]
        messages = transcribe(api, "uid-words")
        assert codes(messages)[-1] == TaskStatus.COMPLETED
        return messages[-1]

    @pytest.mark.parametrize("fmt, expected", [
        ("lrc", "[00:00.24][S0] おはよう。\n[00:01.50][S0] こんにちは。"),
        # SRT／VTT 的每一行在它最後一個詞的結束時結束（#96），不是下一行的開始或片段的結束；
        # 「おはよう」只講 0.66 秒，至少顯示 0.8 秒（ADR-0008）
        ("srt", "1\n00:00:00,240 --> 00:00:01,040\n[S0] おはよう。\n\n"
                "2\n00:00:01,500 --> 00:00:02,560\n[S0] こんにちは。\n"),
        ("vtt", "WEBVTT\n\n00:00:00.240 --> 00:00:01.040\n[S0] おはよう。\n\n"
                "00:00:01.500 --> 00:00:02.560\n[S0] こんにちは。\n"),
        ("txt", "[S0] おはよう。\n[S0] こんにちは。"),
    ])
    def test_downloads_break_and_end_lines_using_word_timings(
            self, api, completed, fmt, expected):
        assert download(api, completed["task_uuid"], fmt) == expected

    @pytest.mark.parametrize("fmt", ["lrc", "srt", "vtt", "txt"])
    def test_completion_broadcast_matches_the_download(self, api, completed, fmt):
        broadcast = completed["result"]["transcripts"][fmt]
        assert broadcast == download(api, completed["task_uuid"], fmt)

    def test_frozen_original_transcription_is_the_lrc_download(self, api, completed, test_engine):
        # 凍結的原始轉錄副本和下載的 LRC 一樣，由輸出格式模組從轉錄結果產生
        task_uuid = completed["task_uuid"]
        assert frozen_original(test_engine, task_uuid) == download(api, task_uuid, "lrc")

    @pytest.fixture
    def across_cut_silence(self, api, fake):
        """一句話跨過被剪掉的靜音的任務。

        音檔見 LONG_GAP。送進供應商的「今日は、ありがとう。」從 1.0 到 8.0 秒，只有 7 秒；
        還原回原音檔是 1.0 到 15.4 秒。
        """
        fake.script = [[(0.8, 8.2, 0, "今日は、ありがとう。",
                         [("今", 1.0, 1.2), ("日", 1.2, 1.4), ("は", 1.4, 1.8),
                          ("ありがとう", 7.0, 8.0)])]]
        messages = transcribe(api, "uid-gap", voiced=LONG_GAP)
        assert codes(messages)[-1] == TaskStatus.COMPLETED
        return messages[-1]

    def test_silence_removed_inside_a_sentence_counts_toward_12_seconds(
            self, api, across_cut_silence):
        # 還原回原音檔超過 12 秒，在讀點斷開，第二行落在剪掉的靜音之後
        assert download(api, across_cut_silence["task_uuid"], "lrc") == (
            "[00:01.00][S0] 今日は、\n[00:14.40][S0] ありがとう。")

    def test_subtitle_end_times_are_restored_to_the_original_timeline(
            self, api, across_cut_silence):
        # 「は」在 1.8 秒結束；「ありがとう」在語音視圖的 8.0 秒結束，還原回原音檔是 15.4 秒。
        # 結束時間和開始時間一樣取到 0.01 秒，不受還原時的浮點誤差影響
        assert download(api, across_cut_silence["task_uuid"], "srt") == (
            "1\n00:00:01,000 --> 00:00:01,800\n[S0] 今日は、\n\n"
            "2\n00:00:14,400 --> 00:00:15,400\n[S0] ありがとう。\n")

    @pytest.mark.parametrize("fmt, expected", [
        ("srt", "1\n00:00:00,500 --> 00:00:03,500\n[S1] 你拉不拉货。\n\n"
                "2\n00:00:03,000 --> 00:00:03,800\n[S0] 对\n\n"
                "3\n00:00:04,000 --> 00:00:06,500\n[S1] 但是。\n"),
        ("vtt", "WEBVTT\n\n00:00:00.500 --> 00:00:03.500\n[S1] 你拉不拉货。\n\n"
                "00:00:03.000 --> 00:00:03.800\n[S0] 对\n\n"
                "00:00:04.000 --> 00:00:06.500\n[S1] 但是。\n"),
    ])
    def test_interjection_overlaps_and_subtitles_follow_start_times(
            self, api, fake, fmt, expected):
        # 像 AISHELL-4 會議錄音 4:07.6 的插話（ADR-0008）：S1 講到 3.5 秒，S0 在 3.0 秒插一句
        # 「对」，兩行同時顯示；「对」的詞是零長度，顯示最短的 0.8 秒。字幕依開始時間排序，
        # S1 的片段斷成的第二行排在「对」後面
        fake.model_capabilities = replace(fake.model_capabilities, remove_silence=False)
        fake.script = [[(0.5, 6.5, 1, "你拉不拉货。但是。",
                         [("你", 0.5, 1.0), ("拉", 1.0, 1.5), ("不", 1.5, 2.0), ("拉", 2.0, 2.5),
                          ("货", 2.5, 3.5), ("但", 4.0, 4.5), ("是", 4.5, 6.5)]),
                        (3.0, 3.25, 0, "对", [("对", 3.0, 3.0)])]]
        messages = transcribe(api, "uid-interjection")

        assert codes(messages)[-1] == TaskStatus.COMPLETED
        assert download(api, messages[-1]["task_uuid"], fmt) == expected

    @pytest.mark.parametrize("fmt, expected", [
        ("srt", "1\n00:00:00,250 --> 00:00:02,500\n[S0] おはよう。\n\n"
                "2\n00:00:02,500 --> 00:00:07,500\n[S1] こんにちは。\n"),
        ("vtt", "WEBVTT\n\n00:00:00.250 --> 00:00:02.500\n[S0] おはよう。\n\n"
                "00:00:02.500 --> 00:00:07.500\n[S1] こんにちは。\n"),
    ])
    def test_segments_without_an_end_keep_the_old_subtitle_end_times(
            self, api, fake, fmt, expected):
        # 供應商只給開始時間：照以前，下一行的開始，最後一行加 5 秒
        fake.model_capabilities = replace(fake.model_capabilities, remove_silence=False)
        fake.script = [[(0.25, None, 0, "おはよう。"), (2.5, None, 1, "こんにちは。")]]
        messages = transcribe(api, "uid-no-end")

        assert codes(messages)[-1] == TaskStatus.COMPLETED
        assert download(api, messages[-1]["task_uuid"], fmt) == expected

    def test_segment_without_text_and_word_without_a_time(self, api, fake):
        # 沒有文字的片段不產生行；有詞缺時間的片段不知道怎麼對到句子，整段一行
        fake.model_capabilities = replace(fake.model_capabilities, remove_silence=False)
        fake.script = [[(0.2, 0.9, 0, None),
                        (1.0, 2.6, 1, "おはよう。こんにちは。",
                         [("おはよう", 1.04, 1.6), ("こんにちは", None, 2.56)])]]
        messages = transcribe(api, "uid-untimed")

        assert codes(messages)[-1] == TaskStatus.COMPLETED
        assert download(api, messages[-1]["task_uuid"], "lrc") == (
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

    @pytest.mark.parametrize("submit_args", [
        {"provider": "fake", "model": "gemini-2.5-flash"},
        {"provider": "local", "model": "moss-align", "prompt": "語助詞也要寫出來"},
    ], ids=["model-mismatch", "unsupported-input"])
    def test_rejected_task_leaves_no_upload_behind(self, api, data_dir, submit_args):
        # 被拒絕的任務不會執行，也沒有任務紀錄可以掛保留音檔：上傳檔不留在電腦上
        task_rejection(api, "uid-reject-upload", **submit_args)

        assert leftovers(data_dir) == []

    def test_rejected_batch_leaves_no_upload_behind(self, api, data_dir):
        files = [upload(api, "a.wav"), upload(api, "b.wav")]
        with api.websocket_connect("/api/v1/batch/ws/batch-reject-uploads") as ws:
            ws.send_json({
                "files": [{"filename": f, "original_filename": f, "file_uid": f} for f in files],
                "provider": "local",
                "model": "gemini-2.5-flash",
                "source_lang": "ja",
            })
            messages = [receive(ws) for _ in files]

        assert {m["status_code"] for m in messages} == {TaskStatus.FAILED}
        assert leftovers(data_dir) == []


# ─── 送出時上傳檔已經不在（#153） ────────────────────────────────────────────

class TestUploadGoneBeforeSubmit:
    def test_single_file_fails_instead_of_staying_in_progress(self, api, fake):
        # 同一個上傳檔已經送出過（例如在另一個分頁）：那個任務收尾時，上傳檔已經搬進保留區或刪掉
        fake.script = list(SCRIPT)
        filename = upload(api)
        with api.websocket_connect("/api/v1/ws/uid-sent-elsewhere") as ws:
            submit(ws, filename)
            assert receive_until_terminal(ws)[-1]["status_code"] == TaskStatus.COMPLETED

        reason = task_rejection(api, "uid-upload-gone", filename=filename)

        assert "找不到上傳的檔案" in reason
        assert fake.opened == 1


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


# ─── 重新轉錄時舊連線還沒收尾（#203） ───────────────────────────────────────

class TestReTranscriptionBeforeTheOldConnectionEnds:
    """第一次轉錄的連線，伺服器還沒發現它已經斷了（例如電腦休眠、換網路），重新轉錄的新連線就連上來：
    伺服器先關掉舊連線、登記新連線，舊連線的處理流程之後才收尾。收尾只能動舊連線自己，新任務的
    狀態訊息才送得到畫面，檔案卡才不會停在處理中。"""

    PATH = "/api/v1/ws/uid-retranscribe"

    @pytest.fixture(autouse=True)
    def _script(self, fake):
        fake.script = list(SCRIPT) * 2

    def test_old_connection_disconnecting_afterwards_keeps_the_new_one(self, api):
        with ExitStack() as old_connection:
            old = old_connection.enter_context(api.websocket_connect(self.PATH))
            submit(old, upload(api))
            assert receive_until_terminal(old)[-1]["status_code"] == TaskStatus.COMPLETED

            with api.websocket_connect(self.PATH) as ws:
                old_connection.close()  # 舊連線的處理流程這時才收到斷線
                submit(ws, upload(api))
                assert receive_until_terminal(ws)[-1]["status_code"] == TaskStatus.COMPLETED

    def test_old_connection_failing_afterwards_keeps_the_new_one(self, api):
        with api.websocket_connect(self.PATH) as old:
            submit(old, upload(api))
            assert receive_until_terminal(old)[-1]["status_code"] == TaskStatus.COMPLETED

            with api.websocket_connect(self.PATH) as ws:
                # 舊連線已經被伺服器關掉，它的處理流程接著又收到訊息：在關掉的連線上收訊息會丟例外，
                # 走端點發生例外時的收尾
                ping(old)
                submit(ws, upload(api))
                assert receive_until_terminal(ws)[-1]["status_code"] == TaskStatus.COMPLETED


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
    """GET /providers 回的所有欄位名稱：供應商（含上傳告知）、模型與模型能力。"""
    fields = set()
    for entry in api.get("/api/v1/providers").json():
        fields |= entry.keys()
        if entry["upload_notice"]:
            fields |= entry["upload_notice"].keys()
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
            "supports_flex": False,
            "pricing": "free",
            "remove_silence": True,
        }

    def test_local_models_take_no_prompt_gemini_models_do(self, api):
        listed = listed_capabilities(api)
        local = {model: c for (provider, model), c in listed.items() if provider == "local"}
        gemini = {model: c for (provider, model), c in listed.items() if provider == "google"}

        assert set(local) == {"moss-align", "moss-qwen3-asr", "vibevoice-qwen3-asr"}
        assert {"gemini-3.5-flash", "gemini-2.5-flash"} <= set(gemini)
        assert not any(c["accepts_prompt"] for c in local.values())
        assert all(c["accepts_prompt"] for c in gemini.values())

    def test_local_models_keep_silences_gemini_models_cut_them(self, api):
        # 剪掉靜音之後 MOSS 的說話者分離變差（#95）：本機的模型送原音檔，只拿靜音的位置當切點
        listed = listed_capabilities(api)
        models = {(provider, model): c["remove_silence"] for (provider, model), c in listed.items()
                  if provider in ("local", "google")}

        assert models
        assert models == {(provider, model): provider == "google" for provider, model in models}

    def test_no_model_takes_user_text_until_it_reaches_the_task(self, api):
        # 使用者文稿還沒交給任務（#66），#13 Q4 定案先隱藏入口：模型能力照實說不吃，轉錄頁就不提供
        # 附加的按鈕。修好 #66 時把 Gemini 的改回來
        listed = listed_capabilities(api)
        models = [c for (provider, _), c in listed.items() if provider in ("local", "google")]

        assert models
        assert not any(c["accepts_user_text"] for c in models)

    def test_only_gemini_models_take_flex_and_batch(self, api):
        # 轉錄頁依這兩項停用本機選不了的處理模式（#162）
        listed = listed_capabilities(api)

        for (provider, model), c in listed.items():
            if provider in ("local", "google"):
                expected = provider == "google"
                assert (c["supports_flex"], c["supports_batch"]) == (expected, expected), model

    def test_says_which_providers_need_the_users_api_key(self, api):
        # 轉錄頁送出前依這一項確認設定了金鑰，不再寫死哪個供應商不用（#97）
        listed = listed_providers(api)

        assert listed["google"]["requires_api_key"] is True
        assert listed["local"]["requires_api_key"] is False

    def test_tells_where_the_audio_goes_and_links_the_terms(self, api):
        # 選 Gemini 時，設定頁與轉錄頁照這一項告訴使用者音檔會上傳、Google 怎麼使用，
        # 並連到條款原文（#231 Q6）；本機不送出音檔，沒有告知
        listed = listed_providers(api)

        notice = listed["google"]["upload_notice"]
        assert notice["terms_url"] == "https://ai.google.dev/gemini-api/terms"
        assert "上傳到 Google" in notice["text"]
        assert "免費層" in notice["text"]
        assert listed["local"]["upload_notice"] is None

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

        assert {"accepts_prompt", "accepts_user_text", "supports_batch", "supports_flex",
                "remove_silence", "requires_api_key", "upload_notice", "terms_url"} <= read
        assert read <= listed_fields(api)


# ─── 模型不吃的輸入（#108） ─────────────────────────────────────────────────

class TestInputsTheModelDoesNotTake:
    @pytest.mark.parametrize("fields, reported", [
        ({"prompt": "語助詞也要寫出來"}, "提示詞"),
        ({"user_supplied_text": "おはよう。こんにちは。"}, "使用者文稿"),
    ], ids=["prompt", "user-text"])
    def test_local_model_rejects_them_with_clear_error(self, api, fields, reported):
        reason = task_rejection(
            api, "uid-local-input", provider="local", model="moss-align", **fields)

        assert "moss-align" in reason
        assert reported in reason

    def test_gemini_model_rejects_user_text_until_it_reaches_the_task(self, api):
        # 以前 Gemini 收下使用者文稿，任務卻沒拿到（#66）：現在送出時就明確拒絕
        reason = task_rejection(api, "uid-gemini-user-text", provider="google",
                                model="gemini-3.5-flash", user_supplied_text="おはよう。")

        assert "gemini-3.5-flash" in reason
        assert "使用者文稿" in reason

    def test_model_that_takes_them_runs_as_usual(self, api, fake):
        fake.script = list(SCRIPT)

        messages = transcribe(api, "uid-with-inputs",
                              prompt="語助詞也要寫出來", user_supplied_text="おはよう。")

        assert codes(messages)[-1] == TaskStatus.COMPLETED
        assert len(fake.calls) == 1

    @pytest.mark.parametrize("fields", [
        {"prompt": None, "user_supplied_text": None},
        {"prompt": "", "user_supplied_text": ""},
        {"prompt": " \n", "user_supplied_text": "\t"},
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


# ─── 模型不支援的處理模式（#162） ─────────────────────────────────────────────

class TestProcessingModeTheModelDoesNotSupport:
    def test_flex_on_model_without_flex_is_rejected_with_clear_error(self, api, fake):
        # 送給本機的 service_tier 以前會被默默忽略
        fake.model_capabilities = replace(fake.model_capabilities, supports_flex=False)

        reason = task_rejection(api, "uid-flex-unsupported", service_tier="flex")

        assert FAKE_MODEL in reason
        assert "不支援 Flex" in reason
        assert fake.opened == 0

    def test_local_model_rejects_flex(self, api):
        reason = task_rejection(
            api, "uid-local-flex", provider="local", model="moss-align", service_tier="flex")

        assert "moss-align" in reason
        assert "不支援 Flex" in reason

    def test_flex_on_model_with_flex_runs(self, api, fake):
        fake.model_capabilities = replace(fake.model_capabilities, supports_flex=True)
        fake.script = list(SCRIPT)

        messages = transcribe(api, "uid-flex-supported", service_tier="flex")

        assert codes(messages)[-1] == TaskStatus.COMPLETED

    @pytest.mark.parametrize("service_tier", [None, "standard"])
    def test_standard_runs_on_model_without_flex(self, api, fake, service_tier):
        fake.model_capabilities = replace(fake.model_capabilities, supports_flex=False)
        fake.script = list(SCRIPT)

        messages = transcribe(api, "uid-standard", service_tier=service_tier)

        assert codes(messages)[-1] == TaskStatus.COMPLETED


# ─── 提示詞：補充說明接在提示詞範本後面（#144） ──────────────────────────────

class TestPromptIsTemplatePlusSupplement:
    """請求帶的提示詞是補充說明，空一行接在提示詞範本後面送出；範本是設定頁為這個供應商存的，
    沒存過就是系統內建的。批次照同一個規則，見 test_batch.py。"""

    @pytest.fixture(autouse=True)
    def _script(self, fake):
        fake.script = list(SCRIPT)

    def test_supplement_is_sent_after_the_built_in_template(self, api, fake):
        transcribe(api, "uid-supplement-built-in", source_lang="ja-JP", prompt="說話者是兩位主持人")

        # 系統內建範本裡要求 LRC 與時間戳的指示照樣送出，補充說明接在最後
        assert fake.prompts == [build_prompt(source_lang="ja-JP") + "\n\n說話者是兩位主持人"]

    def test_supplement_is_sent_after_the_template_saved_in_settings(
            self, api, fake, saved_prompt_template):
        saved_prompt_template("fake", "請把{source_lang}音檔轉成 LRC，時間戳寫成 [mm:ss.xxx]。")

        transcribe(api, "uid-supplement-saved", source_lang="ja-JP",
                   prompt='人名照寫：佐藤，每一行寫成 {"speaker": "S0"}')

        # 範本代入變數；補充說明照寫的送出，大括號不動
        assert fake.prompts == ["請把日文音檔轉成 LRC，時間戳寫成 [mm:ss.xxx]。\n\n"
                                '人名照寫：佐藤，每一行寫成 {"speaker": "S0"}']

    @pytest.mark.parametrize("prompt", [None, "", " \n"], ids=["null", "empty", "blank"])
    def test_without_a_supplement_the_saved_template_is_sent_alone(
            self, api, fake, saved_prompt_template, prompt):
        saved_prompt_template("fake", "請把{source_lang}音檔轉成 LRC。")

        transcribe(api, "uid-template-alone", source_lang="ja-JP", prompt=prompt)

        assert fake.prompts == ["請把日文音檔轉成 LRC。"]


# ─── 取消 ────────────────────────────────────────────────────────────────────

# 前端只在這裡讀取消端點的回應，並依沒有取消的原因顯示不同的提示（#161）
FRONTEND_CANCEL_RESPONSE_READER = REPO_ROOT / "frontend" / "src" / "utils" / "cancelOutcome.js"


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

        # 能不能強制終止隨任務登記（派送時照模型能力）：還沒有任務紀錄的佇列中任務也照登記的送，
        # 剛開始執行、紀錄還沒寫進去的任務才停得下來
        queued_revoke, running_revoke = run_mode_spy.revoked
        assert queued_revoke[1] is terminate
        assert running_revoke[1] is terminate

        assert len(fake.calls) == 1  # 佇列中的那個從沒開始
        running_log = api.get(f"/api/v1/history/{task_end['task_uuid']}").json()
        assert running_log["status"] == TaskStatus.CANCELLED
        assert stored_segments(api, task_end["task_uuid"]) == []
        queued_log = api.get(f"/api/v1/history/{queued_end['task_uuid']}").json()
        assert queued_log["status"] == TaskStatus.CANCELLED

    @pytest.mark.parametrize("retain_audio", [True, False], ids=["retain", "no-retain"])
    def test_cancelled_in_the_queue_is_recorded_and_its_upload_handled(
            self, api, fake, settings, monkeypatch, data_dir, retain_audio):
        monkeypatch.setattr(settings, "retain_audio", retain_audio)
        fake.hold = threading.Event()
        fake.script = list(SCRIPT)
        running_file, queued_file = upload(api, "a.wav"), upload(api, "b.wav")

        with api.websocket_connect("/api/v1/ws/uid-running") as running, \
                api.websocket_connect("/api/v1/ws/uid-queued") as queued:
            submit(running, running_file)
            assert fake.started.wait(TIMEOUT)
            # GPU 佇列只有一個 worker：第二個任務排在佇列裡，撤銷之後就不會開始
            submit(queued, queued_file)
            cancel_when_dispatched(api, "uid-queued")
            queued_end = receive_until_terminal(queued)[-1]
            fake.hold.set()
            receive_until_terminal(running)

        # 沒開始的任務照樣收尾，和開始前才發現被取消的任務一樣：記成已取消，
        # 上傳檔照保留設定搬進保留區或刪掉，不留在暫存區；取消旗標與登記也清掉
        assert queued_end["status_code"] == TaskStatus.CANCELLED
        assert len(fake.calls) == 1
        task_uuid = queued_end["task_uuid"]
        assert api.get(f"/api/v1/history/{task_uuid}").json()["status"] == TaskStatus.CANCELLED
        audio = api.get(f"/api/v1/transcripts/{task_uuid}/audio")
        if retain_audio:
            assert audio.content == synthetic_audio()
        else:
            assert audio.status_code == 404
        assert leftovers(data_dir) == []
        assert run_mode.get().is_cancel_requested("uid-queued") is False
        again = api.post("/api/v1/transcription/uid-queued/cancel").json()
        assert again["reason"] == "not-started"

    def test_task_still_queued_when_the_app_closes_is_recorded_as_failed(
            self, api, fake, data_dir, in_process_run_mode):
        fake.hold = threading.Event()
        fake.script = list(SCRIPT)
        # 檔名在整個測試資料庫裡唯一：之後從歷史紀錄用檔名找到它
        running_file, queued_file = upload(api, "a.wav"), upload(api, "queued-at-close.wav")

        with api.websocket_connect("/api/v1/ws/uid-open") as running, \
                api.websocket_connect("/api/v1/ws/uid-waiting") as queued:
            submit(running, running_file)
            assert fake.started.wait(TIMEOUT)
            submit(queued, queued_file)
            # 派送好了（登記了）才關：還在排隊
            wait_until(lambda: run_mode.get().registered_task("uid-waiting") is not None)
            # 應用程式關閉（lifespan 關掉執行模式）：還在排隊的任務不會再執行
            in_process_run_mode.close()
            fake.hold.set()
            receive_until_terminal(running)

        # 和開始前就被取消的任務一樣有紀錄、上傳檔照保留設定處理，只是記成失敗並寫明原因
        [listed] = api.get("/api/v1/history", params={"keyword": queued_file}).json()["items"]
        record = api.get(f"/api/v1/history/{listed['task_uuid']}").json()
        assert record["status"] == TaskStatus.FAILED
        assert "關閉" in record["error_message"]
        audio = api.get(f"/api/v1/transcripts/{listed['task_uuid']}/audio")
        assert audio.content == synthetic_audio()
        assert leftovers(data_dir) == []
        assert len(fake.calls) == 1

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

    def test_cancel_during_a_chunk_stops_before_the_next_chunk(self, api, fake, data_dir):
        # 語音視圖約 7 秒、單次只能處理 5 秒：切成兩段。供應商不理會取消，照樣轉完手上這一段
        fake.model_capabilities = replace(fake.model_capabilities, single_pass_seconds=5.0)
        fake.ignores_cancel = True
        fake.hold = threading.Event()
        fake.script = [[(0.2, 1.5, 0, "一つ目。")], [(0.2, 0.9, 1, "二つ目。")]]
        filename = upload(api)
        with api.websocket_connect("/api/v1/ws/uid-between-chunks") as ws:
            submit(ws, filename)
            assert fake.started.wait(TIMEOUT)
            cancel_when_dispatched(api, "uid-between-chunks")
            receive_until_terminal(ws)  # 取消端點的廣播
            fake.hold.set()
            task_end = receive_until_terminal(ws)[-1]

        # 下一段不再送進供應商；切出的段照樣清掉
        assert task_end["status_code"] == TaskStatus.CANCELLED
        assert len(fake.calls) == 1
        assert leftovers(data_dir) == []

    @pytest.mark.parametrize("single_pass_seconds", [600.0, 5.0],
                             ids=["whole-audio", "first-of-two-chunks"])
    def test_what_the_provider_finished_after_the_cancel_is_still_billed(
            self, api, fake, single_pass_seconds):
        # 供應商不理會取消、照樣轉完手上這一段，也就照樣收費（例如 Gemini 已經送出的生成）；
        # 分段轉錄時，下一段不再送出
        fake.model_capabilities = replace(
            fake.model_capabilities, pricing="per_token", single_pass_seconds=single_pass_seconds)
        fake.usage = (200_000, 40_000)
        fake.script = [[(0.2, 1.5, 0, "一つ目。")], [(0.2, 0.9, 1, "二つ目。")]]
        task_end = cancel_after_the_provider_finished(api, fake, "uid-billed-after-cancel")

        # 任務維持已取消，轉完的那一段的用量與費用照樣記在紀錄上，計費頁才不會少算
        # （價目見上面的計價測試）
        assert task_end["status_code"] == TaskStatus.CANCELLED
        record = api.get(f"/api/v1/history/{task_end['task_uuid']}").json()
        assert record["status"] == TaskStatus.CANCELLED
        assert record["total_tokens"] == 240_000
        assert record["cost"] == pytest.approx(0.30)

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

    def test_cancel_while_the_task_is_being_dispatched_does_not_lose_it(self, api, fake):
        fake.hold = threading.Event()
        fake.script = list(SCRIPT)
        held = DispatchHeld(run_mode.get())
        filename = upload(api)
        previous = run_mode.use(held)
        try:
            with api.websocket_connect("/api/v1/ws/uid-dispatching") as ws:
                submit(ws, filename)
                # 任務正在交給執行模式時按下取消：還沒有可以取消的任務，請前端稍後再試
                assert held.reached.wait(TIMEOUT)
                early = api.post("/api/v1/transcription/uid-dispatching/cancel").json()
                held.release.set()
                # 派送完再按一次就取消得到：任務沒有因為太早按取消而變成取消不了
                cancel_when_dispatched(api, "uid-dispatching")
                endpoint_end = receive_until_terminal(ws)[-1]
                task_end = receive_until_terminal(ws)[-1]
        finally:
            run_mode.use(previous)

        assert early == {"file_uid": "uid-dispatching", "cancelled": False,
                         "reason": "not-started"}
        assert codes([endpoint_end, task_end]) == [TaskStatus.CANCELLED] * 2

    def test_cancel_while_the_task_is_finishing_reports_it_finished(self, api, fake):
        fake.script = list(SCRIPT)
        held = FinishingHeld(run_mode.get())
        filename = upload(api)
        with api.websocket_connect("/api/v1/ws/uid-finishing") as ws:
            previous = run_mode.use(held)
            try:
                submit(ws, filename)
                # 任務已經記下完成、還在收尾時，使用者按下取消
                assert held.reached.wait(TIMEOUT)
                response = api.post("/api/v1/transcription/uid-finishing/cancel").json()
                flag_left = run_mode.get().is_cancel_requested("uid-finishing")
                held.release.set()
                messages = receive_until_terminal(ws)
            finally:
                run_mode.use(previous)

        # 回報任務已經結束、不廣播已取消：畫面不會先跳已取消再翻成完成；取消旗標也沒留下來
        assert response == {"file_uid": "uid-finishing", "cancelled": False, "reason": "finished"}
        assert TaskStatus.CANCELLED not in codes(messages)
        assert codes(messages)[-1] == TaskStatus.COMPLETED
        assert flag_left is False
        record = api.get(f"/api/v1/history/{messages[-1]['task_uuid']}").json()
        assert record["status"] == TaskStatus.COMPLETED

    def test_cancel_on_a_task_that_ended_but_stayed_registered_reports_it_finished(
            self, api, fake, run_mode_spy):
        # 任務收尾時清不掉登記（Docker 模式的 Redis 剛好斷線）：登記留著，任務其實已經結束
        healthy = run_mode.use(CancelFlagsDown(run_mode.get()))
        try:
            end = cancel_while_transcribing(api, fake, "uid-stale")
        finally:
            run_mode.use(healthy)
        wait_until(lambda: not run_mode.get().is_alive(end["task_uuid"]))
        revoked = list(run_mode_spy.revoked)

        response = api.post("/api/v1/transcription/uid-stale/cancel").json()

        # 回報已結束：不再撤銷、不再廣播；留下來的登記與取消旗標順手清掉
        assert response == {"file_uid": "uid-stale", "cancelled": False, "reason": "finished"}
        assert run_mode_spy.revoked == revoked
        again = api.post("/api/v1/transcription/uid-stale/cancel").json()
        assert again["reason"] == "not-started"
        assert run_mode.get().is_cancel_requested("uid-stale") is False

    def test_cancel_while_re_transcribing_leaves_the_earlier_task_alone(
            self, api, fake, run_mode_spy):
        fake.script = [Fail("模型壞掉了"), list(SCRIPT[0])]
        earlier = transcribe(api, "uid-again")[-1]
        assert earlier["status_code"] == TaskStatus.FAILED

        # 失敗後重新轉錄：新的音檔還在上傳、還沒送出任務時，使用者就按下取消
        response = api.post("/api/v1/transcription/uid-again/cancel").json()

        # 沒有任務可以取消，請前端稍後再試；早就結束的上一個任務不撤銷，紀錄維持失敗
        assert response == {"file_uid": "uid-again", "cancelled": False, "reason": "not-started"}
        assert run_mode_spy.revoked == []
        assert api.get(f"/api/v1/history/{earlier['task_uuid']}").json()["status"] == TaskStatus.FAILED
        # 新任務照常跑完
        assert transcribe(api, "uid-again")[-1]["status_code"] == TaskStatus.COMPLETED

    def test_frontend_recognises_every_reason_the_endpoint_returns(self, api):
        # 沒有取消時，前端照原因說明（#161）：端點回的每一種原因前端都要認得。認不得的只會
        # 說「任務沒有取消」，使用者分不出要不要再按一次
        never_sent = api.post("/api/v1/transcription/uid-never-sent/cancel").json()
        # 登記了、執行模式卻不認得的任務已經結束
        run_mode.get().register_task("uid-ended", "task-already-gone", can_terminate=True)
        ended = api.post("/api/v1/transcription/uid-ended/cancel").json()
        reasons = {never_sent["reason"], ended["reason"]}

        source = FRONTEND_CANCEL_RESPONSE_READER.read_text(encoding="utf-8")
        handled = re.findall(r"case '([\w-]+)':", source)

        assert reasons == {"not-started", "finished"}
        assert sorted(handled) == sorted(reasons)

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
    """暫時錯誤（429、503 之類）只重試那一段（#112）：等一段時間再轉那一段，已完成的段不重送。

    單次只能處理 5 秒：7.2 秒的語音視圖在 4.9 秒切成兩段（見 TestSplitRetryAfterFailure）。第一次
    等待調成 0.01 秒，測試不必真的等。
    """

    @pytest.fixture(autouse=True)
    def _two_chunks(self, fake, quick_transient_retries):
        fake.model_capabilities = replace(fake.model_capabilities, single_pass_seconds=5.0)

    def test_only_the_chunk_that_hit_it_is_retried(self, api, fake):
        fake.script = [[(0.2, 0.8, 0, "一つ目。")], TransientError("503 服務暫時無法使用"),
                       [(0.2, 0.8, 1, "二つ目。")]]
        messages = transcribe(api, "uid-transient")

        assert TaskStatus.FAILED not in codes(messages)
        assert codes(messages)[-1] == TaskStatus.COMPLETED
        # 第一段沒有重送
        assert fake.durations == pytest.approx([4.9, 2.3, 2.3], abs=0.01)
        segments = stored_segments(api, messages[-1]["task_uuid"])
        assert [s["seg_key"] for s in segments] == ["a.0000", "b.0000"]

    def test_each_wait_is_announced_before_it_starts(self, api, fake):
        # 畫面看得出任務沒有卡住：第幾段、為什麼、等幾秒、第幾次重試。回應沒有建議等待秒數，
        # 從 0.01 秒開始每次加倍
        fake.script = [[(0.2, 0.8, 0, "一つ目。")], TransientError("503 服務暫時無法使用"),
                       TransientError("503 服務暫時無法使用"), [(0.2, 0.8, 1, "二つ目。")]]
        messages = transcribe(api, "uid-transient-notice")

        assert codes(messages)[-1] == TaskStatus.COMPLETED
        notices = [m for m in messages if "暫時錯誤" in m["status_text"]]
        assert [m["status_text"] for m in notices] == [
            "分段轉錄的第 2 段（00:09–00:12）遇到暫時錯誤（503 服務暫時無法使用），"
            "0.01 秒後第 1 次重試（最多 3 次）...",
            "分段轉錄的第 2 段（00:09–00:12）遇到暫時錯誤（503 服務暫時無法使用），"
            "0.02 秒後第 2 次重試（最多 3 次）...",
        ]
        assert {m["status_code"] for m in notices} == {TaskStatus.PROCESSING}

    @pytest.mark.parametrize("suggested, cap, notice", [
        (0.03, 120.0, "遇到暫時錯誤（429 配額用完），0.03 秒後第 1 次重試（最多 3 次）..."),
        (30.0, 0.02, "遇到暫時錯誤（429 配額用完），0.02 秒後第 1 次重試（最多 3 次）..."),
    ], ids=["as-suggested", "capped"])
    def test_the_suggested_wait_is_followed_up_to_the_cap(
            self, api, fake, settings, monkeypatch, suggested, cap, notice):
        # 回應建議了等待秒數（例如 429 的 RetryInfo）時照它，但不超過上限。音檔沒有分段，說明不必寫
        # 第幾段
        fake.model_capabilities = replace(fake.model_capabilities, single_pass_seconds=600.0)
        monkeypatch.setattr(settings, "transient_error_max_wait_seconds", cap)
        fake.script = [TransientError("429 配額用完", retry_after=suggested), list(SCRIPT[0])]
        messages = transcribe(api, "uid-suggested-wait")

        assert codes(messages)[-1] == TaskStatus.COMPLETED
        assert [m["status_text"] for m in messages if "暫時錯誤" in m["status_text"]] == [notice]

    def test_task_fails_when_the_retries_run_out(self, api, fake):
        # 第二段每次都遇到暫時錯誤：重試 3 次之後任務失敗，寫明哪一段、重試了幾次與最後的錯誤。
        # 執行模式不再重試整個任務：第一段只送一次，任務不會停在處理中
        fake.script = [[(0.2, 0.8, 0, "一つ目。")]] + [TransientError("503 服務暫時無法使用")] * 4
        messages = transcribe(api, "uid-transient-final")

        assert codes(messages)[-1] == TaskStatus.FAILED
        assert fake.durations == pytest.approx([4.9] + [2.3] * 4, abs=0.01)
        reason = "分段轉錄的第 2 段（00:09–00:12）：暫時錯誤重試 3 次仍失敗（503 服務暫時無法使用）"
        assert reason in messages[-1]["status_text"]
        record = api.get(f"/api/v1/history/{messages[-1]['task_uuid']}").json()
        assert record["status"] == TaskStatus.FAILED
        assert reason in record["error_message"]

    def test_the_short_reason_is_shown_instead_of_the_whole_error(self, api, fake):
        # 轉接器給了簡短的原因（Gemini 給狀態碼與狀態）：等待說明與失敗原因寫它，不寫附著整份錯誤
        # 內容的例外訊息，畫面放得下
        error = TransientError(
            "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'details': ['QuotaFailure', 'RetryInfo']}}",
            reason="429 RESOURCE_EXHAUSTED")
        fake.script = [[(0.2, 0.8, 0, "一つ目。")]] + [error] * 4
        messages = transcribe(api, "uid-transient-reason")

        notices = [m["status_text"] for m in messages
                   if m["status_code"] == TaskStatus.PROCESSING and "暫時錯誤" in m["status_text"]]
        assert notices[0] == ("分段轉錄的第 2 段（00:09–00:12）遇到暫時錯誤（429 RESOURCE_EXHAUSTED），"
                              "0.01 秒後第 1 次重試（最多 3 次）...")
        assert codes(messages)[-1] == TaskStatus.FAILED
        assert messages[-1]["status_text"].endswith(
            "分段轉錄的第 2 段（00:09–00:12）：暫時錯誤重試 3 次仍失敗（429 RESOURCE_EXHAUSTED）]]")

    def test_cancel_while_waiting_stops_at_once(self, api, fake, settings, monkeypatch):
        # 等待重試的期間按下取消：不必等退避結束就停下，任務記成已取消，不再送出。等待調得比
        # 測試的逾時還長，不停下的話這裡會逾時
        monkeypatch.setattr(settings, "transient_error_initial_wait_seconds", 2 * TIMEOUT)
        fake.script = [TransientError("503 服務暫時無法使用")]
        filename = upload(api)
        with api.websocket_connect("/api/v1/ws/uid-cancel-while-waiting") as ws:
            submit(ws, filename)
            while "秒後第 1 次重試" not in receive(ws)["status_text"]:
                pass
            cancel_when_dispatched(api, "uid-cancel-while-waiting")
            endpoint_end = receive_until_terminal(ws)[-1]
            task_end = receive_until_terminal(ws)[-1]

        assert codes([endpoint_end, task_end]) == [TaskStatus.CANCELLED] * 2
        assert len(fake.calls) == 1
        record = api.get(f"/api/v1/history/{task_end['task_uuid']}").json()
        assert record["status"] == TaskStatus.CANCELLED

    def test_one_that_reaches_the_task_is_a_failure_and_the_task_is_not_rerun(self, api, fake):
        # 萬一有暫時錯誤沒經過分段轉錄就漏到任務（這裡是建立轉接器時）：照失敗處理，執行模式不再
        # 重試整個任務，任務也不會停在處理中
        fake.open_error = TransientError("503 服務暫時無法使用")
        messages = transcribe(api, "uid-transient-escaped")

        assert codes(messages)[-1] == TaskStatus.FAILED
        assert "503 服務暫時無法使用" in messages[-1]["status_text"]
        assert fake.opened == 1
        record = api.get(f"/api/v1/history/{messages[-1]['task_uuid']}").json()
        assert record["status"] == TaskStatus.FAILED


# ─── 非 ASCII 檔名 ───────────────────────────────────────────────────────────

def download_filename(response) -> str:
    """Content-Disposition 標頭給的檔名；非 ASCII 的檔名照 RFC 5987 寫成 filename*=utf-8''…。"""
    header = response.headers["content-disposition"]
    match = re.search(r"filename\*=utf-8''([^;]+)", header, re.IGNORECASE)
    assert match, header
    return unquote(match.group(1))


class TestNonAsciiFilename:
    """日文、中文檔名的音檔，放在中文的資料夾裡，走完上傳 → ffmpeg → 下載。

    磁碟上的暫存檔是隨機名稱（#231 Q5），原檔名經過請求、任務紀錄與下載；資料夾的路徑本身也可能有
    中文（例如 Windows 帳號是中文名，解壓在桌面），暫存路徑、ffmpeg 的參數與輸出都帶著它。
    CI 的 Windows job 刻意不開 UTF-8 模式（PYTHONUTF8），和使用者的電腦一樣用系統碼頁：
    哪一處用了系統碼頁就會在那裡出錯。
    """

    @pytest.fixture
    def data_dir(self, data_dir, monkeypatch):
        """上傳檔、保留音檔與去靜音產物改放在中文名稱的資料夾裡；回傳那個資料夾。"""
        from app.api import batch, transcription, upload, vad
        from app.core.config import get_settings

        root = data_dir / "王小明的桌面"
        uploads = root / "temp_uploads"
        uploads.mkdir(parents=True)
        settings = get_settings()
        monkeypatch.setattr(settings, "temp_uploads_dir", str(uploads))
        monkeypatch.setattr(settings, "audio_store_dir", str(root / "audio_store"))
        monkeypatch.setattr(settings, "vad_artifacts_dir", str(root / "vad_artifacts"))
        for module in (transcription, upload, batch, vad):
            monkeypatch.setattr(module, "TEMP_UPLOADS_DIR", uploads)
        return root

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


# ─── 存片段：和完成一起寫，同一個任務再完成一次時不刪校正（#114） ───────────

class Redelivers:
    """Docker 模式的 Celery 重派：同一個任務（同一個 task id、同一份參數）再執行一次，
    其餘照轉；用 ``run_mode.use`` 換上。行程內執行模式不會重派任務。"""

    def __init__(self, inner):
        self._inner = inner
        self._params = {}

    def submit_transcription(self, task_id, task_params_dict, queue):
        self._inner.submit_transcription(task_id, task_params_dict, queue)
        self._params[task_id] = task_params_dict

    def redeliver(self, task_id: str) -> None:
        """同一個任務再執行一次，跑完才回來。"""
        from app.tasks.transcribe_core import run_transcription

        run_transcription(self._params[task_id], task_id)

    def __getattr__(self, name):
        return getattr(self._inner, name)


@pytest.fixture
def redelivery(run_mode_spy):
    mode = Redelivers(run_mode.get())
    previous = run_mode.use(mode)
    yield mode
    run_mode.use(previous)


def mark_segment(engine, task_uuid: str, seg_key: str, **fields) -> None:
    """使用者在一個片段上校正或標確認狀態：校正介面是 v0.2，還沒有端點，直接寫進片段。"""
    from sqlalchemy.orm import sessionmaker

    from app.database.models import TranscriptSegment
    from app.utils.identifiers import coerce_uuid

    with sessionmaker(bind=engine)() as db:
        marked = db.query(TranscriptSegment).filter(
            TranscriptSegment.task_uuid == coerce_uuid(task_uuid),
            TranscriptSegment.seg_key == seg_key,
        ).update(fields)
        db.commit()
    assert marked == 1


@contextmanager
def segments_unwritable(engine):
    """這段期間資料庫寫不進片段（例如磁碟剛好滿了），任務紀錄照樣寫得進去。"""
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TRIGGER segments_unwritable BEFORE INSERT ON transcript_segments "
            "BEGIN SELECT RAISE(ABORT, 'database or disk is full'); END"))
    try:
        yield
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP TRIGGER segments_unwritable"))


# 第一次完成有四個片段；再完成一次時，模型聽成不一樣的文字，而且少了最後一段
FIRST_RUN = [
    (0.2, 1.5, 0, "おはよう。"),
    (2.3, 3.6, 1, "こんにちは。"),
    (4.4, 5.6, 0, "またね。"),
    (6.0, 6.8, 1, "じゃあね。"),
]
SECOND_RUN = [
    (0.2, 1.5, 0, "おはよ。"),
    (2.3, 3.6, 1, "こんにちわ。"),
    (4.4, 5.6, 0, "まったね。"),
]


class TestSegmentsAreSavedWithTheCompletion:
    def test_task_whose_segments_cannot_be_stored_fails(self, api, fake, test_engine):
        fake.script = [list(FIRST_RUN)]
        with segments_unwritable(test_engine):
            messages = transcribe(api, "uid-unwritable")

        # 片段和「完成」一起寫進去：片段寫不進去，任務就沒有完成，不會只記警告就宣告完成
        assert codes(messages)[-1] == TaskStatus.FAILED
        task_uuid = messages[-1]["task_uuid"]
        assert api.get(f"/api/v1/history/{task_uuid}").json()["status"] == TaskStatus.FAILED
        assert stored_segments(api, task_uuid) == []


class TestCompletingTheSameTaskAgain:
    @pytest.fixture
    def task_uuid(self, api, fake, redelivery):
        """完成過一次（FIRST_RUN）的任務；再完成一次時，假供應商回 SECOND_RUN。"""
        fake.script = [list(FIRST_RUN), list(SECOND_RUN)]
        return transcribe(api, "uid-again")[-1]["task_uuid"]

    def test_without_touched_segments_the_new_result_replaces_all(
            self, api, redelivery, task_uuid):
        redelivery.redeliver(task_uuid)

        # 和以前一樣整批換成這次的結果，這次沒有的那一段也拿掉
        assert [s["text"] for s in stored_segments(api, task_uuid)] == [
            "おはよ。", "こんにちわ。", "まったね。"]

    def test_segments_the_user_touched_are_kept_others_take_the_new_result(
            self, api, redelivery, task_uuid, test_engine):
        keys = [s["seg_key"] for s in stored_segments(api, task_uuid)]
        # 使用者校正了第一段，把第三段標成已確認
        mark_segment(test_engine, task_uuid, keys[0], text="おはようございます。", source="edited")
        mark_segment(test_engine, task_uuid, keys[2], review_state="verified")
        corrected, _, verified, _ = stored_segments(api, task_uuid)

        redelivery.redeliver(task_uuid)

        # 這兩段不刪、不覆寫；其他片段換成這次的結果，這次沒有的第四段拿掉
        segments = stored_segments(api, task_uuid)
        assert [s["text"] for s in segments] == ["おはようございます。", "こんにちわ。", "またね。"]
        assert (segments[0], segments[2]) == (corrected, verified)

    def test_failing_to_store_the_new_segments_leaves_the_old_ones_untouched(
            self, api, redelivery, task_uuid, test_engine):
        first_key = stored_segments(api, task_uuid)[0]["seg_key"]
        mark_segment(test_engine, task_uuid, first_key, text="おはようございます。", source="edited")
        before = stored_segments(api, task_uuid)

        with segments_unwritable(test_engine), pytest.raises(Exception, match="disk is full"):
            redelivery.redeliver(task_uuid)

        # 這次的片段寫不進去：任務記成失敗，使用者的校正和上一次的結果都原封不動
        assert api.get(f"/api/v1/history/{task_uuid}").json()["status"] == TaskStatus.FAILED
        assert stored_segments(api, task_uuid) == before


# ─── 失敗的任務照樣記用量 ───────────────────────────────────────────────────

def usage_totals(api) -> dict:
    """儀表板與計費頁的用量（GET /history/usage）：每日用量加起來的總數，以及假模型那一列。

    測試資料庫裡還有其他測試的任務，要比較的是前後的差。
    """
    usage = api.get("/api/v1/history/usage").json()
    model = next((row for row in usage["by_model"] if row["model"] == FAKE_MODEL),
                 {"tokens": 0, "cost": 0.0, "files": 0})
    fields = ("tokens", "cost", "files")
    return {"daily": {key: sum(day[key] for day in usage["daily"]) for key in fields},
            "by_model": {key: model[key] for key in fields}}


class CancelFlagUnreadable:
    """任務查不到取消旗標（Docker 模式的 Redis 斷線時，寧可讓任務繼續），其餘照轉：取消端點照樣把
    紀錄記成已取消。用 ``run_mode.use`` 換上。"""

    def __init__(self, inner):
        self._inner = inner

    def is_cancel_requested(self, file_uid):
        return False

    def __getattr__(self, name):
        return getattr(self._inner, name)


class CancelWhilePricing:
    """任務記下完成之前、正在計價時，使用者剛好按下取消：取消端點先設的取消旗標已經在了，紀錄還沒
    記成已取消。其餘照轉；用 ``run_mode.use`` 換上。"""

    def __init__(self, inner):
        self._inner = inner

    def publish(self, message):
        if message.get("status_text") == "正在計算費用...":
            self._inner.request_cancel(message["file_uid"])
        self._inner.publish(message)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class TestUsageOfTasksThatDidNotComplete:
    """供應商已經回應、任務才失敗（或失敗時剛好被取消）時，供應商照樣收費（例如 Gemini 的回應被阻擋）：
    用量與費用照樣記在任務紀錄上，儀表板與計費頁才不會少算；沒有用量時留空（#155）。價目見
    TestSingleFileTask 的計價測試：一次呼叫 240,000 個 token、0.30 美元。"""

    @pytest.fixture(autouse=True)
    def _priced_per_token(self, fake):
        fake.model_capabilities = replace(fake.model_capabilities, pricing="per_token")
        fake.usage = (200_000, 40_000)

    def test_failed_result_is_recorded_and_priced(self, api, fake):
        fake.script = [Fail("回應被阻擋")]
        end = transcribe(api, "uid-failed-billed")[-1]

        assert end["status_code"] == TaskStatus.FAILED
        record = api.get(f"/api/v1/history/{end['task_uuid']}").json()
        assert record["status"] == TaskStatus.FAILED
        assert "回應被阻擋" in record["error_message"]
        assert record["total_tokens"] == 240_000
        assert record["cost"] == pytest.approx(0.30)
        assert record["service_tier_used"] == "standard"
        assert record["audio_duration_seconds"] == pytest.approx(12.0, abs=0.1)

    def test_failure_without_any_usage_leaves_it_empty(self, api, fake):
        # 供應商沒有回報用量（例如本機的模型不回報 token）：不記用量，歷史紀錄的 token 與費用留空，
        # 不會變成 0 元
        fake.usage = (0, 0)
        fake.script = [Fail("模型壞掉了")]
        end = transcribe(api, "uid-failed-unbilled")[-1]

        assert end["status_code"] == TaskStatus.FAILED
        record = api.get(f"/api/v1/history/{end['task_uuid']}").json()
        assert (record["total_tokens"], record["cost"]) == (None, None)

    def test_cancel_without_any_usage_leaves_it_empty(self, api, fake):
        # 取消也一樣：供應商照樣轉完、卻沒有回報用量時，不記成 0 個 token、0 元
        fake.usage = (0, 0)
        fake.script = list(SCRIPT)
        end = cancel_after_the_provider_finished(api, fake, "uid-cancelled-unbilled")

        assert end["status_code"] == TaskStatus.CANCELLED
        record = api.get(f"/api/v1/history/{end['task_uuid']}").json()
        assert (record["total_tokens"], record["cost"]) == (None, None)

    def test_failure_after_the_cancel_was_recorded_is_billed_as_a_cancel(self, api, fake):
        # 任務查不到取消旗標，取消端點已經把紀錄記成已取消；供應商之後才回報失敗：失敗不蓋掉取消，
        # 這次呼叫的用量照樣記在已取消的紀錄上
        fake.script = [Fail("回應被阻擋")]
        readable = run_mode.use(CancelFlagUnreadable(run_mode.get()))
        try:
            end = cancel_after_the_provider_finished(api, fake, "uid-failed-after-cancel")
        finally:
            run_mode.use(readable)

        assert end["status_code"] == TaskStatus.CANCELLED
        record = api.get(f"/api/v1/history/{end['task_uuid']}").json()
        assert record["status"] == TaskStatus.CANCELLED
        assert record["total_tokens"] == 240_000
        assert record["cost"] == pytest.approx(0.30)

    def test_cancel_while_the_result_is_being_saved_is_billed(self, api, fake, test_engine):
        # 正在記下完成時使用者剛好按下取消，片段又寫不進去：記成已取消，供應商已經轉完的這次呼叫照樣
        # 記下用量
        fake.script = list(SCRIPT)
        previous = run_mode.use(CancelWhilePricing(run_mode.get()))
        try:
            with writes_fail(test_engine, "transcript_segments", "INSERT"):
                end = transcribe(api, "uid-cancel-while-saving")[-1]
        finally:
            run_mode.use(previous)

        assert end["status_code"] == TaskStatus.CANCELLED
        record = api.get(f"/api/v1/history/{end['task_uuid']}").json()
        assert record["status"] == TaskStatus.CANCELLED
        assert record["total_tokens"] == 240_000
        assert record["cost"] == pytest.approx(0.30)

    @pytest.mark.parametrize("split_retry, script", [
        (False, [[(0.2, 0.8, 0, "一つ目。")], Fail("模型壞掉了")]),
        (True, [[(0.2, 0.8, 0, "一つ目。")], Fail("模型壞掉了"), Fail("模型壞掉了")]),
    ], ids=["without-split-retry", "after-split-retry"])
    def test_chunks_finished_before_the_failure_are_billed_too(
            self, api, fake, settings, monkeypatch, split_retry, script):
        # 切成 4.9 秒與 2.3 秒兩段（見 TestSplitRetryAfterFailure）：第一段轉完，第二段失敗。切段重試
        # 時第二段再切成兩個 1.15 秒，前一個又失敗、短於下限 2 秒，任務失敗。轉完的段與失敗的每一次
        # 呼叫都照樣收費
        fake.model_capabilities = replace(
            fake.model_capabilities, single_pass_seconds=5.0, split_retry_on_failure=split_retry)
        monkeypatch.setattr(settings, "transcription_max_duration_seconds", 2)
        fake.script = list(script)
        end = transcribe(api, "uid-chunk-failed-billed")[-1]

        assert end["status_code"] == TaskStatus.FAILED
        assert len(fake.calls) == len(script)
        record = api.get(f"/api/v1/history/{end['task_uuid']}").json()
        assert record["total_tokens"] == 240_000 * len(script)
        assert record["cost"] == pytest.approx(0.30 * len(script))

    def test_chunks_finished_before_an_unexpected_error_are_billed_too(self, api, fake):
        # 分段轉錄裡冒出非預期的例外（程式錯誤）時也一樣（#198）：切成 4.9 秒與 2.3 秒兩段，兩段都
        # 轉完，第二段的轉接器卻回傳不是數字的開始時間，合併時出錯。兩次呼叫照樣收費
        fake.model_capabilities = replace(fake.model_capabilities, single_pass_seconds=5.0)
        fake.script = [[(0.2, 0.8, 0, "一つ目。")], [("0.1", 0.8, 0, "二つ目。")]]
        end = transcribe(api, "uid-unexpected-error-billed")[-1]

        assert end["status_code"] == TaskStatus.FAILED
        assert len(fake.calls) == 2
        record = api.get(f"/api/v1/history/{end['task_uuid']}").json()
        assert record["status"] == TaskStatus.FAILED
        assert record["total_tokens"] == 2 * 240_000
        assert record["cost"] == pytest.approx(2 * 0.30)

    def test_task_whose_segments_cannot_be_stored_is_billed(self, api, fake, test_engine):
        # 供應商轉完了，片段卻寫不進資料庫（例如磁碟剛好滿了）：任務照失敗處理，這次呼叫照樣收費
        fake.script = list(SCRIPT)
        with writes_fail(test_engine, "transcript_segments", "INSERT"):
            end = transcribe(api, "uid-unwritable-billed")[-1]

        assert end["status_code"] == TaskStatus.FAILED
        record = api.get(f"/api/v1/history/{end['task_uuid']}").json()
        assert record["status"] == TaskStatus.FAILED
        assert record["total_tokens"] == 240_000
        assert record["cost"] == pytest.approx(0.30)

    def test_usage_counts_failed_and_cancelled_tasks_but_only_completed_files(self, api, fake):
        # 取消、失敗、完成的任務各一個，各呼叫供應商一次：三次的 token 與費用都算進每日與各模型的
        # 用量，檔案數只算完成的那一個
        before = usage_totals(api)
        fake.script = [list(SCRIPT[0]), Fail("回應被阻擋"), list(SCRIPT[0])]
        ends = [cancel_after_the_provider_finished(api, fake, "uid-usage-cancelled"),
                transcribe(api, "uid-usage-failed")[-1],
                transcribe(api, "uid-usage-completed")[-1]]
        after = usage_totals(api)

        assert codes(ends) == [TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.COMPLETED]
        for view in ("daily", "by_model"):
            assert after[view]["tokens"] - before[view]["tokens"] == 3 * 240_000
            assert after[view]["cost"] - before[view]["cost"] == pytest.approx(3 * 0.30)
            assert after[view]["files"] - before[view]["files"] == 1
