"""接縫 3：Gemini 轉接器，用假的 google-genai 用戶端（#107、#110）。

只從轉接器的公開介面觀察：轉錄結果（片段）、用量、實際用到的處理模式、拋出的錯誤，
以及遠端還留著哪些檔案、送出了哪些生成請求（假用戶端的 ``stored`` 與 ``generated``，
等同去 Gemini 查）。
"""
import threading
from contextlib import suppress

import pytest
from google.genai import types

from app.exceptions import GeminiPermanentError, GeminiTransientError, TranscriptionCancelledError
from app.provider.base import ProgressAndCancel, TranscribeRequest
from app.provider.google.provider import FLEX_MAX_RETRIES, GeminiProvider
from tests.support.fake_genai import (
    Blocked,
    FakeGenaiClient,
    Reply,
    invalid_argument,
    rate_limited,
    unavailable,
)

MODEL = "gemini-2.5-flash"
# 這裡不看進度，使用者也沒有取消
PROGRESS = ProgressAndCancel(report=lambda text: None, cancel_requested=lambda: False)


@pytest.fixture
def genai():
    return FakeGenaiClient()


@pytest.fixture
def gemini(genai):
    return GeminiProvider(MODEL, client=genai, sleep=lambda seconds: None)


@pytest.fixture
def audio(tmp_path):
    path = tmp_path / "voice.wav"
    path.write_bytes(b"RIFF fake wav")
    return path


def request(**overrides) -> TranscribeRequest:
    return TranscribeRequest(model=MODEL, prompt="請轉錄這段音檔", **overrides)


def transcript(result) -> list[tuple]:
    """轉錄結果的片段，只看（開始, 說話者編號, 文字）。"""
    return [(s["start"], s["speaker"], s["text"]) for s in result.segments]


class TestTranscribe:
    def test_returns_transcript_and_usage(self, gemini, genai, audio):
        genai.replies = [Reply(text="[00:01.00]こんにちは", input_tokens=1000, output_tokens=200)]

        result = gemini.transcribe(audio, request(), PROGRESS)

        assert result.success
        assert transcript(result) == [(1.0, None, "こんにちは")]
        assert (result.input_tokens, result.output_tokens, result.total_tokens) == (1000, 200, 1200)
        assert result.service_tier_used == "standard"

    def test_waits_until_gemini_has_processed_the_upload(self, gemini, genai, audio):
        # 假用戶端和 Gemini 一樣：檔案還在處理中就拿來轉錄會回 400
        genai.processing_polls = 3

        assert gemini.transcribe(audio, request(), PROGRESS).success

    def test_blocked_response_is_a_failure(self, gemini, genai, audio):
        genai.replies = [Blocked()]

        result = gemini.transcribe(audio, request(), PROGRESS)

        assert not result.success
        assert "PROHIBITED_CONTENT" in result.text


