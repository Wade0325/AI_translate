"""接縫 1：透過 API 跑完一個批次，只把供應商換成支援批次的假供應商（#115）。

批次裡每個音檔仍各是一個任務，走任務生命週期與語音視圖：和單檔任務一樣有任務紀錄、片段、計價
與狀態廣播。其他都走真的：TestClient、sqlite、行程內執行模式、WebSocket 狀態廣播，以及合成音檔
經真實的 ffmpeg 轉檔與去靜音。測試只從外部觀察：狀態廣播、API 回應、存下來的任務紀錄與片段、
可以下載的輸出格式與保留音檔、暫存資料夾裡還留著哪些檔案，以及假供應商收到了什麼。
"""
import threading
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.core.task_status import TaskStatus
from app.exceptions import TransientError
from app.runtime import run_mode
from tests.support.fake_provider import FAKE_MODEL, Fail
from tests.support.synthetic_audio import VOICED, synthetic_audio
from tests.support.waiting import wait_until

TIMEOUT = 30

LINES = [(0.2, 1.5, 0, "おはよう。"), (3.0, 3.6, 1, "こんにちは。"), (5.5, 6.2, 0, "またね。")]
"""送進假供應商的轉錄結果，時間軸是去靜音之後 7.2 秒的語音視圖（見 VOICED）。"""
RESTORED = [0.2, 1.5, 5.4, 6.0, 10.3, 11.0]
"""LINES 的起訖時間還原回原音檔：第二句在第二個有聲段、第三句在第三個。"""

NAMES = ["batch-a.wav", "batch-b.wav", "batch-c.wav"]


# ─── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def batch_fake(fake):
    """支援批次的假供應商。"""
    fake.model_capabilities = replace(fake.model_capabilities, supports_batch=True)
    return fake


# ─── helpers ─────────────────────────────────────────────────────────────────

_reader = ThreadPoolExecutor(max_workers=2)


def receive_until(ws, *end: TaskStatus) -> list[dict]:
    """收廣播直到收到其中一種結束狀態；等一則廣播超過 TIMEOUT 秒就斷言失敗，不讓 CI 卡住。"""
    messages = []
    while not messages or messages[-1]["status_code"] not in end:
        done, _ = wait([_reader.submit(ws.receive_json)], timeout=TIMEOUT)
        assert done, f"{TIMEOUT} 秒內沒有新的廣播，還沒收到 {'、'.join(end)}；已經收到：{messages}"
        messages.append(done.pop().result())
    return messages


def upload(api: TestClient, name: str, voiced=VOICED) -> str:
    response = api.post("/api/v1/upload", files={"file": (name, synthetic_audio(voiced=voiced),
                                                          "audio/wav")})
    assert response.status_code == 200, response.text
    return response.json()["filename"]


def batch_request(api: TestClient, names: list[str], voiced=VOICED,
                  fields_per_file: dict[str, dict] | None = None, **fields) -> dict:
    """上傳每個檔案，組出送給批次端點的請求；檔案的 file_uid 就是檔名。

    fields 是批次層級的欄位，fields_per_file 是個別檔案的欄位（以檔名為 key）。
    """
    files = [{"filename": upload(api, name, voiced), "original_filename": name, "file_uid": name,
              **(fields_per_file or {}).get(name, {})} for name in names]
    return {"files": files, "provider": "fake", "model": FAKE_MODEL, "source_lang": "ja",
            **fields}


def run_batch(api: TestClient, mode, batch_id: str, names: list[str], **request) -> list[dict]:
    """上傳、送出批次，收下所有廣播直到批次結束；request 見 :func:`batch_request`。"""
    payload = batch_request(api, names, **request)
    with api.websocket_connect(f"/api/v1/batch/ws/{batch_id}") as ws:
        ws.send_json(payload)
        messages = receive_until(ws, TaskStatus.BATCH_COMPLETED)
    # 結束的廣播之後批次還在收尾，等它整個跑完
    wait_until(lambda: not mode.is_alive(messages[-1]["task_uuid"]))
    return messages


