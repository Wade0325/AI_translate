"""接縫 1：透過 API 跑完一個批次，只把供應商換成支援批次的假供應商（#115、#116）。

批次裡每個音檔仍各是一個任務，走任務生命週期與語音視圖：和單檔任務一樣有任務紀錄、片段、計價
與狀態廣播。批次本身是一個狀態機，執行與復原是它的兩個入口；每個檔案在 batch_files 資料表各一列。
其他都走真的：TestClient、sqlite、行程內執行模式、WebSocket 狀態廣播，以及合成音檔經真實的 ffmpeg
轉檔與去靜音。測試只從外部觀察：狀態廣播、API 回應、存下來的任務紀錄與片段、可以下載的輸出格式與
保留音檔、暫存資料夾裡還留著哪些檔案、假供應商收到了什麼，以及批次存進資料庫的樣子。
"""
import threading
from contextlib import ExitStack
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.core.default_prompt import build_prompt
from app.core.error_codes import ErrorCode
from app.core.task_status import TaskStatus
from app.exceptions import TransientError
from app.runtime import run_mode
from app.tasks import batch_core
from tests.support.db_faults import NOT_NULL, assert_logged_without, rejected_row, writes_fail
from tests.support.fake_provider import FAKE_MODEL, Fail, Restart
from tests.support.older_batches import (
    SPANS,
    OlderFile,
    finished_by_previous_release,
    sent_between_115_and_116,
    sent_by_previous_release,
    start_this_version,
    unreadable_older_batch,
)
from tests.support.synthetic_audio import VOICED, synthetic_audio
from tests.support.task_api import (
    download,
    file_results,
    flat_times,
    last_heard,
    leftovers,
    listed,
    listed_batch_ids,
    ping,
    receive,
    receive_until,
    shown,
    stored_segments,
    upload,
)
from tests.support.waiting import TIMEOUT, wait_until

LINES = [(0.2, 1.5, 0, "おはよう。"), (3.0, 3.6, 1, "こんにちは。"), (5.5, 6.2, 0, "またね。")]
"""送進假供應商的轉錄結果，時間軸是去靜音之後 7.2 秒的語音視圖（見 VOICED）。"""
RESTORED = [0.2, 1.5, 5.4, 6.0, 10.3, 11.0]
"""LINES 的起訖時間還原回原音檔：第二句在第二個有聲段、第三句在第三個。"""

NAMES = ["batch-a.wav", "batch-b.wav", "batch-c.wav"]


# 恢復批次的請求不帶金鑰：後端從資料庫取，請求帶明文會被拒收（#16 Q8b）
pytestmark = pytest.mark.usefixtures("google_key")


# ─── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def batch_fake(fake):
    """支援批次的假供應商。"""
    fake.model_capabilities = replace(fake.model_capabilities, supports_batch=True)
    return fake


@pytest.fixture
def quick_polls(monkeypatch):
    """送出之後第一次只等 0.01 秒就查（之後照樣每次多等一半）：測試不必真的等。"""
    monkeypatch.setattr(batch_core, "FIRST_POLL_SECONDS", 0.01)


@pytest.fixture
def no_google_key(db_session):
    """資料庫裡沒有 Google 金鑰（使用者還沒到 Settings 設定）；測試結束後還原。"""
    from sqlalchemy import func

    from app.database.models import ModelConfiguration

    rows = db_session.query(ModelConfiguration).filter(
        func.lower(ModelConfiguration.provider) == "google").all()
    saved = [(row, row.api_keys) for row in rows]
    for row in rows:
        row.api_keys = "[]"
    db_session.commit()
    yield
    for row, keys in saved:
        row.api_keys = keys
    db_session.commit()


# ─── helpers ─────────────────────────────────────────────────────────────────

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
    return _batch_until(api, mode, batch_id, names, TaskStatus.BATCH_COMPLETED, **request)


def submit_batch(api: TestClient, mode, batch_id: str, names: list[str], **request) -> list[dict]:
    """上傳、送出批次，收下廣播直到送出給供應商，再等這次執行停下來（例如中途重啟了）。"""
    return _batch_until(api, mode, batch_id, names, TaskStatus.BATCH_SUBMITTED, **request)


def _batch_until(api: TestClient, mode, batch_id: str, names: list[str], until: TaskStatus,
                 **request) -> list[dict]:
    payload = batch_request(api, names, **request)
    with api.websocket_connect(f"/api/v1/batch/ws/{batch_id}") as ws:
        ws.send_json(payload)
        messages = receive_until(ws, until)
    # 這則廣播之後批次的這次執行還在跑（收尾、或接著輪詢），等它整個停下來
    wait_until(lambda: not mode.is_alive(messages[-1]["task_uuid"]))
    return messages


def recover(api: TestClient, batch_id: str) -> list[dict]:
    """從復原入口接著結束批次，收下廣播直到批次結束。"""
    with api.websocket_connect(f"/api/v1/batch/ws/{batch_id}") as ws:
        response = api.post(f"/api/v1/batch/{batch_id}/recover", json={})
        assert response.status_code == 200, response.text
        return receive_until(ws, TaskStatus.BATCH_COMPLETED)


def of_file(messages: list[dict], file_uid: str) -> list[dict]:
    """這個檔案的廣播。"""
    return [m for m in messages if m.get("file_uid") == file_uid]


def ends(messages: list[dict], names: list[str]) -> list[dict]:
    """每個檔案的結果（最後一則完成或失敗的廣播），依 names 的順序。"""
    results = file_results(messages)
    return [results[name] for name in names]


def codes(messages: list[dict]) -> list[str]:
    return [m["status_code"] for m in messages]


def transcribe_single(api: TestClient, file_uid: str, name: str) -> list[dict]:
    """同一個假供應商跑一個單檔任務，收下它的廣播直到結束。"""
    filename = upload(api, name)
    with api.websocket_connect(f"/api/v1/ws/{file_uid}") as ws:
        ws.send_json({"filename": filename, "original_filename": name, "provider": "fake",
                      "model": FAKE_MODEL, "source_lang": "ja"})
        return receive_until(ws, TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)


def record(api: TestClient, task_uuid: str) -> dict:
    return api.get(f"/api/v1/history/{task_uuid}").json()


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
    # 說話者人數從存下來的片段算（S0、S1），和單檔任務完成時廣播的一樣
    assert (single["result"]["speaker_count"], batched["result"]["speaker_count"]) == (2, 2)


def test_a_chinese_file_is_stored_in_traditional_like_a_single_file_task(
        api, in_process_run_mode, batch_fake):
    # 批次的檔案和單檔任務一樣在完成時轉成繁體輸出（#14）；語言看每個檔案自己的
    batch_fake.script = [[(0.2, 1.5, 0, "我们开会。")], [(0.2, 1.5, 0, "我们开会。")]]
    names = ["batch-zh.wav", "batch-ja.wav"]

    messages = run_batch(api, in_process_run_mode, "batch-traditional", names,
                         fields_per_file={"batch-zh.wav": {"source_lang": "zh-TW"}})

    zh, ja = ends(messages, names)
    assert [s["text"] for s in stored_segments(api, zh["task_uuid"])] == ["我們開會。"]
    assert "我們開會。" in download(api, zh["task_uuid"], "lrc")
    assert [s["text"] for s in stored_segments(api, ja["task_uuid"])] == ["我们开会。"]


MULTI_SPEAKER_NAMES = ["labelled.wav", "unlabelled.wav"]
MULTI_SPEAKER_REQUEST = {"multi_speaker": True,
                         "fields_per_file": {"unlabelled.wav": {"multi_speaker": False}}}
"""批次層級開著 Multi-Speaker，第二個檔案在每檔設定裡關掉。"""