class TestLrcIsParsedOnce:
    """Gemini 寫的 LRC 在轉接器裡解析一次就變成轉錄結果（片段）；之後的流程不再碰 LRC 文字。"""

    def test_each_timestamped_line_is_a_segment_and_other_lines_are_dropped(
            self, gemini, genai, audio):
        # 時間戳的小數兩位、三位或省略都算有時間戳
        genai.replies = [Reply(text=(
            "```lrc\n"
            "[00:01.500]おはよう。\n"
            "這一行沒有時間戳\n"
            "\n"
            "[01:02.25]こんにちは。\n"
            "[01:05]またね。\n"
            "```"))]

        result = gemini.transcribe(audio, request(), PROGRESS)

        assert transcript(result) == [
            (1.5, None, "おはよう。"), (62.25, None, "こんにちは。"), (65.0, None, "またね。")]
        assert result.text == ""  # 不再附著 LRC 文字

    def test_lines_break_only_at_newlines(self, gemini, genai, audio):
        # 只在換行斷開、去掉行尾的 \r：行裡的 U+2028 之類的分隔字元留著，不會把一行拆成兩半、
        # 丟掉後半（輸出格式模組會把它收成空白）
        genai.replies = [Reply(text="[00:01.00]おはよう\u2028ございます。\r\n[00:02.00]はい。\r\n")]

        result = gemini.transcribe(audio, request(), PROGRESS)

        assert transcript(result) == [(1.0, None, "おはよう\u2028ございます。"), (2.0, None, "はい。")]

    def test_timestamp_may_have_hours(self, gemini, genai, audio):
        genai.replies = [Reply(text="[00:00:01.500]おはよう。\n[01:02:03.25]またね。")]

        result = gemini.transcribe(audio, request(), PROGRESS)

        assert transcript(result) == [(1.5, None, "おはよう。"), (3723.25, None, "またね。")]

    @pytest.mark.parametrize("first, second", [
        ("Speaker 1:", "Speaker 2:"),
        ("Speaker A:", "Speaker B:"),
        ("Speaker 1：", "Speaker 2："),
    ], ids=["numbers", "letters", "full-width-colon"])
    def test_speaker_codes_become_speaker_ids(self, gemini, genai, audio, first, second):
        # Gemini 寫的同一個說話者代號一律同一個說話者編號；沒有代號的行（例如聲響描述）沒有編號
        genai.replies = [Reply(text=(
            f"[00:01.00]{first} おはよう。\n"
            f"[00:02.00]{second} こんにちは。\n"
            f"[00:03.00]{first} またね。\n"
            "[00:04.00][拍手]"))]

        result = gemini.transcribe(audio, request(), PROGRESS)

        assert transcript(result) == [
            (1.0, "S0", "おはよう。"), (2.0, "S1", "こんにちは。"), (3.0, "S0", "またね。"),
            (4.0, None, "[拍手]")]

    def test_code_before_the_timestamp_and_list_markers(self, gemini, genai, audio):
        # 說話者代號也可能寫在時間戳前面；行首可以有空白或項目符號
        genai.replies = [Reply(text=(
            "Speaker 1: [00:01.00]おはよう。\n"
            "- [00:02.00]Speaker 2: こんにちは。\n"
            "  * Speaker 1: [00:03.00] またね。\n"
            "• [00:04.00]はい。"))]

        result = gemini.transcribe(audio, request(), PROGRESS)

        assert transcript(result) == [
            (1.0, "S0", "おはよう。"), (2.0, "S1", "こんにちは。"), (3.0, "S0", "またね。"),
            (4.0, None, "はい。")]

    @pytest.mark.parametrize("code, variant", [
        ("Speaker 1:", "speaker 1:"),
        ("Speaker 1:", "SPEAKER 1:"),
        ("Speaker 1:", "**Speaker 1:**"),
        ("Speaker 1:", "**Speaker 1**:"),
        ("Speaker 1:", "Speaker 01:"),
        ("Speaker 1:", "Speaker １:"),
        ("Speaker A:", "speaker a:"),
    ], ids=["lower", "upper", "bold", "bold-before-colon", "leading-zero", "full-width-digit",
            "lower-letter"])
    def test_variants_of_a_code_are_the_same_speaker(self, gemini, genai, audio, code, variant):
        # 說話者代號不分大小寫、去掉 markdown 粗體，全形數字與前導零正規化
        genai.replies = [Reply(text=(
            f"[00:01.00]{code} おはよう。\n"
            "[00:02.00]Speaker 9: はい。\n"
            f"[00:03.00]{variant} またね。"))]

        result = gemini.transcribe(audio, request(), PROGRESS)

        assert transcript(result) == [
            (1.0, "S0", "おはよう。"), (2.0, "S1", "はい。"), (3.0, "S0", "またね。")]

    def test_words_that_only_look_like_a_code_stay_in_the_text(self, gemini, genai, audio):
        # 字母代號前面要有空白：「Speakers:」是文字，不是說話者「S」
        genai.replies = [Reply(text="[00:01.00]Speakers: are loud.\n[00:02.00]Speaker1: はい。")]

        result = gemini.transcribe(audio, request(), PROGRESS)

        assert transcript(result) == [(1.0, None, "Speakers: are loud."), (2.0, "S0", "はい。")]

    def test_speaker_ids_follow_the_order_codes_first_appear(self, gemini, genai, audio):
        # 不照代號上的數字：先開口的是 S0，和本機一樣；代號從 0 起算或跳號也不會缺號、撞號
        genai.replies = [Reply(text=(
            "[00:01.00]Speaker 2: おはよう。\n"
            "[00:02.00]Speaker 0: はい。\n"
            "[00:03.00]Speaker 2: またね。"))]

        result = gemini.transcribe(audio, request(), PROGRESS)

        assert transcript(result) == [
            (1.0, "S0", "おはよう。"), (2.0, "S1", "はい。"), (3.0, "S0", "またね。")]

    def test_line_without_text_is_dropped(self, gemini, genai, audio):
        # 只有時間戳或只有說話者代號的行不成為片段，也不佔說話者編號
        genai.replies = [Reply(text=(
            "[00:01.00]Speaker 1: おはよう。\n"
            "[00:02.00]\n"
            "[00:03.00]Speaker 3: \n"
            "[00:04.00]Speaker 2: はい。"))]

        result = gemini.transcribe(audio, request(), PROGRESS)

        assert transcript(result) == [(1.0, "S0", "おはよう。"), (4.0, "S1", "はい。")]

    def test_end_time_only_from_a_timestamp_line_right_after_the_text(self, gemini, genai, audio):
        # Gemini 明寫的結束時間：緊接在文字行後（中間只能有空行）、只有時間戳的行，晚於那一行的
        # 開始才算。其他片段沒有結束時間，不拿下一行的開始來猜：猜的值會被字幕當成真實的結束時間
        genai.replies = [Reply(text=(
            "[00:01.00]おはよう。\n"
            "\n"
            "[00:02.50]\n"
            "[00:03.00]\n"
            "[00:04.00]はい。\n"
            "[00:03.50]\n"
            "[00:06.00]またね。\n"
            "（笑い）\n"
            "[00:07.00]"))]

        result = gemini.transcribe(audio, request(), PROGRESS)

        assert [(s["text"], s["end"]) for s in result.segments] == [
            ("おはよう。", 2.5), ("はい。", None), ("またね。", None)]

    @pytest.mark.parametrize("reason", [types.FinishReason.SAFETY, types.FinishReason.RECITATION])
    def test_empty_response_that_stopped_early_is_a_failure(self, gemini, genai, audio, reason):
        # 沒有內容但不是正常結束：不是「那段沒人說話」，當成功的話那一段會默默不見
        genai.replies = [Reply(text="", finish_reason=reason)]

        result = gemini.transcribe(audio, request(), PROGRESS)

        assert not result.success
        assert reason.name in result.text

    def test_dropped_lines_are_logged_as_a_count_without_their_content(
            self, gemini, genai, audio, app_log):
        # 排查只能靠使用者附上的日誌（ADR-0005）：記下丟掉幾行，不記轉錄的內容
        genai.replies = [Reply(text=(
            "```lrc\n"
            "[00:01.00]おはよう。\n"
            "秘密の話\n"
            "\n"
            "[00:02.00]Speaker 3:\n"
            "```"))]

        gemini.transcribe(audio, request(), PROGRESS)

        assert any("丟掉 4 行" in message for message in app_log)
        assert not any("秘密の話" in message for message in app_log)

    @pytest.mark.parametrize("text", [
        "",
        "這段音檔聽不出任何語音。",
        "[00:05.00]\n[00:06.00]Speaker 1:",
    ], ids=["empty", "no-timestamps", "no-text"])
    def test_response_without_any_line_has_no_segments(self, gemini, genai, audio, text):
        # 這一段沒有任何帶時間戳、有文字的行（例如那段沒人說話）：算成功、沒有片段，不必切段重試。
        # text 寫為什麼沒有：整個任務合併完都沒有片段時，任務用它回報失敗
        genai.replies = [Reply(text=text, input_tokens=1000, output_tokens=200)]

        result = gemini.transcribe(audio, request(), PROGRESS)

        assert result.success
        assert result.segments == []
        assert "沒有任何帶時間戳" in result.text
        assert result.total_tokens == 1200  # 用量照樣回報


