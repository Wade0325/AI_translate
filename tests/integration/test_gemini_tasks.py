"""Gemini 的單檔任務透過 API 跑完：Gemini 轉接器接上假的 google-genai 用戶端（#107、#110）。

這裡不換供應商，只換掉 google-genai 用戶端：遠端檔只有 Gemini 會留下。其他都走真的：TestClient、
sqlite、行程內執行模式、WebSocket 狀態廣播、ffmpeg 與去靜音。測試只從外部觀察：狀態廣播、API 回應、
送給 Gemini 的提示詞，以及遠端還留著哪些檔案。

批次透過 API 跑完的測試在 test_batch.py（假供應商，#115）；Gemini 轉接器的批次在
tests/unit/test_gemini_adapter.py。
"""
import threading

import pytest
from fastapi.testclient import TestClient

from app.core.task_status import TaskStatus
from app.provider import registry
from app.provider.google.provider import GeminiProvider
from tests.support.fake_genai import FakeGenaiClient, Reply, invalid_argument, unavailable
from tests.support.synthetic_audio import VOICED
from tests.support.task_api import receive_until, upload
from tests.support.waiting import TIMEOUT, wait_until

MODEL = "gemini-2.5-flash"

# 使用者的提示詞照樣代入變數，裡面的 JSON 之類的大括號原樣送給 Gemini（#143）
JSON_PROMPT = '請轉錄{source_lang}音檔，每一行寫成 {"speaker": "S0", "text": "…"}'
JSON_PROMPT_SENT = '請轉錄日文音檔，每一行寫成 {"speaker": "S0", "text": "…"}'


# ─── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def genai():
    return FakeGenaiClient()


class _GeminiWithFakeClient:
    """供應商「google」：建立的 Gemini 轉接器都接上同一個假用戶端，也不真的等。"""

    info = GeminiProvider.info

    def __init__(self, genai: FakeGenaiClient):
        self._genai = genai
        self.sleep = lambda seconds: None
        """轉接器等待（輪詢上傳檔、Flex 退避）時呼叫；預設不等。"""

    def capabilities(self):
        return GeminiProvider.capabilities()

    def __call__(self, model: str, api_key: str) -> GeminiProvider:
        return GeminiProvider(model, api_key, client=self._genai, sleep=lambda s: self.sleep(s))


@pytest.fixture
def gemini(genai):
    provider = _GeminiWithFakeClient(genai)
    previous = registry.register("google", provider)
    yield provider
    registry.register("google", previous)


@pytest.fixture
def api(gemini, api):
    """供應商「google」換成接上假用戶端的 Gemini 轉接器；換回之前先等任務跑完。"""
    return api


# ─── helpers ─────────────────────────────────────────────────────────────────