def test_each_file_follows_its_own_multi_speaker_switch(api, in_process_run_mode, batch_fake):
    # 個別檔案的設定優先，沒設定的用批次的（#13 Q1）：完成時廣播的與下載的輸出格式照各自的開關
    # 帶或不帶說話者標記；關掉的檔案，片段照樣存說話者編號
    batch_fake.script = [[(0.2, 1.5, 1, "一つ目。")], [(0.2, 1.5, 1, "二つ目。")]]

    messages = run_batch(api, in_process_run_mode, "batch-multi-speaker", MULTI_SPEAKER_NAMES,
                         **MULTI_SPEAKER_REQUEST)

    labelled, unlabelled = ends(messages, MULTI_SPEAKER_NAMES)
    assert download(api, labelled["task_uuid"], "txt") == "[S1] 一つ目。"
    assert download(api, unlabelled["task_uuid"], "txt") == "二つ目。"
    for end in (labelled, unlabelled):
        for fmt in ("srt", "vtt", "lrc", "txt"):
            assert end["result"]["transcripts"][fmt] == download(api, end["task_uuid"], fmt)
    assert [s["speaker"] for s in stored_segments(api, unlabelled["task_uuid"])] == ["S1"]


def test_files_finished_from_recovery_keep_their_multi_speaker_switch(
        api, in_process_run_mode, batch_fake):
    # 輪詢時應用程式重啟，之後從復原入口接回每個檔案的任務：開關從任務紀錄讀回來，不會變成預設
    batch_fake.script = [[(0.2, 1.5, 1, "一つ目。")], [(0.2, 1.5, 1, "二つ目。")]]
    batch_fake.batch_polls = [Restart()]
    submit_batch(api, in_process_run_mode, "batch-multi-speaker-restarted", MULTI_SPEAKER_NAMES,
                 **MULTI_SPEAKER_REQUEST)

    recovered = ends(recover(api, "batch-multi-speaker-restarted"), MULTI_SPEAKER_NAMES)
    in_process_run_mode.close(wait=True)  # 等復原整個跑完再查 API

    assert [end["result"]["transcripts"]["txt"] for end in recovered] == ["[S1] 一つ目。", "二つ目。"]
    assert [download(api, end["task_uuid"], "txt") for end in recovered] == [
        "[S1] 一つ目。", "二つ目。"]


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


def test_a_failed_file_is_still_billed_at_the_batch_discount(api, in_process_run_mode, batch_fake):
    # 供應商回報這個請求失敗（例如 Gemini 的回應被阻擋），照樣收費：用量記在失敗的任務紀錄上，和
    # 完成的檔案一樣打批次的折扣（#155；價目見 test_provider_seam.py 的計價測試，一次 0.30 美元）
    batch_fake.model_capabilities = replace(batch_fake.model_capabilities, pricing="per_token")
    batch_fake.usage = (200_000, 40_000)
    batch_fake.script = [Fail("回應被阻擋")]

    [failed] = ends(run_batch(api, in_process_run_mode, "batch-failed-billed", ["billed.wav"]),
                    ["billed.wav"])

    assert failed["status_code"] == TaskStatus.FAILED
    saved = record(api, failed["task_uuid"])
    assert saved["status"] == TaskStatus.FAILED
    assert (saved["total_tokens"], saved["cost"]) == (240_000, pytest.approx(0.15))
    assert saved["service_tier_used"] == "batch"


@pytest.mark.parametrize("entry", ["run", "recovery"])
def test_a_result_that_cannot_be_placed_on_the_original_audio_is_still_billed(
        api, in_process_run_mode, batch_fake, entry):
    # 供應商回應成功、回報了用量，片段卻放不回原音檔的時間軸（這裡是開始時間不是數字，#197）：這個
    # 檔案照失敗結束，同一批的其他檔案照常完成。供應商照樣收費：用量記在失敗的任務紀錄上，和完成的
    # 檔案一樣打批次的折扣（價目同上）。執行與復原（在輪詢時重啟之後）都一樣
    batch_fake.model_capabilities = replace(batch_fake.model_capabilities, pricing="per_token")
    batch_fake.usage = (200_000, 40_000)
    batch_fake.script = [[("0:00.2", 1.5, 0, "おはよう。")], list(LINES)]
    batch_id = f"batch-unplaced-{entry}"
    if entry == "run":
        messages = run_batch(api, in_process_run_mode, batch_id, NAMES[:2])
    else:
        batch_fake.batch_polls = [Restart()]
        submit_batch(api, in_process_run_mode, batch_id, NAMES[:2])
        messages = recover(api, batch_id)

    unplaced, other = ends(messages, NAMES[:2])
    assert codes([unplaced, other]) == [TaskStatus.FAILED, TaskStatus.COMPLETED]
    saved = record(api, unplaced["task_uuid"])
    assert saved["status"] == TaskStatus.FAILED
    assert "結果放不回原音檔的時間軸" in saved["error_message"]
    assert (saved["total_tokens"], saved["cost"]) == (240_000, pytest.approx(0.15))
    assert saved["service_tier_used"] == "batch"
    assert saved["audio_duration_seconds"] == pytest.approx(12.0, abs=0.1)


def test_records_store_the_listed_provider_name(api, in_process_run_mode, batch_fake, db_session):
    # 舊前端、直接呼叫 API 的人可能送大寫；任務紀錄存的是供應商清單上的名稱（#97）
    from app.repositories.transcription_log_repository import TranscriptionLogRepository

    batch_fake.script = [list(LINES)]
    end = of_file(run_batch(api, in_process_run_mode, "batch-spelling", ["spelling.wav"],
                            provider="FAKE"), "spelling.wav")[-1]

    db_session.expire_all()
    assert TranscriptionLogRepository().get(db_session, end["task_uuid"]).provider == "fake"


def test_each_file_sends_the_saved_template_and_its_supplement(
        api, in_process_run_mode, batch_fake, saved_prompt_template):
    # 和單檔任務同一個規則（#144）：設定頁存的範本（變數照樣代入，JSON 的大括號原樣留著，#143），
    # 空一行接上這個檔案的補充說明：自己的，沒有就用批次層級的；補充說明照寫的送出
    saved_prompt_template("fake", '請轉錄{source_lang}音檔，每一行寫成 {"speaker": "S0", "text": "…"}')
    batch_fake.script = [list(LINES), list(LINES), list(LINES)]
    own_prompt = "這一檔有兩位說話者，分別標成 {A} 與 {B}"

    run_batch(api, in_process_run_mode, "batch-prompts", ["prompt-a.wav", "prompt-b.wav"],
              fields_per_file={"prompt-b.wav": {"prompt": own_prompt}},
              prompt="人名照寫：佐藤", source_lang="ja-JP")
    run_batch(api, in_process_run_mode, "batch-template-alone", ["prompt-c.wav"],
              source_lang="ja-JP")

    template = '請轉錄日文音檔，每一行寫成 {"speaker": "S0", "text": "…"}'
    assert batch_fake.prompts == [
        template + "\n\n人名照寫：佐藤", template + "\n\n" + own_prompt, template]


def test_supplement_is_sent_after_the_built_in_template(api, in_process_run_mode, batch_fake):
    # 設定頁沒存過範本：系統內建範本裡要求 LRC 與時間戳的指示照樣送出，補充說明接在最後
    batch_fake.script = [list(LINES)]

    run_batch(api, in_process_run_mode, "batch-built-in-template", ["prompt-d.wav"],
              fields_per_file={"prompt-d.wav": {"prompt": "說話者是兩位主持人"}},
              source_lang="ja-JP")

    assert batch_fake.prompts == [build_prompt(source_lang="ja-JP") + "\n\n說話者是兩位主持人"]


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


def test_a_file_whose_upload_is_gone_fails_alone(api, in_process_run_mode, batch_fake):
    # 第二個檔案送出的檔名在上傳資料夾裡找不到，和上傳檔已經被清掃掉一樣（#153）
    batch_fake.script = [[(0.2, 1.5, 0, "一つ目。")], [(0.2, 1.5, 0, "三つ目。")]]

    messages = run_batch(api, in_process_run_mode, "batch-upload-gone", NAMES,
                         fields_per_file={NAMES[1]: {"filename": "swept-away.wav"}})

    # 只有那個檔案失敗並說明原因，使用者才知道它沒有送出；其他檔案照常送出
    first, gone, third = ends(messages, NAMES)
    assert codes([first, gone, third]) == [
        TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.COMPLETED]
    assert "找不到上傳的檔案" in gone["status_text"]
    assert len(batch_fake.prompts) == 2
    assert [s["text"] for s in stored_segments(api, third["task_uuid"])] == ["三つ目。"]