def cancellable() -> tuple[threading.Event, ProgressAndCancel]:
    """使用者可以取消的進度與取消物件：set 回傳的 Event 就是按下取消。"""
    cancel = threading.Event()
    return cancel, ProgressAndCancel(report=lambda text: None, cancel_requested=cancel.is_set)


class TestCancel:
    """使用者取消之後，音檔不再往外送、也不再送出要收費的生成請求。"""

    def test_cancelled_before_upload_sends_nothing(self, gemini, genai, audio):
        cancel, progress = cancellable()
        cancel.set()

        with pytest.raises(TranscriptionCancelledError):
            gemini.transcribe(audio, request(), progress)

        assert genai.stored == {}
        assert genai.generated == []

    def test_cancelled_while_gemini_processes_the_upload_stops_waiting(self, genai, audio):
        cancel, progress = cancellable()
        # 等 Gemini 處理上傳檔的期間，使用者按下取消
        gemini = GeminiProvider(MODEL, client=genai, sleep=lambda seconds: cancel.set())
        genai.processing_polls = 3

        with pytest.raises(TranscriptionCancelledError):
            gemini.transcribe(audio, request(), progress)
        # 不等 Gemini 處理完就停下，也沒有送出生成
        assert [f.state for f in genai.stored.values()] == [types.FileState.PROCESSING]
        assert genai.generated == []

        gemini.release()
        assert genai.stored == {}  # 已經上傳的遠端檔，任務結束時照樣刪掉

    @pytest.mark.parametrize("service_tier", [None, "flex"], ids=["standard", "flex"])
    def test_cancelled_after_the_upload_sends_no_generation(
            self, gemini, genai, audio, service_tier):
        # 上傳一處理完，使用者就按下取消
        progress = ProgressAndCancel(report=lambda text: None,
                                     cancel_requested=lambda: bool(genai.stored))

        with pytest.raises(TranscriptionCancelledError):
            gemini.transcribe(audio, request(service_tier=service_tier), progress)

        assert genai.generated == []

    def test_cancelled_while_waiting_to_retry_flex_sends_nothing_more(self, genai, audio):
        cancel, progress = cancellable()
        # Flex 回 503、等著重試的期間，使用者按下取消
        gemini = GeminiProvider(MODEL, client=genai, sleep=lambda seconds: cancel.set())
        genai.replies = [unavailable()]

        with pytest.raises(TranscriptionCancelledError):
            gemini.transcribe(audio, request(service_tier="flex"), progress)

        # 不再重試 Flex，也不退回標準
        assert genai.generated == ["flex"]

    def test_cancelled_during_the_last_flex_attempt_does_not_fall_back_to_standard(
            self, gemini, genai, audio):
        genai.overloaded = {"flex"}
        # 最後一次 Flex 送出之後，使用者按下取消
        progress = ProgressAndCancel(
            report=lambda text: None,
            cancel_requested=lambda: len(genai.generated) == FLEX_MAX_RETRIES)

        with pytest.raises(TranscriptionCancelledError):
            gemini.transcribe(audio, request(service_tier="flex"), progress)

        assert genai.generated == ["flex"] * FLEX_MAX_RETRIES