def of_file(messages: list[dict], file_uid: str) -> list[dict]:
    """這個檔案的廣播。"""
    return [m for m in messages if m.get("file_uid") == file_uid]


def ends(messages: list[dict], names: list[str]) -> list[dict]:
    """每個檔案最後一則廣播（它的結果），依 names 的順序。"""
    return [of_file(messages, name)[-1] for name in names]


def codes(messages: list[dict]) -> list[str]:
    return [m["status_code"] for m in messages]


def flat_times(spans: list[dict]) -> list[float]:
    """片段的起訖時間依序攤平：[開始, 結束, 開始, 結束, …]。"""
    return [t for span in spans for t in (span["start"], span["end"])]


def transcribe_single(api: TestClient, file_uid: str, name: str) -> list[dict]:
    """同一個假供應商跑一個單檔任務，收下它的廣播直到結束。"""
    filename = upload(api, name)
    with api.websocket_connect(f"/api/v1/ws/{file_uid}") as ws:
        ws.send_json({"filename": filename, "original_filename": name, "provider": "fake",
                      "model": FAKE_MODEL, "source_lang": "ja"})
        return receive_until(ws, TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)


def stored_segments(api: TestClient, task_uuid: str) -> list[dict]:
    return api.get(f"/api/v1/transcripts/{task_uuid}").json()["segments"]


def record(api: TestClient, task_uuid: str) -> dict:
    return api.get(f"/api/v1/history/{task_uuid}").json()


def download(api: TestClient, task_uuid: str, fmt: str) -> str:
    response = api.get(f"/api/v1/history/{task_uuid}/download/{fmt}")
    assert response.status_code == 200
    return response.text


def leftovers(data_dir) -> list[str]:
    """暫存上傳資料夾裡還留著的檔案：上傳檔，以及去靜音產生的暫存檔。"""
    return sorted(p.name for p in (data_dir / "temp_uploads").iterdir())


# ─── 每個檔案都走任務生命週期 ───────────────────────────────────────────────

def test_each_of_three_files_has_segments_pricing_and_broadcasts(api, in_process_run_mode, batch_fake):
    # 按 token 計價（價目見 test_provider_seam.py 的計價測試，一次 0.30 美元），批次照設定打五折
    batch_fake.model_capabilities = replace(batch_fake.model_capabilities, pricing="per_token")
    batch_fake.usage = (200_000, 40_000)
    batch_fake.script = [[(0.2, 1.5, 0, "一つ目。")], [(0.2, 1.5, 1, "二つ目。")],
                         [(0.2, 1.5, 0, "三つ目。")]]

    messages = run_batch(api, in_process_run_mode, "batch-three", NAMES)

    for name, text in zip(NAMES, ["一つ目。", "二つ目。", "三つ目。"], strict=True):
        own = of_file(messages, name)
        # 和單檔任務一樣：處理中……之後才宣告完成，廣播帶著這個檔案自己的任務
        assert codes(own)[-1] == TaskStatus.COMPLETED
        assert set(codes(own)[:-1]) == {TaskStatus.PROCESSING}
        task_uuid = own[-1]["task_uuid"]
        assert {m["task_uuid"] for m in own} == {task_uuid}
        assert own[-1]["result"]["cost"] == pytest.approx(0.15)
        assert text in own[-1]["result"]["transcripts"]["srt"]
        assert [s["text"] for s in stored_segments(api, task_uuid)] == [text]
        saved = record(api, task_uuid)
        assert saved["status"] == TaskStatus.COMPLETED
        assert saved["is_batch"] is True
        assert (saved["total_tokens"], saved["cost"]) == (240_000, pytest.approx(0.15))
        assert saved["service_tier_used"] == "batch"
        assert saved["audio_duration_seconds"] == pytest.approx(12.0, abs=0.1)
    assert codes(messages)[-1] == TaskStatus.BATCH_COMPLETED