def test_a_batch_whose_uploads_are_all_gone_is_not_sent(api, batch_fake):
    names = NAMES[:2]
    with api.websocket_connect("/api/v1/batch/ws/batch-all-gone") as ws:
        ws.send_json({
            "files": [{"filename": f"swept-{name}", "original_filename": name, "file_uid": name}
                      for name in names],
            "provider": "fake", "model": FAKE_MODEL, "source_lang": "ja"})
        messages = [receive(ws) for _ in names]

    # 每個檔案都失敗並說明原因；沒有檔案可以送出，整批不派送
    assert [(m["file_uid"], m["status_code"]) for m in messages] == [
        (name, TaskStatus.FAILED) for name in names]
    assert all("找不到上傳的檔案" in m["status_text"] for m in messages)
    assert "batch-all-gone" not in listed_batch_ids(api)
    assert batch_fake.opened == 0


def test_every_file_fails_when_the_batch_cannot_be_submitted(api, in_process_run_mode, batch_fake):
    batch_fake.submit_errors = [RuntimeError("請求太大")]

    messages = run_batch(api, in_process_run_mode, "batch-not-submitted", NAMES[:2])

    for end in ends(messages, NAMES[:2]):
        assert end["status_code"] == TaskStatus.FAILED
        assert "送出批次失敗: 請求太大" in record(api, end["task_uuid"])["error_message"]
    assert TaskStatus.BATCH_SUBMITTED not in codes(messages)


def test_a_file_without_a_result_fails_instead_of_staying_in_progress(
        api, in_process_run_mode, batch_fake):
    # 批次成功結束，供應商卻少給了最後一個檔案的結果：那個檔案記成失敗，不停在處理中
    batch_fake.script = [list(LINES), list(LINES)]
    batch_fake.missing_results = 1

    messages = run_batch(api, in_process_run_mode, "batch-missing-result", NAMES[:2])

    first, missing = ends(messages, NAMES[:2])
    assert codes([first, missing]) == [TaskStatus.COMPLETED, TaskStatus.FAILED]
    assert "沒有回傳這個檔案的結果" in record(api, missing["task_uuid"])["error_message"]


def test_database_errors_are_not_passed_on(api, in_process_run_mode, batch_fake, app_log):
    # 批次紀錄寫不進資料庫（這裡是同一個批次 id 又送了一次）：每個檔案照樣結束，畫面與 log 都不轉述
    # 資料庫的例外，例外裡有 SQL 原文（ADR-0005）
    batch_fake.script = [list(LINES)]
    run_batch(api, in_process_run_mode, "batch-twice", ["twice-a.wav"])

    messages = run_batch(api, in_process_run_mode, "batch-twice", ["twice-b.wav"])

    end = of_file(messages, "twice-b.wav")[-1]
    assert end["status_code"] == TaskStatus.FAILED
    # 畫面照錯誤碼說「轉錄結果沒有存進資料庫」；細節是空的，原因只記在 log
    assert (end["error_code"], end["error_message"]) == (ErrorCode.DATABASE, None)
    assert "資料庫出錯了" in messages[-1]["status_text"]
    assert not any("INSERT" in m["status_text"] for m in messages)
    assert not any("INSERT INTO" in entry for entry in app_log)


@pytest.mark.parametrize("entry", ["run", "recovery"])
def test_a_file_whose_result_cannot_be_stored_fails_alone_without_passing_on_the_row(
        api, in_process_run_mode, batch_fake, test_engine, app_log, entry):
    # 一個檔案的片段寫不進資料庫，Postgres 附上的那一列有轉錄結果（#175、#178）：只有這個檔案失敗，
    # 同一批的其他檔案照常完成。畫面、任務紀錄與 log 都不轉述資料庫的例外。執行與復原（在輪詢時重啟
    # 之後）都一樣
    secret = "来期の人事はまだ内密に。"
    batch_id = f"batch-secret-row-{entry}"
    batch_fake.script = [list(LINES), [(0.2, 1.5, 0, secret)], list(LINES)]
    if entry == "recovery":
        batch_fake.batch_polls = [Restart()]
        submit_batch(api, in_process_run_mode, batch_id, NAMES)
    row = rejected_row("transcript_segments", f"1, 0f5c, 0-0, 0, 0.2, 1.5, S0, {secret}")
    with writes_fail(test_engine, "transcript_segments", "INSERT", row,
                     when="NEW.text LIKE '%内密%'"):
        if entry == "run":
            messages = run_batch(api, in_process_run_mode, batch_id, NAMES)
        else:
            messages = recover(api, batch_id)
            in_process_run_mode.close(wait=True)  # 等復原整個跑完再拿掉 trigger

    first, failed, third = ends(messages, NAMES)
    assert codes([first, failed, third]) == [
        TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.COMPLETED]
    assert (failed["error_code"], failed["error_message"]) == (ErrorCode.DATABASE, None)
    saved = record(api, failed["task_uuid"])
    assert (saved["error_code"], saved["error_message"]) == (ErrorCode.DATABASE, None)
    shown = [m["status_text"] for m in messages]
    for text in shown:
        for leaked in (secret, NOT_NULL, "INSERT"):
            assert leaked not in text
    assert_logged_without(app_log, secret)


@pytest.mark.parametrize("entry", ["run", "recovery"])
def test_a_batch_that_cannot_be_recorded_as_completed_keeps_its_files_without_passing_on_the_row(
        api, in_process_run_mode, batch_fake, test_engine, app_log, entry):
    # 檔案都完成了，批次卻記不成完成，Postgres 附上的那一列有原始檔名與轉錄結果（#175、#178）：
    # 完成的檔案照樣完成。批次的訊息說資料庫出錯，不說成沒有轉錄結果，也不轉述資料庫的例外。執行
    # 時批次記成失敗；復原時退回輪詢中，之後可以再按「恢復」
    filename, secret = "社長との面談_極秘.wav", "来期の人事はまだ内密に。"
    batch_id = f"batch-end-unrecorded-{entry}"
    batch_fake.script = [list(LINES), list(LINES)]
    if entry == "recovery":
        batch_fake.batch_polls = [Restart()]
        submit_batch(api, in_process_run_mode, batch_id, NAMES[:2])
    row = rejected_row("batch_jobs", f'{batch_id}, null, batches/1, COMPLETED, '
                                     f'{{"original_filename": "{filename}"}}, {{"text": "{secret}"}}')
    with writes_fail(test_engine, "batch_jobs", "UPDATE", row, when="NEW.status = 'COMPLETED'"):
        if entry == "run":
            messages = run_batch(api, in_process_run_mode, batch_id, NAMES[:2])
        else:
            messages = recover(api, batch_id)
            in_process_run_mode.close(wait=True)  # 等復原整個跑完再拿掉 trigger

    assert codes(ends(messages, NAMES[:2])) == [TaskStatus.COMPLETED, TaskStatus.COMPLETED]
    assert messages[-1]["status_code"] == TaskStatus.BATCH_COMPLETED
    assert "資料庫出錯了" in messages[-1]["status_text"]
    assert "轉錄結果沒有存進資料庫" not in messages[-1]["status_text"]
    assert listed(api, batch_id)["status"] == ("FAILED" if entry == "run" else "POLLING")
    for text in [m["status_text"] for m in messages]:
        for leaked in (filename, secret, NOT_NULL, "UPDATE", "batch_jobs"):
            assert leaked not in text
    assert_logged_without(app_log, filename, secret)


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
    ("upload_errors", "上傳 (1/1) 遇到暫時錯誤（503 UNAVAILABLE），0.01 秒後第 1 次重試"),
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