def processing_failed(genai):
    genai.processing_polls = 1
    genai.processing_fails = True


class TestRemoteFilesAreDeletedWhenTheTaskEnds:
    @pytest.mark.parametrize("setup", [
        lambda genai: None,
        lambda genai: genai.replies.append(Blocked()),
        lambda genai: genai.replies.append(invalid_argument()),
        processing_failed,
    ], ids=["succeeded", "blocked", "error", "processing-failed"])
    def test_release_deletes_every_uploaded_file(self, gemini, genai, audio, setup):
        gemini.transcribe(audio, request(), PROGRESS)  # 分段轉錄的前一段
        setup(genai)
        with suppress(GeminiPermanentError):
            gemini.transcribe(audio, request(), PROGRESS)
        assert len(genai.stored) == 2  # 任務還沒結束：兩段的遠端檔都還在

        gemini.release()

        assert genai.stored == {}


class TestFlex:
    def test_retries_retryable_errors_with_growing_waits(self, genai, audio):
        waits = []
        gemini = GeminiProvider(MODEL, client=genai, sleep=waits.append)
        genai.replies = [unavailable(), rate_limited(), Reply()]

        result = gemini.transcribe(audio, request(service_tier="flex"), PROGRESS)

        assert result.success
        assert result.service_tier_used == "flex"
        assert len(waits) == 2 and 0 < waits[0] < waits[1]

    def test_falls_back_to_standard_when_flex_stays_unavailable(self, gemini, genai, audio):
        genai.overloaded = {"flex"}

        result = gemini.transcribe(audio, request(service_tier="flex"), PROGRESS)

        assert result.success
        assert result.service_tier_used == "standard"

    def test_other_flex_errors_fall_back_without_retrying(self, gemini, genai, audio):
        # 重試 Flex 的話，第二次 Flex 會拿到 Reply，回報的就會是 flex
        genai.replies = [invalid_argument(), Reply()]

        result = gemini.transcribe(audio, request(service_tier="flex"), PROGRESS)

        assert result.service_tier_used == "standard"

    def test_transient_when_standard_is_unavailable_too(self, gemini, genai, audio):
        genai.overloaded = {"flex", "standard"}
        with pytest.raises(GeminiTransientError):
            gemini.transcribe(audio, request(service_tier="flex"), PROGRESS)

    @pytest.mark.parametrize("reply, tier_header, reported", [
        (Reply(), True, "flex"),
        (Reply(served="standard"), True, "standard"),  # API 端沒有套用 Flex
        (Reply(), False, "flex"),  # 讀不到 header：照請求端判定
    ], ids=["served-flex", "api-downgraded", "no-header"])
    def test_reports_the_processing_mode_actually_used(
            self, gemini, genai, audio, reply, tier_header, reported):
        genai.replies = [reply]
        genai.tier_header = tier_header

        result = gemini.transcribe(audio, request(service_tier="flex"), PROGRESS)

        assert result.service_tier_used == reported


