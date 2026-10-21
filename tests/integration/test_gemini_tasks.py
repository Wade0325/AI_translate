"""Gemini 的單檔任務與批次透過 API 跑完：Gemini 轉接器接上假的 google-genai 用戶端（#107）。

這裡不換供應商，只換掉 google-genai 用戶端：批次目前只有 Gemini 支援，遠端檔也只有
Gemini 會留下。其他都走真的：TestClient、sqlite、行程內執行模式、WebSocket 狀態廣播、
ffmpeg 與去靜音。測試只從外部觀察：狀態廣播、API 回應、送給 Gemini 的提示詞，以及
遠端與上傳的暫存資料夾還留著哪些檔案。
"""
import io
import threading
from concurrent.futures import ThreadPoolExecutor, wait
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
from tests.support.waiting import wait_until

MODEL = "gemini-2.5-flash"
SAMPLE_RATE = 16000
TIMEOUT = 30

# 使用者的提示詞照樣代入變數，裡面的 JSON 之類的大括號原樣送給 Gemini（#143）
JSON_PROMPT = '請轉錄{source_lang}音檔，每一行寫成 {"speaker": "S0", "text": "…"}'
JSON_PROMPT_SENT = '請轉錄日文音檔，每一行寫成 {"speaker": "S0", "text": "…"}'


VOICED = [(0, 2), (5, 7), (10, 12)]
"""合成音檔的有聲段（秒）：有聲 2 秒、靜音 3 秒交錯，共 12 秒。"""


def synthetic_audio() -> bytes:
    """有聲段見 VOICED，其餘是靜音的合成 wav。"""
    samples = np.zeros(VOICED[-1][1] * SAMPLE_RATE, dtype=np.float32)
    for start, end in VOICED:
        t = np.arange((end - start) * SAMPLE_RATE) / SAMPLE_RATE
        samples[start * SAMPLE_RATE:end * SAMPLE_RATE] = 0.3 * np.sin(2 * np.pi * 440 * t)
    buffer = io.BytesIO()
    sf.write(buffer, samples, SAMPLE_RATE, format="WAV")
    return buffer.getvalue()


# ─── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def genai():
    return FakeGenaiClient()


class _GeminiWithFakeClient:
    """供應商「google」：建立的 Gemini 轉接器都接上同一個假用戶端，也不真的等。"""

    info = GeminiProvider.info

    def __init__(self, genai: FakeGenaiClient):
        self._genai = genai
        self.withdrawn: set[str] = set()
        """不再提供的模型，例如升級後從模型清單拿掉的。"""
        self.sleep = lambda seconds: None
        """轉接器等待（輪詢上傳檔、Flex 退避）時呼叫；預設不等。"""
        self.open_error: Exception | None = None
        """建立轉接器時拋的錯，例如金鑰無效時的 ValueError。"""

    def capabilities(self):
        return {model: capabilities for model, capabilities in GeminiProvider.capabilities().items()
                if model not in self.withdrawn}

    def __call__(self, model: str, api_key: str) -> GeminiProvider:
        if self.open_error is not None:
            raise self.open_error
        return GeminiProvider(model, api_key, client=self._genai, sleep=lambda s: self.sleep(s))


@pytest.fixture
def gemini(genai):
    provider = _GeminiWithFakeClient(genai)
    previous = registry.register("google", provider)
    yield provider
    registry.register("google", previous)


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