def test_submitting_that_keeps_hitting_transient_errors_fails_every_file(
        api, in_process_run_mode, batch_fake, data_dir, quick_transient_retries):
    # 送出一直遇到暫時錯誤（#164）：重試 3 次之後每個檔案都記成失敗、批次結束，暫存區不留檔；
    # 執行模式也不重跑整個批次
    batch_fake.submit_errors = [transient() for _ in range(4)]

    messages = run_batch(api, in_process_run_mode, "batch-submit-gives-up", NAMES[:2])

    for end in ends(messages, NAMES[:2]):
        assert end["status_code"] == TaskStatus.FAILED
        assert "送出批次失敗" in record(api, end["task_uuid"])["error_message"]
    assert messages[-1]["status_code"] == TaskStatus.BATCH_COMPLETED
    assert len(batch_fake.calls) == 2  # 每個檔案只上傳一次
    assert leftovers(data_dir) == []


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
        response = api.post(f"/api/v1/batch/{batch_id}/recover", json={})
        assert response.status_code == 200, response.text
        recovered = of_file(receive_until(ws, TaskStatus.BATCH_COMPLETED), name)[-1]
    in_process_run_mode.close(wait=True)  # 等復原整個跑完再查 API

    # 同一個任務記成完成；去靜音過的檔案，片段的時間還原回原音檔，和沒中斷時一樣
    assert recovered["status_code"] == TaskStatus.COMPLETED
    assert recovered["task_uuid"] == first_end["task_uuid"]
    assert record(api, recovered["task_uuid"])["status"] == TaskStatus.COMPLETED
    assert flat_times(stored_segments(api, recovered["task_uuid"])) == pytest.approx(RESTORED)
    # 之後再取回結果，和完成時廣播的結果相同（從任務紀錄與片段讀出，不再去問供應商）
    polls = batch_fake.polls
    again = api.post(f"/api/v1/batch/{batch_id}/recover", json={}).json()
    assert [(f["file_uid"], f["status"]) for f in again["files"]] == [(name, TaskStatus.COMPLETED)]
    assert again["files"][0]["result"] == recovered["result"]
    assert batch_fake.polls == polls
    assert listed(api, batch_id)["status"] == "RETRIEVED"


RECORD_FIELDS = ("status", "error_message", "is_batch", "model_used", "source_language",
                 "audio_duration_seconds", "total_tokens", "cost", "service_tier_used")
"""任務紀錄裡和結果有關的欄位：同一份劇本跑出來應該相同（處理時間、檔名與 id 不在裡面）。"""


def without_task_uuid(result: dict) -> dict:
    return {key: value for key, value in result.items() if key != "task_uuid"}


def test_a_restart_while_polling_is_finished_from_recovery_as_if_never_interrupted(
        api, in_process_run_mode, batch_fake, data_dir):
    # 兩個批次照同一份劇本：一個一路跑完；一個在第一次查詢時應用程式重啟，之後從復原入口接著完成
    batch_fake.model_capabilities = replace(batch_fake.model_capabilities, pricing="per_token")
    batch_fake.usage = (200_000, 40_000)
    script = [list(LINES), [(0.2, 1.5, 1, "二つ目。")]]
    batch_fake.script = list(script)
    uninterrupted = ends(run_batch(api, in_process_run_mode, "batch-not-restarted", NAMES[:2]),
                         NAMES[:2])

    restarted = ["restarted-a.wav", "restarted-b.wav"]
    batch_fake.script = list(script)
    batch_fake.batch_polls = [Restart()]
    started = submit_batch(api, in_process_run_mode, "batch-restarted", restarted)
    # 重啟之後：批次停在輪詢中，檔案停在處理中
    assert listed(api, "batch-restarted")["status"] == "POLLING"
    for name in restarted:
        assert record(api, of_file(started, name)[-1]["task_uuid"])["status"] == TaskStatus.PROCESSING

    recovered = ends(recover(api, "batch-restarted"), restarted)
    in_process_run_mode.close(wait=True)  # 等復原整個跑完再查 API

    # 每個檔案的結果和沒中斷時相同：完成的廣播、片段、四種下載、任務紀錄與保留音檔
    for before, after, name in zip(uninterrupted, recovered, restarted, strict=True):
        assert after["status_code"] == TaskStatus.COMPLETED
        assert after["task_uuid"] == of_file(started, name)[-1]["task_uuid"]
        assert without_task_uuid(after["result"]) == without_task_uuid(before["result"])
        assert stored_segments(api, after["task_uuid"]) == stored_segments(api, before["task_uuid"])
        for fmt in ("srt", "vtt", "lrc", "txt"):
            assert download(api, after["task_uuid"], fmt) == download(api, before["task_uuid"], fmt)
        saved, expected = record(api, after["task_uuid"]), record(api, before["task_uuid"])
        assert {key: saved[key] for key in RECORD_FIELDS} == {
            key: expected[key] for key in RECORD_FIELDS}
        assert api.get(f"/api/v1/transcripts/{after['task_uuid']}/audio").content == synthetic_audio()
    assert flat_times(stored_segments(api, recovered[0]["task_uuid"])) == pytest.approx(RESTORED)
    assert listed(api, "batch-restarted")["status"] == "COMPLETED"
    assert leftovers(data_dir) == []


def test_recovery_keeps_polling_until_the_batch_ends(api, in_process_run_mode, batch_fake, quick_polls):
    # 重啟之後批次還在供應商那邊跑：復原入口和執行是同一個狀態機，接著輪詢到批次結束，不必再復原一次
    batch_fake.script = [list(LINES)]
    batch_fake.batch_polls = [Restart(), "RUNNING", "RUNNING"]
    submit_batch(api, in_process_run_mode, "batch-still-running", ["still-running.wav"])

    messages = recover(api, "batch-still-running")

    assert of_file(messages, "still-running.wav")[-1]["status_code"] == TaskStatus.COMPLETED
    assert sum("JOB_STATE_RUNNING" in m["status_text"] for m in messages) == 2
    assert batch_fake.polls == 4


def test_recovery_that_cannot_open_the_provider_can_be_tried_again(
        api, in_process_run_mode, batch_fake):
    # 復原時開不了供應商（例如金鑰無效）：批次退回輪詢中，檔案留在處理中；之後再復原一次就完成
    batch_fake.script = [list(LINES)]
    batch_fake.batch_polls = [Restart()]
    started = submit_batch(api, in_process_run_mode, "batch-key-later", ["key-later.wav"])
    task_uuid = of_file(started, "key-later.wav")[-1]["task_uuid"]
    batch_fake.open_error = ValueError("API 金鑰無效")

    refused = recover(api, "batch-key-later")

    assert refused[-1]["status_text"] == "API Key 無效"
    wait_until(lambda: listed(api, "batch-key-later")["status"] == "POLLING")
    assert record(api, task_uuid)["status"] == TaskStatus.PROCESSING
    batch_fake.open_error = None
    end = of_file(recover(api, "batch-key-later"), "key-later.wav")[-1]
    assert (end["status_code"], end["task_uuid"]) == (TaskStatus.COMPLETED, task_uuid)


@pytest.mark.parametrize("in_process_run_mode", [2], indirect=True)
def test_two_watchers_end_each_file_once(api, in_process_run_mode, batch_fake):
    # 執行還在輪詢時，使用者又呼叫了復原：兩邊都看著同一個批次（Docker 模式看不出執行還在不在，所以
    # 照樣接手）。復原先看到批次結束、結束了檔案；執行晚一步看到時不再結束一次
    batch_fake.script = [list(LINES)]
    run_poll, recovery_poll = threading.Event(), threading.Event()
    batch_fake.poll_holds = [run_poll, recovery_poll]
    with api.websocket_connect("/api/v1/batch/ws/batch-two-watchers") as ws:
        ws.send_json(batch_request(api, ["two-watchers.wav"]))
        wait_until(lambda: batch_fake.polls == 1)
        response = api.post("/api/v1/batch/batch-two-watchers/recover",
                            json={})
        assert response.status_code == 200, response.text
        wait_until(lambda: batch_fake.polls == 2)

        recovery_poll.set()
        messages = receive_until(ws, TaskStatus.BATCH_COMPLETED)
        run_poll.set()
        messages += receive_until(ws, TaskStatus.BATCH_COMPLETED)
    in_process_run_mode.close(wait=True)

    assert [m["status_code"] for m in of_file(messages, "two-watchers.wav")
            if m["status_code"] != TaskStatus.PROCESSING] == [TaskStatus.COMPLETED]
    assert listed(api, "batch-two-watchers")["status"] == "COMPLETED"