def transcribe(api: TestClient, run_mode, name: str, **fields) -> list[dict]:
    """上傳、送出單檔任務，收下所有廣播直到任務結束。file_uid 就是檔名。

    fields 是請求的其他欄位，例如提示詞。
    """
    filename = upload(api, name)
    with api.websocket_connect(f"/api/v1/ws/{name}") as ws:
        ws.send_json({"filename": filename, "original_filename": name,
                      "provider": "Google", "model": MODEL, "source_lang": "ja", **fields})
        messages = receive_until(ws, TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
    # 結束的廣播之後任務還在收尾（刪遠端檔就在這裡），等它整個跑完
    wait_until(lambda: not run_mode.is_alive(messages[-1]["task_uuid"]))
    return messages


def history(api: TestClient, original_filename: str) -> dict:
    items = api.get("/api/v1/history", params={"keyword": original_filename}).json()["items"]
    assert len(items) == 1, items
    return items[0]


# ─── 單檔 ────────────────────────────────────────────────────────────────────

def test_single_file_completes_and_its_remote_file_is_deleted(api, in_process_run_mode, genai):
    genai.replies = [Reply(text="[00:01.00]おはよう。")]

    end = transcribe(api, in_process_run_mode, "gemini-single-ok.wav")[-1]

    assert end["status_code"] == TaskStatus.COMPLETED
    assert "おはよう。" in end["result"]["transcripts"]["srt"]
    assert genai.stored == {}  # 任務結束時刪掉上傳到 Gemini 的檔案


def test_single_file_stores_segments_labelled_like_the_local_provider(api, in_process_run_mode, genai):
    # Gemini 的 LRC 在轉接器裡解析一次就變成片段：任務存下片段，字幕的說話者標記和本機一樣
    genai.replies = [Reply(text="[00:00.50]Speaker 1: おはよう。\n[00:03.00]Speaker 2: こんにちは。")]

    end = transcribe(api, in_process_run_mode, "gemini-single-speakers.wav")[-1]

    assert end["status_code"] == TaskStatus.COMPLETED
    segments = api.get(f"/api/v1/transcripts/{end['task_uuid']}").json()["segments"]
    assert [(s["speaker"], s["text"]) for s in segments] == [("S0", "おはよう。"), ("S1", "こんにちは。")]
    # 去靜音之後的時間還原回原音檔：第二句落在第二個有聲段（5–7 秒），不在被剪掉的靜音裡
    assert 4.5 <= segments[1]["start"] <= 7.5
    srt = api.get(f"/api/v1/history/{end['task_uuid']}/download/srt").text
    assert "[S0] おはよう。" in srt and "[S1] こんにちは。" in srt
    assert "Speaker" not in srt


def test_subtitles_end_where_gemini_wrote_it_and_otherwise_follow_the_old_rule(
        api, in_process_run_mode, genai):
    # 只有時間戳的行是 Gemini 寫明的結束時間，字幕照實際說話的時間顯示（ADR-0008）；沒寫結束時間
    # 的行照以前的規則，最後一行加 5 秒。兩行都在第一個有聲段，去靜音不改它們的時間
    genai.replies = [Reply(text="[00:00.50]おはよう。\n[00:01.50]\n[00:01.75]はい。")]

    end = transcribe(api, in_process_run_mode, "gemini-single-end-times.wav")[-1]

    assert end["status_code"] == TaskStatus.COMPLETED
    assert api.get(f"/api/v1/history/{end['task_uuid']}/download/srt").text == (
        "1\n00:00:00,500 --> 00:00:01,500\nおはよう。\n\n"
        "2\n00:00:01,750 --> 00:00:06,750\nはい。\n")


def test_single_file_failure_still_deletes_its_remote_file(api, in_process_run_mode, genai):
    # 假用戶端只在檔案已經上傳、處理完時才回這個錯：失敗之前遠端確實有檔案
    genai.replies = [invalid_argument("音檔無法解碼")]

    end = transcribe(api, in_process_run_mode, "gemini-single-fail.wav")[-1]

    assert end["status_code"] == TaskStatus.FAILED
    assert "音檔無法解碼" in end["status_text"]
    assert genai.stored == {}


def test_cancelling_a_running_task_stops_it_before_the_generation(
        api, in_process_run_mode, genai, gemini):
    name = "gemini-cancel.wav"
    polling, cancel_sent = threading.Event(), threading.Event()

    def sleep(seconds):
        polling.set()
        cancel_sent.wait(TIMEOUT)

    # 音檔上傳之後，Gemini 還要處理一下；使用者在等的期間按下取消
    gemini.sleep = sleep
    genai.processing_polls = 3
    filename = upload(api, name)
    with api.websocket_connect(f"/api/v1/ws/{name}") as ws:
        ws.send_json({"filename": filename, "original_filename": name,
                      "provider": "Google", "model": MODEL, "source_lang": "ja"})
        assert polling.wait(TIMEOUT)
        assert api.post(f"/api/v1/transcription/{name}/cancel").json()["cancelled"] is True
        cancel_sent.set()
        end = receive_until(ws, TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)[-1]
    wait_until(lambda: not in_process_run_mode.is_alive(end["task_uuid"]))

    # 沒有送出要收費的生成，已經上傳的遠端檔也刪掉了；任務紀錄是已取消，不會變回完成
    assert end["status_code"] == TaskStatus.CANCELLED
    assert genai.generated == []
    assert genai.stored == {}
    assert history(api, name)["status"] == TaskStatus.CANCELLED


def test_single_file_is_retried_after_a_transient_error(
        api, in_process_run_mode, genai, quick_transient_retries):
    # 503 是暫時錯誤：分段轉錄不把它當成這一段失敗，等一段時間（這裡調成 0.01 秒）再轉那一段
    genai.replies = [unavailable(), Reply(text="[00:01.00]おはよう。")]

    messages = transcribe(api, in_process_run_mode, "gemini-single-transient.wav")

    assert TaskStatus.FAILED not in [m["status_code"] for m in messages]
    assert messages[-1]["status_code"] == TaskStatus.COMPLETED
    assert "おはよう。" in messages[-1]["result"]["transcripts"]["srt"]
    assert history(api, "gemini-single-transient.wav")["status"] == TaskStatus.COMPLETED
    assert genai.stored == {}  # 兩次上傳的遠端檔都刪掉了


def test_single_file_prompt_with_braces_reaches_gemini_as_written(api, in_process_run_mode, genai):
    genai.replies = [Reply(text="[00:01.00]おはよう。")]

    end = transcribe(api, in_process_run_mode, "gemini-single-braces.wav",
                     prompt=JSON_PROMPT, source_lang="ja-JP")[-1]

    assert end["status_code"] == TaskStatus.COMPLETED
    assert genai.prompts == [JSON_PROMPT_SENT]


# ─── 分段轉錄 ────────────────────────────────────────────────────────────────

@pytest.fixture
def three_chunks(monkeypatch):
    """單次只能處理 3 秒：去靜音後約 7.2 秒的語音視圖在有聲段的交界切成三段，依序送進 Gemini，
    每一段是一個有聲段。"""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "long_audio_split_threshold_seconds", 3)