class TestErrors:
    @pytest.mark.parametrize("error", [unavailable(), rate_limited()], ids=["503", "429"])
    def test_transient_errors_are_reported_as_transient(self, gemini, genai, audio, error):
        genai.replies = [error]
        with pytest.raises(GeminiTransientError):
            gemini.transcribe(audio, request(), PROGRESS)

    def test_transient_upload_error_is_reported_as_transient(self, gemini, genai, audio):
        genai.failing["files.upload"] = rate_limited()
        with pytest.raises(GeminiTransientError):
            gemini.transcribe(audio, request(), PROGRESS)

    def test_other_errors_are_permanent(self, gemini, genai, audio):
        genai.replies = [invalid_argument("API key not valid.")]
        with pytest.raises(GeminiPermanentError, match="API key not valid"):
            gemini.transcribe(audio, request(), PROGRESS)


def audio_file(tmp_path, name: str):
    path = tmp_path / name
    path.write_bytes(b"RIFF fake wav " + name.encode())
    return path


def submit(gemini, tmp_path, prompts) -> str:
    """每個提示詞配一個上傳的音檔，送出批次。"""
    requests = [(gemini.upload(audio_file(tmp_path, f"{i}.wav")), prompt)
                for i, prompt in enumerate(prompts)]
    return gemini.submit_batch(requests, display_name="transcription-test")


class TestBatch:
    def test_polls_until_succeeded_with_one_result_per_request(self, gemini, genai, tmp_path):
        genai.batch_states = ["JOB_STATE_PENDING", "JOB_STATE_RUNNING", "JOB_STATE_SUCCEEDED"]
        name = submit(gemini, tmp_path, ["轉錄 A", "轉錄 B"])

        polls = [gemini.poll_batch(name) for _ in range(3)]

        assert [(p.state, p.done) for p in polls] == [
            ("JOB_STATE_PENDING", False),
            ("JOB_STATE_RUNNING", False),
            ("JOB_STATE_SUCCEEDED", True),
        ]
        final = polls[-1]
        assert final.succeeded
        # 假用戶端把請求的提示詞當成轉錄文字：結果的順序和送出時相同
        assert [r.text for r in final.results] == ["[00:00.00]轉錄 A", "[00:00.00]轉錄 B"]
        assert [(r.success, r.total_tokens) for r in final.results] == [(True, 1200)] * 2

    @pytest.mark.parametrize("state", ["JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"])
    def test_polls_until_failed(self, gemini, genai, tmp_path, state):
        genai.batch_states = ["JOB_STATE_RUNNING", state]
        name = submit(gemini, tmp_path, ["轉錄 A"])

        assert not gemini.poll_batch(name).done
        final = gemini.poll_batch(name)

        assert (final.state, final.done, final.succeeded, final.results) == (state, True, False, ())

    def test_failed_requests_are_reported_one_by_one(self, gemini, genai, tmp_path):
        genai.batch_outcomes = {0: types.JobError(code=3, message="音檔無法解碼"), 1: Blocked()}
        name = submit(gemini, tmp_path, ["轉錄 A", "轉錄 B", "轉錄 C"])

        results = gemini.poll_batch(name).results

        assert [r.success for r in results] == [False, False, True]
        assert "音檔無法解碼" in results[0].text
        assert "PROHIBITED_CONTENT" in results[1].text
        assert results[2].text == "[00:00.00]轉錄 C"

    @pytest.mark.parametrize("operation", ["batches.create", "batches.get"])
    def test_transient_errors_are_reported_as_transient(self, gemini, genai, tmp_path, operation):
        genai.failing[operation] = unavailable()
        with pytest.raises(GeminiTransientError):
            gemini.poll_batch(submit(gemini, tmp_path, ["轉錄 A"]))

    def test_release_deletes_the_uploaded_files(self, gemini, genai, tmp_path):
        gemini.poll_batch(submit(gemini, tmp_path, ["轉錄 A", "轉錄 B"]))
        assert len(genai.stored) == 2

        gemini.release()

        assert genai.stored == {}