def test_a_recovery_queued_behind_the_running_batch_finds_it_completed(
        api, in_process_run_mode, batch_fake):
    # 只有一個 worker：執行還在輪詢時又呼叫了復原，復原排在後面。執行先把批次結束了，復原開始時看到
    # 批次已經完成，不再接手、不再去問供應商
    batch_fake.script = [list(LINES)]
    first_poll = threading.Event()
    batch_fake.poll_holds = [first_poll]
    with api.websocket_connect("/api/v1/batch/ws/batch-queued-recovery") as ws:
        ws.send_json(batch_request(api, ["queued-recovery.wav"]))
        assert batch_fake.polling.wait(TIMEOUT)
        response = api.post("/api/v1/batch/batch-queued-recovery/recover",
                            json={})
        assert response.status_code == 200, response.text
        first_poll.set()
        messages = receive_until(ws, TaskStatus.BATCH_COMPLETED)
    in_process_run_mode.close(wait=True)  # 等排在後面的復原也跑完

    assert [m["status_code"] for m in of_file(messages, "queued-recovery.wav")
            if m["status_code"] != TaskStatus.PROCESSING] == [TaskStatus.COMPLETED]
    assert batch_fake.polls == 1
    assert listed(api, "batch-queued-recovery")["status"] == "COMPLETED"


def test_a_file_whose_record_was_deleted_does_not_hold_back_the_others(
        api, in_process_run_mode, batch_fake):
    # 重啟之後、復原之前，使用者在歷史紀錄刪掉了其中一個檔案：復原照樣結束另一個檔案，之後每次取回
    # 都拿得到它的結果
    batch_fake.script = [list(LINES), list(LINES)]
    batch_fake.batch_polls = [Restart()]
    started = submit_batch(api, in_process_run_mode, "batch-deleted-record", NAMES[:2])
    deleted = of_file(started, NAMES[0])[-1]["task_uuid"]
    assert api.delete(f"/api/v1/history/{deleted}").status_code == 200

    recovered = recover(api, "batch-deleted-record")
    in_process_run_mode.close(wait=True)

    assert of_file(recovered, NAMES[1])[-1]["status_code"] == TaskStatus.COMPLETED
    for _ in range(2):  # 第一次取回之後是已取回，再取回一次也一樣
        files = api.post("/api/v1/batch/batch-deleted-record/recover",
                         json={}).json()["files"]
        assert [(f["file_uid"], f["status"]) for f in files] == [(NAMES[1], TaskStatus.COMPLETED)]


def test_files_whose_result_status_cannot_be_recorded_are_still_retrieved(
        api, in_process_run_mode, batch_fake, test_engine):
    # 復原時結果狀態記不回 batch_files（例如磁碟滿了）：任務紀錄已經記下完成，取回照樣拿得到結果
    batch_fake.script = [list(LINES), list(LINES)]
    batch_fake.batch_polls = [Restart()]
    submit_batch(api, in_process_run_mode, "batch-status-lost", NAMES[:2])

    with writes_fail(test_engine, "batch_files", "UPDATE"):
        recovered = recover(api, "batch-status-lost")
        in_process_run_mode.close(wait=True)

    assert [of_file(recovered, name)[-1]["status_code"] for name in NAMES[:2]] == [
        TaskStatus.COMPLETED] * 2
    files = api.post("/api/v1/batch/batch-status-lost/recover",
                     json={}).json()["files"]
    assert [f["file_uid"] for f in files] == NAMES[:2]


# ─── 舊版送出的批次（#117）──────────────────────────────────────────────────

@pytest.mark.parametrize("sent_before_start", [True, False],
                         ids=["sent-before-this-version-started", "sent-after-it-started"])
def test_a_batch_sent_by_the_previous_release_is_finished_from_recovery(
        api, in_process_run_mode, batch_fake, db_session, test_engine, sent_before_start):
    # 上一個發布版本送出的批次還在供應商那邊跑時升級：三個檔案，第二個上傳失敗沒有送出；第一個去靜音
    # 過，第三個沒有。從復原入口接手，和這一版送出的批次走同一個狀態機結束。舊版的 worker 也可能在
    # 這一版啟動之後才送出（Docker 模式升級時）：啟動時沒補到列的，復原入口當場補
    batch_id = f"batch-older-{sent_before_start}"
    batch_fake.model_capabilities = replace(batch_fake.model_capabilities, pricing="per_token")
    batch_fake.usage = (200_000, 40_000)
    batch_fake.script = [list(LINES), [(0.2, 1.5, 1, "三つ目。")]]
    if not sent_before_start:
        start_this_version(test_engine)
    name = batch_fake.submit_batch([(None, "")] * 2, "older")  # 舊版送出的兩個請求
    task_uuids = sent_by_previous_release(db_session, batch_id, name, [
        OlderFile("older-a", SPANS), OlderFile("older-b", sent=False), OlderFile("older-c")])

    if sent_before_start:
        start_this_version(test_engine)
    messages = recover(api, batch_id)
    in_process_run_mode.close(wait=True)  # 等復原整個跑完再查 API

    # 送出的兩個檔案：和這一版的批次一樣，處理中……之後宣告完成，廣播帶著舊版開始的那個任務
    for file_uid in ("older-a", "older-c"):
        own = of_file(messages, file_uid)
        assert codes(own)[-1] == TaskStatus.COMPLETED
        assert set(codes(own)[:-1]) == {TaskStatus.PROCESSING}
        assert {m["task_uuid"] for m in own} == {task_uuids[file_uid]}
        saved = record(api, task_uuids[file_uid])
        assert saved["status"] == TaskStatus.COMPLETED
        assert (saved["total_tokens"], saved["cost"]) == (240_000, pytest.approx(0.15))
        assert saved["audio_duration_seconds"] == pytest.approx(12.0)
        assert own[-1]["result"]["cost"] == pytest.approx(0.15)
        for fmt in ("srt", "vtt", "lrc", "txt"):
            assert download(api, task_uuids[file_uid], fmt) == own[-1]["result"]["transcripts"][fmt]
    # 去靜音過的檔案，片段的時間還原回原音檔；沒有去靜音的原樣
    assert flat_times(stored_segments(api, task_uuids["older-a"])) == pytest.approx(RESTORED)
    assert flat_times(stored_segments(api, task_uuids["older-c"])) == pytest.approx([0.2, 1.5])
    # 沒有送出的檔案在舊版就結束了，復原不再動它
    assert of_file(messages, "older-b") == []
    assert record(api, task_uuids["older-b"])["status"] == TaskStatus.FAILED
    assert listed(api, batch_id)["status"] == "COMPLETED"


def test_an_upload_recorded_by_an_older_version_is_retained_after_recovery(
        api, in_process_run_mode, batch_fake, db_session, test_engine, data_dir):
    # #115 到 #116 之間的版本另外記下了上傳檔：復原之後和這一版的批次一樣，上傳檔搬進保留區，暫存區
    # 不留檔
    batch_fake.script = [list(LINES)]
    name = batch_fake.submit_batch([(None, "")], "older")
    path = data_dir / "temp_uploads" / upload(api, "kept.wav")
    task_uuids = sent_between_115_and_116(db_session, "batch-older-upload", name,
                                          [("kept", str(path))])

    start_this_version(test_engine)
    end = of_file(recover(api, "batch-older-upload"), "kept")[-1]
    in_process_run_mode.close(wait=True)

    assert (end["status_code"], end["task_uuid"]) == (TaskStatus.COMPLETED, task_uuids["kept"])
    assert flat_times(stored_segments(api, end["task_uuid"])) == pytest.approx(RESTORED)
    assert api.get(f"/api/v1/transcripts/{end['task_uuid']}/audio").content == synthetic_audio()
    assert leftovers(data_dir) == []