def stored(api: TestClient, task_uuid: str) -> list[tuple]:
    """存下來的片段：（落在第幾個有聲段, 說話者編號, 文字）。"""
    segments = api.get(f"/api/v1/transcripts/{task_uuid}").json()["segments"]
    return [(next(i for i, (lo, hi) in enumerate(VOICED) if lo - 0.5 <= s["start"] <= hi + 0.5),
             s["speaker"], s["text"]) for s in segments]


def test_chunk_without_any_line_is_skipped_and_the_others_are_kept(
        api, in_process_run_mode, genai, three_chunks):
    # 一段沒有任何帶時間戳的行（例如那段沒人說話）：算成功、沒有片段，任務照樣完成。
    # 其他段的片段平移、還原回原音檔，落在各自的有聲段；Gemini 寫明的結束時間也一樣
    genai.replies = [Reply(text="[00:00.50]おはよう。"), Reply(text=""),
                     Reply(text="[00:01.00]またね。\n[00:01.80]")]

    end = transcribe(api, in_process_run_mode, "gemini-chunks-gap.wav")[-1]

    assert end["status_code"] == TaskStatus.COMPLETED
    assert stored(api, end["task_uuid"]) == [(0, None, "おはよう。"), (2, None, "またね。")]
    last = api.get(f"/api/v1/transcripts/{end['task_uuid']}").json()["segments"][-1]
    assert last["start"] + 0.7 < last["end"] < VOICED[2][1] + 0.5


def test_speaker_ids_are_consistent_across_chunks(api, in_process_run_mode, genai, three_chunks):
    # Gemini 的同一個說話者代號在同一個任務的各段對到同一個說話者編號，依整個任務第一次出現的順序
    genai.replies = [
        Reply(text="[00:00.50]Speaker 2: おはよう。"),
        Reply(text="[00:00.50]Speaker 1: こんにちは。\n[00:01.50]Speaker 2: はい。"),
        Reply(text="[00:01.00]Speaker 2: またね。"),
    ]

    end = transcribe(api, in_process_run_mode, "gemini-chunks-speakers.wav")[-1]

    assert end["status_code"] == TaskStatus.COMPLETED
    assert stored(api, end["task_uuid"]) == [
        (0, "S0", "おはよう。"), (1, "S1", "こんにちは。"), (1, "S0", "はい。"), (2, "S0", "またね。")]


def test_task_fails_only_when_no_chunk_has_any_line(
        api, in_process_run_mode, genai, three_chunks, monkeypatch):
    # 整個任務合併完一個片段都沒有才算失敗，原因寫明。沒有內容不是轉錄失敗：每一段都長過切段重試
    # 的下限（調成 1 秒），也不切段重試（重試的話，後面的回應會被切出的段用掉，任務反而完成）
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "transcription_max_duration_seconds", 1)
    genai.replies = [Reply(text=""), Reply(text="這段聽不出任何語音。"), Reply(text="[00:01.00]")]

    end = transcribe(api, in_process_run_mode, "gemini-chunks-empty.wav")[-1]

    assert end["status_code"] == TaskStatus.FAILED
    assert "Gemini 的回應沒有任何帶時間戳的文字" in end["status_text"]
    assert "Gemini 的回應沒有任何帶時間戳的文字" in history(
        api, "gemini-chunks-empty.wav")["error_message"]