def test_a_file_ends_like_a_single_file_task(api, in_process_run_mode, batch_fake):
    # 同一段音檔、同一份轉錄結果：批次的檔案和單檔任務存下一樣的片段（時間都還原回原音檔），
    # 四種輸出格式下載到一樣的內容，也和完成時廣播的一樣；只有計價套用批次的折扣
    batch_fake.model_capabilities = replace(batch_fake.model_capabilities, pricing="per_token")
    batch_fake.usage = (200_000, 40_000)
    batch_fake.script = [list(LINES), list(LINES)]

    single = transcribe_single(api, "uid-like-single", "like-single.wav")[-1]
    batched = of_file(run_batch(api, in_process_run_mode, "batch-like-single", ["batched.wav"]),
                      "batched.wav")[-1]

    assert codes([single, batched]) == [TaskStatus.COMPLETED] * 2
    segments = stored_segments(api, batched["task_uuid"])
    assert segments == stored_segments(api, single["task_uuid"])
    assert flat_times(segments) == pytest.approx(RESTORED)
    for fmt in ("srt", "vtt", "lrc", "txt"):
        content = download(api, batched["task_uuid"], fmt)
        assert content == download(api, single["task_uuid"], fmt)
        assert content == batched["result"]["transcripts"][fmt]
    assert (single["result"]["cost"], batched["result"]["cost"]) == (
        pytest.approx(0.30), pytest.approx(0.15))


def test_a_failed_file_does_not_stop_the_others(api, in_process_run_mode, batch_fake):
    batch_fake.script = [[(0.2, 1.5, 0, "一つ目。")], Fail("音檔無法解碼"), [(0.2, 1.5, 0, "三つ目。")]]

    messages = run_batch(api, in_process_run_mode, "batch-partial", NAMES)

    # 只有那個檔案記成失敗並寫明原因，其他檔案照常完成
    first, failed, third = ends(messages, NAMES)
    assert codes([first, failed, third]) == [
        TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.COMPLETED]
    assert "音檔無法解碼" in failed["status_text"]
    saved = record(api, failed["task_uuid"])
    assert saved["status"] == TaskStatus.FAILED
    assert "音檔無法解碼" in saved["error_message"]
    assert stored_segments(api, failed["task_uuid"]) == []
    assert [s["text"] for s in stored_segments(api, third["task_uuid"])] == ["三つ目。"]


def test_records_store_the_listed_provider_name(api, in_process_run_mode, batch_fake, db_session):
    # 舊前端、直接呼叫 API 的人可能送大寫；任務紀錄存的是供應商清單上的名稱（#97）
    from app.repositories.transcription_log_repository import TranscriptionLogRepository

    batch_fake.script = [list(LINES)]
    end = of_file(run_batch(api, in_process_run_mode, "batch-spelling", ["spelling.wav"],
                            provider="FAKE"), "spelling.wav")[-1]

    db_session.expire_all()
    assert TranscriptionLogRepository().get(db_session, end["task_uuid"]).provider == "fake"


def test_prompts_reach_the_provider_as_written(api, in_process_run_mode, batch_fake):
    # 第一個檔案沿用批次的提示詞（變數照樣代入，JSON 的大括號原樣留著，#143），第二個檔案有自己的
    batch_fake.script = [list(LINES), list(LINES)]
    own_prompt = "這一檔有兩位說話者，分別標成 {A} 與 {B}"

    run_batch(api, in_process_run_mode, "batch-prompts", ["prompt-a.wav", "prompt-b.wav"],
              fields_per_file={"prompt-b.wav": {"prompt": own_prompt}},
              prompt='請轉錄{source_lang}音檔，每一行寫成 {"speaker": "S0", "text": "…"}',
              source_lang="ja-JP")

    assert batch_fake.prompts == [
        '請轉錄日文音檔，每一行寫成 {"speaker": "S0", "text": "…"}', own_prompt]


# ─── 語音視圖 ────────────────────────────────────────────────────────────────

MOSTLY_VOICED = [(0.0, 10.0), (11.5, 21.5)]
"""有聲 0–10、11.5–21.5 秒，中間靜音 1.5 秒：語音佔比約 96%，不低於門檻，不去靜音。"""