def test_results_of_a_batch_the_previous_release_finished_can_still_be_retrieved(
        api, batch_fake, db_session, test_engine):
    # 舊版已經結束、還沒取回的批次：完成的檔案結果只存成任務紀錄裡的 LRC，另一個檔案供應商回報失敗。
    # 升級後「取回結果」照樣拿得到完成的那個，從任務紀錄讀出，和到歷史紀錄下載的相同；取回之後再取回
    # 一次也一樣，不再去問供應商
    lrc = "[00:00.20]おはよう。\n[00:05.40]こんにちは。\n[00:10.30]またね。"
    task_uuids = sent_by_previous_release(db_session, "batch-older-done", "batches/older-done",
                                          [OlderFile("older-done", SPANS), OlderFile("older-garbled")])
    finished_by_previous_release(db_session, "batch-older-done", task_uuids,
                                 {"older-done": lrc, "older-garbled": None})

    start_this_version(test_engine)

    for _ in range(2):  # 第一次取回之後是已取回
        response = api.post("/api/v1/batch/batch-older-done/recover", json={})
        assert response.status_code == 200, response.text
        [retrieved] = response.json()["files"]
        assert (retrieved["file_uid"], retrieved["original_filename"], retrieved["status"]) == (
            "older-done", "older-done.wav", TaskStatus.COMPLETED)
        transcripts = retrieved["result"]["transcripts"]
        assert transcripts["lrc"] == lrc
        for fmt in ("srt", "vtt", "txt"):
            assert transcripts[fmt] == download(api, task_uuids["older-done"], fmt)
            assert "こんにちは。" in transcripts[fmt]
        assert retrieved["result"]["cost"] == pytest.approx(0.15)
    assert batch_fake.polls == 0
    assert listed(api, "batch-older-done")["status"] == "RETRIEVED"


def test_the_batch_list_names_each_file_of_a_batch_sent_by_the_previous_release(
        api, db_session, test_engine):
    # 任務頁列出舊版批次的每個檔案，依在批次裡的順序，連沒有送出的也列；每次啟動都會補列，補過的
    # 不再補一次。看著它的舊版執行在升級之後已經不在了：和這一版停住的批次一樣給「恢復」
    sent_by_previous_release(db_session, "batch-older-listed", "batches/older-listed", [
        OlderFile("listed-a", SPANS), OlderFile("listed-b", sent=False), OlderFile("listed-c")])

    start_this_version(test_engine)
    start_this_version(test_engine)

    batch = listed(api, "batch-older-listed")
    assert batch["files"] == [{"file_uid": uid, "original_filename": f"{uid}.wav"}
                              for uid in ("listed-a", "listed-b", "listed-c")]
    assert batch["file_count"] == 3
    assert shown(api, "batch-older-listed") == ("POLLING", False, True)


@pytest.mark.parametrize("status", ["POLLING", "FAILED", "COMPLETED"])
def test_an_older_batch_whose_file_list_cannot_be_read_is_left_as_it_was(
        api, db_session, test_engine, status):
    # 舊版的檔案清單讀不懂（這裡沒有記下任務紀錄 id），啟動時與復原入口都補不了列：取回或復原都回看得懂
    # 的錯誤，批次的狀態不動，也不派送復原；任務頁也不給「恢復」，即使看著它的任務已經不在了
    from app.database.models import BatchJob

    batch_id = f"batch-unreadable-{status}"
    unreadable_older_batch(db_session, batch_id, status)

    start_this_version(test_engine)
    response = api.post(f"/api/v1/batch/{batch_id}/recover", json={})

    assert response.status_code == 400
    assert "舊版送出的" in response.json()["detail"]
    assert "讀不出它的檔案清單" in response.json()["detail"]
    db_session.expire_all()
    assert db_session.get(BatchJob, batch_id).status == status
    assert listed(api, batch_id)["recoverable"] is False


def test_an_unreadable_older_batch_does_not_hold_back_the_others(api, db_session, test_engine):
    # 啟動時一個舊版批次讀不懂（這裡檔案清單不是 JSON）：不補它的列，其他舊版批次照樣補上
    unreadable_older_batch(db_session, "batch-garbled", file_list="{not json")
    sent_by_previous_release(db_session, "batch-after-garbled", "batches/after-garbled",
                             [OlderFile("after-garbled")])

    start_this_version(test_engine)

    assert listed(api, "batch-garbled")["files"] == []
    assert listed(api, "batch-after-garbled")["files"] == [
        {"file_uid": "after-garbled", "original_filename": "after-garbled.wav"}]


def test_a_new_batch_keeps_one_row_per_file_instead_of_json_columns(
        api, in_process_run_mode, batch_fake, db_session):
    from app.database.models import BatchFile, BatchJob

    # 第二個檔案上傳失敗、沒有送出；第三個送出了，供應商回報它轉錄失敗
    batch_fake.upload_errors = [None, RuntimeError("讀不到檔案")]
    batch_fake.script = [list(LINES), Fail("音檔無法解碼")]

    messages = run_batch(api, in_process_run_mode, "batch-rows", NAMES)

    # 這條驗收講的是存進資料庫的樣子，所以直接讀資料表
    db_session.expire_all()
    job = db_session.get(BatchJob, "batch-rows")
    assert [job.file_mapping_json, job.file_durations_json, job.file_log_uuids_json,
            job.results_json] == [None] * 4
    rows = db_session.query(BatchFile).filter_by(batch_id="batch-rows").order_by(BatchFile.seq).all()
    # 每個檔案一列：任務紀錄 id、長度與結果狀態；語音視圖的序列化形式只有送出的檔案有
    assert [(row.file_uid, str(row.task_uuid), row.status) for row in rows] == [
        (end["file_uid"], end["task_uuid"], end["status_code"]) for end in ends(messages, NAMES)]
    assert [row.audio_duration_seconds for row in rows] == [pytest.approx(12.0, abs=0.1)] * 3
    assert [row.speech_view_json is not None for row in rows] == [True, False, True]


def test_the_batch_list_reads_each_file_from_the_new_table(api, in_process_run_mode, batch_fake):
    # 上傳中就列出每個檔案；回應的格式不變
    batch_fake.hold = threading.Event()
    batch_fake.script = [list(LINES), list(LINES)]
    with api.websocket_connect("/api/v1/batch/ws/batch-listed") as ws:
        ws.send_json(batch_request(api, NAMES[:2]))
        assert batch_fake.started.wait(TIMEOUT)
        uploading = listed(api, "batch-listed")
        batch_fake.hold.set()
        messages = receive_until(ws, TaskStatus.BATCH_COMPLETED)
    wait_until(lambda: not in_process_run_mode.is_alive(messages[-1]["task_uuid"]))

    files = [{"file_uid": name, "original_filename": name} for name in NAMES[:2]]
    assert set(uploading) == {"batch_id", "status", "file_count", "is_alive", "created_at",
                              "elapsed_seconds", "files", "session_id", "recoverable"}
    assert (uploading["status"], uploading["is_alive"], uploading["files"],
            uploading["recoverable"]) == ("UPLOADING", True, files, False)
    completed = listed(api, "batch-listed")
    assert (completed["status"], completed["file_count"], completed["files"],
            completed["recoverable"]) == ("COMPLETED", 2, files, False)


@pytest.mark.parametrize("in_process_run_mode", [2], indirect=True)
def test_a_batch_id_sent_again_leaves_the_running_batch_alone(api, in_process_run_mode, batch_fake):
    # 兩個 worker，兩次執行可以同時跑。第一次的批次還在輪詢時，同一個批次 id 又送了一次（例如前端
    # 重送）：第二次的檔案失敗，第一次的批次不受影響，照樣跑完、取回得到它的結果
    batch_fake.script = [list(LINES)]
    first_poll = threading.Event()
    batch_fake.poll_holds = [first_poll]
    with api.websocket_connect("/api/v1/batch/ws/batch-again") as ws:
        ws.send_json(batch_request(api, ["again-a.wav"]))
        assert batch_fake.polling.wait(TIMEOUT)

    second = of_file(run_batch(api, in_process_run_mode, "batch-again", ["again-b.wav"]),
                     "again-b.wav")[-1]

    assert second["status_code"] == TaskStatus.FAILED
    assert listed(api, "batch-again")["status"] == "POLLING"
    first_poll.set()
    wait_until(lambda: listed(api, "batch-again")["status"] == "COMPLETED")
    assert listed(api, "batch-again")["files"] == [
        {"file_uid": "again-a.wav", "original_filename": "again-a.wav"}]
    files = api.post("/api/v1/batch/batch-again/recover", json={}).json()["files"]
    assert [(f["file_uid"], f["status"]) for f in files] == [("again-a.wav", TaskStatus.COMPLETED)]