def transcribe(api: TestClient, run_mode, name: str, **fields) -> list[dict]:
    """上傳、送出單檔任務，收下所有廣播直到任務結束。file_uid 就是檔名。

    fields 是請求的其他欄位，例如提示詞。
    """
    response = api.post("/api/v1/upload", files={"file": (name, synthetic_audio(), "audio/wav")})
    assert response.status_code == 200, response.text

    with api.websocket_connect(f"/api/v1/ws/{name}") as ws:
        ws.send_json({"filename": response.json()["filename"], "original_filename": name,
                      "provider": "Google", "model": MODEL, "source_lang": "ja", **fields})
        messages = receive_until(ws, TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
    # 結束的廣播之後任務還在收尾（刪遠端檔就在這裡），等它整個跑完
    wait_until(lambda: not run_mode.is_alive(messages[-1]["task_uuid"]))
    return messages


def run_batch(api: TestClient, run_mode, batch_id: str, names: list[str],
              fields_per_file: dict[str, dict] | None = None, timeout: float = TIMEOUT,
              **fields) -> list[dict]:
    """上傳、送出批次，收下所有廣播直到批次結束。檔案的 file_uid 就是檔名。

    fields 是批次層級的其他欄位，fields_per_file 是個別檔案的欄位（以檔名為 key），
    例如提示詞。timeout 是每則廣播最多等幾秒。
    """
    files = []
    for name in names:
        response = api.post("/api/v1/upload", files={"file": (name, synthetic_audio(), "audio/wav")})
        assert response.status_code == 200, response.text
        files.append({"filename": response.json()["filename"], "original_filename": name,
                      "file_uid": name, **(fields_per_file or {}).get(name, {})})

    with api.websocket_connect(f"/api/v1/batch/ws/{batch_id}") as ws:
        ws.send_json({"files": files, "provider": "Google", "model": MODEL, "source_lang": "ja",
                      **fields})
        messages = receive_until(ws, TaskStatus.BATCH_COMPLETED, timeout=timeout)
    # 結束的廣播之後批次還在收尾。等它整個跑完再查 API：
    # 測試的 sqlite 只有一條連線，和 worker 同時用會互相蓋掉交易
    wait_until(lambda: not run_mode.is_alive(messages[-1]["task_uuid"]))
    return messages


def receive_until(ws, *end: TaskStatus, timeout: float = TIMEOUT) -> list[dict]:
    """收廣播直到收到其中一種結束狀態。

    等一則廣播超過 timeout 秒就斷言失敗，附上已經收到的廣播，不讓 CI 卡住。
    """
    messages = []
    while not messages or messages[-1]["status_code"] not in end:
        done, _ = wait([_reader.submit(ws.receive_json)], timeout=timeout)
        assert done, f"{timeout} 秒內沒有新的廣播，還沒收到 {'、'.join(end)}；已經收到：{messages}"
        messages.append(done.pop().result())
    return messages


def final_status(messages: list[dict]) -> dict[str, dict]:
    """每個檔案最後一則完成或失敗的廣播。"""
    return {m["file_uid"]: m for m in messages
            if m.get("file_uid") and m["status_code"] in (TaskStatus.COMPLETED, TaskStatus.FAILED)}


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
    response = api.post("/api/v1/upload", files={"file": (name, synthetic_audio(), "audio/wav")})
    with api.websocket_connect(f"/api/v1/ws/{name}") as ws:
        ws.send_json({"filename": response.json()["filename"], "original_filename": name,
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


def test_single_file_is_retried_after_a_transient_error(api, in_process_run_mode, genai):
    # 503 是暫時錯誤：分段轉錄不把它當成這一段失敗，交給執行模式重試整個任務
    genai.replies = [unavailable(), Reply(text="[00:01.00]おはよう。")]

    messages = transcribe(api, in_process_run_mode, "gemini-single-transient.wav")

    assert TaskStatus.FAILED not in [m["status_code"] for m in messages]
    assert messages[-1]["status_code"] == TaskStatus.COMPLETED
    assert "おはよう。" in messages[-1]["result"]["transcripts"]["srt"]
    assert history(api, "gemini-single-transient.wav")["status"] == TaskStatus.COMPLETED
    assert genai.stored == {}  # 兩次執行上傳的遠端檔都刪掉了


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
    # 整個任務合併完一個片段都沒有才算失敗，原因寫明。沒有內容不是轉錄失敗，檔案夠長也不切段重試
    # （重試的話會因為測試環境沒有 Silero 找不到切點，原因變成「無法分割音訊檔案」）
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "transcription_max_duration_seconds", 5)
    genai.replies = [Reply(text=""), Reply(text="這段聽不出任何語音。"), Reply(text="[00:01.00]")]

    end = transcribe(api, in_process_run_mode, "gemini-chunks-empty.wav")[-1]

    assert end["status_code"] == TaskStatus.FAILED
    assert "Gemini 的回應沒有任何帶時間戳的文字" in end["status_text"]
    assert "Gemini 的回應沒有任何帶時間戳的文字" in history(
        api, "gemini-chunks-empty.wav")["error_message"]


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


def test_batch_records_store_the_listed_provider_name(api, in_process_run_mode, genai, db_session):
    # run_batch 照舊前端的寫法送 Google；任務紀錄存的是供應商清單上的 google（#97）
    from app.repositories.transcription_log_repository import TranscriptionLogRepository

    genai.batch_outcomes = {0: Reply(text="[00:01.00]おはよう。")}
    run_batch(api, in_process_run_mode, "batch-gemini-spelling", ["gemini-spelling.wav"])

    task_uuid = history(api, "gemini-spelling.wav")["task_uuid"]
    db_session.expire_all()
    assert TranscriptionLogRepository().get(db_session, task_uuid).provider == "google"


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


def test_every_file_fails_when_the_provider_cannot_be_opened(
        api, in_process_run_mode, gemini, data_dir):
    # 開供應商時就失敗，這時還沒建立任務紀錄（#156）
    gemini.open_error = ValueError("API 金鑰無效")

    # 失敗得這麼早，廣播馬上就到：每則只等 5 秒，收不到就斷言失敗
    messages = run_batch(api, in_process_run_mode, "batch-gemini-bad-key",
                         ["gemini-bad-key-a.wav", "gemini-bad-key-b.wav"], timeout=5)

    # 畫面靠每個檔案自己的失敗廣播離開處理中，批次結束的廣播不會改檔案的狀態
    results = final_status(messages)
    assert {uid: m["status_code"] for uid, m in results.items()} == {
        "gemini-bad-key-a.wav": TaskStatus.FAILED, "gemini-bad-key-b.wav": TaskStatus.FAILED}
    assert all("API 金鑰無效" in m["status_text"] for m in results.values())
    assert [p.name for p in (data_dir / "temp_uploads").iterdir()] == []  # 上傳的暫存檔照樣清掉


def test_prompts_with_braces_reach_gemini_as_written(api, in_process_run_mode, genai):
    # 第一個檔案沿用批次的提示詞，第二個檔案有自己的提示詞（#143）
    own_prompt = "這一檔有兩位說話者，分別標成 {A} 與 {B}"

    messages = run_batch(api, in_process_run_mode, "batch-gemini-braces",
                         ["gemini-braces-a.wav", "gemini-braces-b.wav"],
                         fields_per_file={"gemini-braces-b.wav": {"prompt": own_prompt}},
                         prompt=JSON_PROMPT, source_lang="ja-JP")

    assert {uid: m["status_code"] for uid, m in final_status(messages).items()} == {
        "gemini-braces-a.wav": TaskStatus.COMPLETED, "gemini-braces-b.wav": TaskStatus.COMPLETED}
    assert genai.prompts == [JSON_PROMPT_SENT, own_prompt]


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