@pytest.mark.parametrize("voiced, remove_silence, sent, times", [
    (VOICED, True, 7.2, RESTORED),
    (MOSTLY_VOICED, True, 21.5, [0.2, 1.5, 3.0, 3.6, 5.5, 6.2]),
    (VOICED, False, 12.0, [0.2, 1.5, 3.0, 3.6, 5.5, 6.2]),
], ids=["mostly-silent", "mostly-speech", "model-keeps-silences"])
def test_files_are_sent_through_their_speech_view(
        api, in_process_run_mode, batch_fake, data_dir, voiced, remove_silence, sent, times):
    # 去靜音和單檔任務同一個入口：語音佔比低於門檻才剪掉靜音，模型能力說不剪的就不剪；
    # 時間只在剪過靜音時才還原。去靜音的暫存檔用完就清掉
    batch_fake.model_capabilities = replace(
        batch_fake.model_capabilities, remove_silence=remove_silence)
    batch_fake.script = [list(LINES)]

    batch_id = f"batch-speech-view-{sent}"
    end = of_file(run_batch(api, in_process_run_mode, batch_id, ["view.wav"], voiced=voiced),
                  "view.wav")[-1]

    assert batch_fake.durations == [pytest.approx(sent, abs=0.01)]
    assert flat_times(stored_segments(api, end["task_uuid"])) == pytest.approx(times)
    assert leftovers(data_dir) == []


# ─── 送出之前就失敗 ──────────────────────────────────────────────────────────

def test_every_file_fails_when_the_provider_cannot_be_opened(
        api, in_process_run_mode, batch_fake, data_dir):
    batch_fake.open_error = ValueError("API 金鑰無效")

    messages = run_batch(api, in_process_run_mode, "batch-bad-key", NAMES[:2])

    # 和單檔任務一樣有任務紀錄，記成失敗並寫明原因；畫面靠每個檔案自己的失敗廣播離開處理中
    for end in ends(messages, NAMES[:2]):
        assert end["status_code"] == TaskStatus.FAILED
        assert "API 金鑰無效" in end["status_text"]
        saved = record(api, end["task_uuid"])
        assert saved["status"] == TaskStatus.FAILED
        assert "API 金鑰無效" in saved["error_message"]
    assert batch_fake.calls == []
    assert leftovers(data_dir) == []


def test_a_file_that_cannot_be_uploaded_fails_alone(api, in_process_run_mode, batch_fake):
    batch_fake.upload_errors = [None, RuntimeError("讀不到檔案")]
    batch_fake.script = [[(0.2, 1.5, 0, "一つ目。")], [(0.2, 1.5, 0, "三つ目。")]]

    messages = run_batch(api, in_process_run_mode, "batch-upload-fails", NAMES)

    first, failed, third = ends(messages, NAMES)
    assert codes([first, failed, third]) == [
        TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.COMPLETED]
    assert "檔案上傳失敗: 讀不到檔案" in record(api, failed["task_uuid"])["error_message"]
    # 送出的只有上傳成功的兩個檔案，結果照它們送出的順序對回去
    assert len(batch_fake.prompts) == 2
    assert [s["text"] for s in stored_segments(api, third["task_uuid"])] == ["三つ目。"]


def test_every_file_fails_when_the_batch_cannot_be_submitted(api, in_process_run_mode, batch_fake):
    batch_fake.submit_errors = [RuntimeError("請求太大")]

    messages = run_batch(api, in_process_run_mode, "batch-not-submitted", NAMES[:2])

    for end in ends(messages, NAMES[:2]):
        assert end["status_code"] == TaskStatus.FAILED
        assert "送出批次失敗: 請求太大" in record(api, end["task_uuid"])["error_message"]
    assert TaskStatus.BATCH_SUBMITTED not in codes(messages)