def test_a_batch_archived_while_running_still_finishes(api, in_process_run_mode, batch_fake):
    # 歸檔只管任務頁怎麼顯示：批次照樣跑完，任務頁又列成完成，可以取回結果
    batch_fake.script = [list(LINES)]
    first_poll = threading.Event()
    batch_fake.poll_holds = [first_poll]
    with api.websocket_connect("/api/v1/batch/ws/batch-archived") as ws:
        ws.send_json(batch_request(api, ["archived.wav"]))
        assert batch_fake.polling.wait(TIMEOUT)
        assert api.post("/api/v1/batch/batch-archived/dismiss").status_code == 200
        first_poll.set()
        messages = receive_until(ws, TaskStatus.BATCH_COMPLETED)
    wait_until(lambda: not in_process_run_mode.is_alive(messages[-1]["task_uuid"]))

    assert of_file(messages, "archived.wav")[-1]["status_code"] == TaskStatus.COMPLETED
    assert listed(api, "batch-archived")["status"] == "COMPLETED"


def test_a_batch_archived_after_a_restart_can_still_be_recovered(
        api, in_process_run_mode, batch_fake):
    # 重啟之後、復原之前就歸檔了：檔案還在處理中，取回時從復原入口接手，不是回一份空的結果
    batch_fake.script = [list(LINES)]
    batch_fake.batch_polls = [Restart()]
    submit_batch(api, in_process_run_mode, "batch-archived-restarted", ["archived-restarted.wav"])
    assert api.post("/api/v1/batch/batch-archived-restarted/dismiss").status_code == 200

    messages = recover(api, "batch-archived-restarted")

    assert of_file(messages, "archived-restarted.wav")[-1]["status_code"] == TaskStatus.COMPLETED
    assert listed(api, "batch-archived-restarted")["status"] == "COMPLETED"


# ─── 同一個批次 id 的舊連線還沒收尾（#203） ─────────────────────────────────────
# 同一個批次 id 先後有兩條連線（例如前端重送），伺服器還沒發現舊連線斷了，新連線就連上來：伺服器先關掉
# 舊連線、登記新連線，舊連線的處理流程之後才收尾。收尾只能動舊連線自己，批次的狀態訊息才送得到新連線

def send_rejected_batch(ws) -> None:
    """送出上傳檔已經不在的批次：整批不派送，端點回失敗之後連線照樣開著、等下一則訊息。"""
    ws.send_json({
        "files": [{"filename": "swept.wav", "original_filename": "swept.wav", "file_uid": "swept"}],
        "provider": "fake", "model": FAKE_MODEL, "source_lang": "ja"})
    assert receive(ws)["status_code"] == TaskStatus.FAILED


def test_the_old_connection_disconnecting_later_keeps_the_new_one(
        api, in_process_run_mode, batch_fake):
    batch_fake.script = [list(LINES)]
    path = "/api/v1/batch/ws/batch-old-disconnects"
    with ExitStack() as old_connection:
        send_rejected_batch(old_connection.enter_context(api.websocket_connect(path)))
        with api.websocket_connect(path) as ws:
            old_connection.close()  # 舊連線的處理流程這時才收到斷線
            ws.send_json(batch_request(api, ["reconnect.wav"]))
            messages = receive_until(ws, TaskStatus.BATCH_COMPLETED)
    wait_until(lambda: not in_process_run_mode.is_alive(messages[-1]["task_uuid"]))

    assert of_file(messages, "reconnect.wav")[-1]["status_code"] == TaskStatus.COMPLETED


def test_the_old_connection_failing_later_keeps_the_new_one(api, in_process_run_mode, batch_fake):
    batch_fake.script = [list(LINES)]
    path = "/api/v1/batch/ws/batch-old-fails"
    with api.websocket_connect(path) as old:
        send_rejected_batch(old)
        with api.websocket_connect(path) as ws:
            # 舊連線已經被伺服器關掉，它的處理流程接著又收到頁面的心跳：在關掉的連線上收訊息會丟例外，
            # 走端點發生例外時的收尾
            ping(old)
            ws.send_json(batch_request(api, ["reconnect.wav"]))
            messages = receive_until(ws, TaskStatus.BATCH_COMPLETED)
    wait_until(lambda: not in_process_run_mode.is_alive(messages[-1]["task_uuid"]))

    assert of_file(messages, "reconnect.wav")[-1]["status_code"] == TaskStatus.COMPLETED


# ─── 任務頁的恢復入口 ────────────────────────────────────────────────────────

def test_a_batch_left_waiting_by_restarts_is_offered_for_recovery(
        api, in_process_run_mode, batch_fake):
    # 應用程式在輪詢時重啟，接手的復原又遇到一次重啟：每次都沒有任務看著批次了，任務頁給「恢復」；
    # 恢復到完成之後不再給
    batch_fake.script = [list(LINES)]
    batch_fake.batch_polls = [Restart(), Restart()]
    submit_batch(api, in_process_run_mode, "batch-offered", ["offered.wav"])
    assert shown(api, "batch-offered") == ("POLLING", False, True)

    response = api.post("/api/v1/batch/batch-offered/recover", json={})
    assert response.status_code == 200, response.text
    wait_until(lambda: listed(api, "batch-offered")["is_alive"] is False)
    assert shown(api, "batch-offered") == ("RECOVERING", False, True)

    end = of_file(recover(api, "batch-offered"), "offered.wav")[-1]

    assert end["status_code"] == TaskStatus.COMPLETED
    assert shown(api, "batch-offered") == ("COMPLETED", None, False)


def test_recovery_without_a_google_key_points_to_settings_and_leaves_the_batch_waiting(
        api, in_process_run_mode, batch_fake, no_google_key):
    # 任務頁按「恢復」時不帶金鑰，後端改用資料庫裡的；還沒設定時回看得懂的錯誤，請使用者先到
    # Settings 設定，批次不動、照樣給「恢復」
    batch_fake.script = [list(LINES)]
    batch_fake.batch_polls = [Restart()]
    submit_batch(api, in_process_run_mode, "batch-no-key", ["no-key.wav"])

    response = api.post("/api/v1/batch/batch-no-key/recover", json={})

    assert response.status_code == 400
    assert "API 金鑰" in response.json()["detail"]
    assert "Settings" in response.json()["detail"]
    assert shown(api, "batch-no-key") == ("POLLING", False, True)


def test_a_batch_still_being_watched_is_not_offered_for_recovery(
        api, in_process_run_mode, batch_fake):
    # 執行還在輪詢：有任務看著批次，任務頁不給「恢復」
    batch_fake.script = [list(LINES)]
    first_poll = threading.Event()
    batch_fake.poll_holds = [first_poll]
    with api.websocket_connect("/api/v1/batch/ws/batch-watched") as ws:
        ws.send_json(batch_request(api, ["watched.wav"]))
        assert batch_fake.polling.wait(TIMEOUT)
        watched = shown(api, "batch-watched")
        first_poll.set()
        receive_until(ws, TaskStatus.BATCH_COMPLETED)

    assert watched == ("POLLING", True, False)


def test_a_watcher_that_goes_quiet_is_taken_for_stopped_until_it_is_heard_again(
        api, in_process_run_mode, batch_fake, db_session, quick_polls, quick_transient_retries):
    # 心跳：看著批次的任務每次查詢、每次重試之前都記下它還在。超過 10 分鐘沒有消息，任務頁就當成停住、
    # 給「恢復」（Docker 模式的 worker 被砍掉時只看得出這個）；一有消息又是還在處理
    batch_fake.script = [list(LINES)]
    batch_fake.batch_polls = ["RUNNING", transient()]
    holds = [threading.Event() for _ in range(3)]
    batch_fake.poll_holds = list(holds)
    with api.websocket_connect("/api/v1/batch/ws/batch-heartbeat") as ws:
        ws.send_json(batch_request(api, ["heartbeat.wav"]))
        wait_until(lambda: batch_fake.polls == 1)  # 第一次查詢停在這裡
        last_heard(db_session, "batch-heartbeat", minutes_ago=11)
        assert shown(api, "batch-heartbeat") == ("POLLING", False, True)

        holds[0].set()  # 查到還在跑：記下心跳，等一下再查
        wait_until(lambda: batch_fake.polls == 2)
        assert shown(api, "batch-heartbeat") == ("POLLING", True, False)

        last_heard(db_session, "batch-heartbeat", minutes_ago=11)
        holds[1].set()  # 暫時錯誤：等著重試之前也記下心跳
        wait_until(lambda: batch_fake.polls == 3)
        assert shown(api, "batch-heartbeat") == ("POLLING", True, False)

        holds[2].set()
        messages = receive_until(ws, TaskStatus.BATCH_COMPLETED)

    assert of_file(messages, "heartbeat.wav")[-1]["status_code"] == TaskStatus.COMPLETED


def test_a_long_upload_is_not_taken_for_stopped(api, in_process_run_mode, batch_fake, db_session):
    # 上傳中不記心跳（一個大檔可能傳很久）：執行模式說看著它的任務還在，就算很久沒有消息也是上傳中
    batch_fake.hold = threading.Event()
    batch_fake.script = [list(LINES)]
    with api.websocket_connect("/api/v1/batch/ws/batch-long-upload") as ws:
        ws.send_json(batch_request(api, ["long-upload.wav"]))
        assert batch_fake.started.wait(TIMEOUT)
        last_heard(db_session, "batch-long-upload", minutes_ago=11)
        uploading = shown(api, "batch-long-upload")
        batch_fake.hold.set()
        receive_until(ws, TaskStatus.BATCH_COMPLETED)

    assert uploading == ("UPLOADING", True, False)


def test_a_batch_whose_polling_broke_off_is_listed_as_failed_and_offered_for_recovery(
        api, in_process_run_mode, batch_fake):
    # 輪詢中斷（例如網路斷了）：批次記成失敗，任務頁照樣列出來並給「恢復」，恢復之後接著完成
    batch_fake.script = [list(LINES)]
    batch_fake.batch_polls = [RuntimeError("連線中斷")]
    run_batch(api, in_process_run_mode, "batch-broke-off", ["broke-off.wav"])
    assert shown(api, "batch-broke-off") == ("FAILED", None, True)

    end = of_file(recover(api, "batch-broke-off"), "broke-off.wav")[-1]

    assert end["status_code"] == TaskStatus.COMPLETED
    assert shown(api, "batch-broke-off") == ("COMPLETED", None, False)


def test_a_batch_that_failed_before_it_was_sent_is_listed_without_recovery(
        api, in_process_run_mode, batch_fake):
    # 沒有一個檔案上傳成功，批次沒有送出：任務頁列出它失敗了，但沒有東西可以恢復
    batch_fake.upload_errors = [RuntimeError("讀不到檔案")]

    run_batch(api, in_process_run_mode, "batch-never-sent", ["never-sent.wav"])

    assert shown(api, "batch-never-sent") == ("FAILED", None, False)


def test_a_failed_batch_leaves_the_task_page_a_day_after_it_failed(
        api, in_process_run_mode, batch_fake, db_session):
    # 和已取回的批次一樣，失敗的批次在任務頁只留 24 小時，從失敗的時候算起
    from datetime import datetime, timedelta

    from app.database.models import BatchJob

    batch_fake.upload_errors = [RuntimeError("讀不到檔案")]
    run_batch(api, in_process_run_mode, "batch-failed-long-ago", ["failed-long-ago.wav"])

    for hours, still_shown in [(23, True), (25, False)]:
        db_session.query(BatchJob).filter_by(batch_id="batch-failed-long-ago").update(
            {BatchJob.updated_at: datetime.now() - timedelta(hours=hours)})
        db_session.commit()
        assert ("batch-failed-long-ago" in listed_batch_ids(api)) is still_shown, hours


def test_a_batch_the_provider_reports_as_failed_can_be_recovered_but_stays_failed(
        api, in_process_run_mode, batch_fake):
    # 供應商回報整個批次失敗（例如過期了）：資料庫分不出是輪詢中斷還是供應商回報失敗，任務頁照樣給
    # 「恢復」。恢復時供應商還是回報失敗，檔案與批次照樣是失敗，之後照樣給「恢復」
    batch_fake.script = [list(LINES)]
    batch_fake.batch_outcome = "EXPIRED"
    first = of_file(run_batch(api, in_process_run_mode, "batch-expired-again", ["expired.wav"]),
                    "expired.wav")[-1]
    assert first["status_code"] == TaskStatus.FAILED
    assert shown(api, "batch-expired-again") == ("FAILED", None, True)

    again = of_file(recover(api, "batch-expired-again"), "expired.wav")[-1]

    assert (again["status_code"], again["task_uuid"]) == (TaskStatus.FAILED, first["task_uuid"])
    assert record(api, first["task_uuid"])["status"] == TaskStatus.FAILED
    assert shown(api, "batch-expired-again") == ("FAILED", None, True)


def test_an_archived_batch_without_results_leaves_the_task_page(
        api, in_process_run_mode, batch_fake):
    # 歸檔記成已取回，已取回的批次在任務頁留 24 小時。沒有任何結果的不留：失敗了才歸檔的批次，
    # 重新整理之後不會變成「已取回」回到任務頁
    batch_fake.upload_errors = [RuntimeError("讀不到檔案")]
    run_batch(api, in_process_run_mode, "batch-archived-failure", ["archived-failure.wav"])
    assert "batch-archived-failure" in listed_batch_ids(api)

    assert api.post("/api/v1/batch/batch-archived-failure/dismiss").status_code == 200

    assert "batch-archived-failure" not in listed_batch_ids(api)


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


# ─── 上傳中停住的批次 ────────────────────────────────────────────────────────

def stop_while_uploading(api: TestClient, batch_id: str, names: list[str]) -> None:
    """送出批次，在上傳最後一個檔案時應用程式重啟（:class:`Restart`）：等這次執行停下來。"""
    with api.websocket_connect(f"/api/v1/batch/ws/{batch_id}") as ws:
        ws.send_json(batch_request(api, names))
        wait_until(lambda: listed_batch_ids(api).count(batch_id) == 1
                   and listed(api, batch_id)["is_alive"] is False)


def test_a_batch_stopped_while_uploading_is_recorded_as_failed_at_startup(
        api, in_process_run_mode, batch_fake, data_dir):
    # 第一個檔案上傳好了，第二個上傳失敗，第三個上傳到一半時應用程式重啟：批次停在上傳中，
    # 還沒結束的檔案停在處理中
    names = ["stopped-a.wav", "stopped-b.wav", "stopped-c.wav"]
    batch_fake.upload_errors = [None, RuntimeError("讀不到檔案"), Restart()]
    stop_while_uploading(api, "batch-stopped-uploading", names)
    assert shown(api, "batch-stopped-uploading") == ("UPLOADING", False, False)
    records = {item["original_filename"]: item for item in api.get(
        "/api/v1/history", params={"keyword": "stopped-"}).json()["items"]}
    assert [records[name]["status"] for name in names] == [
        TaskStatus.PROCESSING, TaskStatus.FAILED, TaskStatus.PROCESSING]

    # 啟動時：沒有任務還看著它，批次記成失敗；沒送出過，所以不給「恢復」
    batch_core.end_stopped_uploads()

    assert shown(api, "batch-stopped-uploading") == ("FAILED", None, False)
    for name in names:
        saved = record(api, records[name]["task_uuid"])
        assert saved["status"] == TaskStatus.FAILED
        assert saved["is_batch"] is True
        # 和單檔任務一樣：上傳檔照保留設定處理
        assert api.get(
            f"/api/v1/transcripts/{saved['task_uuid']}/audio").content == synthetic_audio()
    # 已經因為上傳失敗結束的檔案，原因不被蓋掉
    assert "讀不到檔案" in record(api, records["stopped-b.wav"]["task_uuid"])["error_message"]
    for name in ("stopped-a.wav", "stopped-c.wav"):
        assert "上傳" in record(api, records[name]["task_uuid"])["error_message"]
    assert leftovers(data_dir) == []


def test_a_batch_already_sent_is_left_for_recovery_at_startup(
        api, in_process_run_mode, batch_fake):
    # 送出之後才重啟的批次停在輪詢中：啟動時不動它，照樣從任務頁恢復到完成
    batch_fake.script = [list(LINES)]
    batch_fake.batch_polls = [Restart()]
    submit_batch(api, in_process_run_mode, "batch-sent-before-restart", ["sent.wav"])

    batch_core.end_stopped_uploads()

    assert shown(api, "batch-sent-before-restart") == ("POLLING", False, True)
    end = of_file(recover(api, "batch-sent-before-restart"), "sent.wav")[-1]
    assert end["status_code"] == TaskStatus.COMPLETED