def test_every_file_fails_when_the_whole_batch_fails(api, in_process_run_mode, batch_fake):
    batch_fake.script = [list(LINES), list(LINES)]
    batch_fake.batch_outcome = "EXPIRED"

    messages = run_batch(api, in_process_run_mode, "batch-expired", NAMES[:2])

    for end in ends(messages, NAMES[:2]):
        assert end["status_code"] == TaskStatus.FAILED
        assert "JOB_STATE_EXPIRED" in record(api, end["task_uuid"])["error_message"]
    assert "JOB_STATE_EXPIRED" in messages[-1]["status_text"]


# ─── 暫時錯誤 ────────────────────────────────────────────────────────────────

def transient() -> TransientError:
    return TransientError("503 服務暫時無法使用", reason="503 UNAVAILABLE")


@pytest.mark.parametrize("step, notice", [
    ("upload_errors", "上傳 transient.wav 遇到暫時錯誤（503 UNAVAILABLE），0.01 秒後第 1 次重試"),
    ("submit_errors", "送出批次遇到暫時錯誤（503 UNAVAILABLE），0.01 秒後第 1 次重試"),
    ("batch_polls", "查詢批次狀態遇到暫時錯誤（503 UNAVAILABLE），0.01 秒後第 1 次重試"),
])
def test_a_transient_error_is_retried_where_it_happened(
        api, in_process_run_mode, batch_fake, quick_transient_retries, step, notice):
    # 暫時錯誤（429、503）：先廣播，等一段時間（這裡調成 0.01 秒）再做一次出錯的那一步，其他步驟不重做
    batch_fake.script = [list(LINES)]
    getattr(batch_fake, step).append(transient())

    messages = run_batch(api, in_process_run_mode, f"batch-transient-{step}", ["transient.wav"])

    assert of_file(messages, "transient.wav")[-1]["status_code"] == TaskStatus.COMPLETED
    assert any(m["status_text"].startswith(notice) for m in messages)
    assert len(batch_fake.calls) == (2 if step == "upload_errors" else 1)
    assert len(batch_fake.submitted) == 1


def test_polling_that_keeps_failing_ends_the_files_as_failed(
        api, in_process_run_mode, batch_fake, quick_transient_retries):
    # 查詢一直遇到暫時錯誤：重試 3 次之後輪詢中斷，檔案記成失敗（之後還能從復原入口取回）
    batch_fake.script = [list(LINES)]
    batch_fake.batch_polls = [transient() for _ in range(4)]

    messages = run_batch(api, in_process_run_mode, "batch-transient-out", ["gives-up.wav"])

    end = of_file(messages, "gives-up.wav")[-1]
    assert end["status_code"] == TaskStatus.FAILED
    assert "查詢批次狀態失敗" in record(api, end["task_uuid"])["error_message"]


# ─── 復原 ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("model_withdrawn", [False, True], ids=["model-offered", "model-withdrawn"])
def test_recover_ends_files_on_the_original_timeline(
        api, in_process_run_mode, batch_fake, model_withdrawn):
    batch_id, name = f"batch-recover-{model_withdrawn}", f"recover-{model_withdrawn}.wav"
    # 查詢批次狀態失敗：這一次的執行到此中斷，檔案記成失敗，批次在供應商那邊照樣跑完
    batch_fake.batch_polls = [RuntimeError("連線中斷")]
    batch_fake.script = [list(LINES)]
    first_end = of_file(run_batch(api, in_process_run_mode, batch_id, [name]), name)[-1]
    assert first_end["status_code"] == TaskStatus.FAILED
    if model_withdrawn:
        # 批次還在跑的時候升級，新版的模型清單拿掉了送出時的模型
        batch_fake.withdrawn = True

    # 從復原入口接著結束：進度一樣廣播給這個批次
    with api.websocket_connect(f"/api/v1/batch/ws/{batch_id}") as ws:
        response = api.post(f"/api/v1/batch/{batch_id}/recover", json={"api_keys": "test-key"})
        assert response.status_code == 200, response.text
        recovered = of_file(receive_until(ws, TaskStatus.BATCH_COMPLETED), name)[-1]
    in_process_run_mode.close(wait=True)  # 等復原整個跑完再查 API

    # 同一個任務記成完成；去靜音過的檔案，片段的時間還原回原音檔，和沒中斷時一樣
    assert recovered["status_code"] == TaskStatus.COMPLETED
    assert recovered["task_uuid"] == first_end["task_uuid"]
    assert record(api, recovered["task_uuid"])["status"] == TaskStatus.COMPLETED
    assert flat_times(stored_segments(api, recovered["task_uuid"])) == pytest.approx(RESTORED)
    # 之後再取回結果，直接從批次紀錄讀出完成時的結果
    again = api.post(f"/api/v1/batch/{batch_id}/recover", json={"api_keys": "test-key"}).json()
    assert [(f["file_uid"], f["status"]) for f in again["files"]] == [(name, TaskStatus.COMPLETED)]
    assert again["files"][0]["result"]["transcripts"] == recovered["result"]["transcripts"]


# ─── 收尾 ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("retain_audio", [True, False], ids=["retain", "no-retain"])
def test_audio_is_retained_and_nothing_is_left_behind(
        api, in_process_run_mode, batch_fake, monkeypatch, data_dir, retain_audio):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "retain_audio", retain_audio)
    batch_fake.script = [list(LINES), Fail("音檔無法解碼")]

    messages = run_batch(api, in_process_run_mode, f"batch-finishing-{retain_audio}", NAMES[:2])

    # 完成與失敗的檔案都照保留設定處理上傳檔，暫存區不留任何檔案；送給供應商的資源也釋放了
    for end in ends(messages, NAMES[:2]):
        audio = api.get(f"/api/v1/transcripts/{end['task_uuid']}/audio")
        if retain_audio:
            assert audio.content == synthetic_audio()
        else:
            assert audio.status_code == 404
    assert leftovers(data_dir) == []
    assert batch_fake.released == 1


class SubmissionsSeen:
    """記下派送出去的批次，其餘照轉；用 ``run_mode.use`` 換上。"""

    def __init__(self, inner):
        self._inner = inner
        self.batches = 0

    def submit_batch(self, task_params_dict):
        task_id = self._inner.submit_batch(task_params_dict)
        self.batches += 1
        return task_id

    def __getattr__(self, name):
        return getattr(self._inner, name)


def test_a_batch_still_queued_when_the_app_closes_is_recorded_as_failed(
        api, in_process_run_mode, batch_fake, data_dir):
    # 執行緒池只有一個 worker：第一個批次停在上傳，第二個批次排在佇列裡
    batch_fake.hold = threading.Event()
    batch_fake.script = [list(LINES)]
    seen = SubmissionsSeen(run_mode.get())
    previous = run_mode.use(seen)
    try:
        with api.websocket_connect("/api/v1/batch/ws/batch-running") as running, \
                api.websocket_connect("/api/v1/batch/ws/batch-waiting") as waiting:
            running.send_json(batch_request(api, ["running.wav"]))
            assert batch_fake.started.wait(TIMEOUT)
            waiting.send_json(batch_request(api, ["waiting-at-close.wav"]))
            wait_until(lambda: seen.batches == 2)
            # 應用程式關閉（lifespan 關掉執行模式）：還在排隊的批次不會再執行
            in_process_run_mode.close()
            batch_fake.hold.set()
            receive_until(running, TaskStatus.BATCH_COMPLETED)
    finally:
        run_mode.use(previous)
    in_process_run_mode.close(wait=True)

    # 和單檔任務一樣：每個檔案都有任務紀錄，記成失敗並寫明原因，上傳檔照保留設定處理
    [listed] = api.get("/api/v1/history",
                       params={"keyword": "waiting-at-close.wav"}).json()["items"]
    saved = record(api, listed["task_uuid"])
    assert saved["status"] == TaskStatus.FAILED
    assert "關閉" in saved["error_message"]
    assert saved["is_batch"] is True
    assert api.get(f"/api/v1/transcripts/{listed['task_uuid']}/audio").content == synthetic_audio()
    assert leftovers(data_dir) == []
    assert len(batch_fake.calls) == 1
