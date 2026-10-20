"""接縫 3：Gemini 轉接器，用假的 google-genai 用戶端（#107、#110）。

只從轉接器的公開介面觀察：轉錄結果（片段）、用量、實際用到的處理模式、拋出的錯誤，
以及遠端還留著哪些檔案（假用戶端的 ``stored``，等同去 Gemini 查）。
"""
from contextlib import suppress

import pytest
from google.genai import types

from app.exceptions import GeminiPermanentError, GeminiTransientError
from app.provider.base import TranscribeRequest
from app.provider.google.provider import GeminiProvider
from tests.support.fake_genai import (
    Blocked,
    FakeGenaiClient,
    Reply,
    invalid_argument,
    rate_limited,
    unavailable,
)

MODEL = "gemini-2.5-flash"


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

        result = gemini.transcribe(audio, request())

        assert result.success
        assert transcript(result) == [(1.0, None, "こんにちは")]
        assert (result.input_tokens, result.output_tokens, result.total_tokens) == (1000, 200, 1200)
        assert result.service_tier_used == "standard"

    def test_waits_until_gemini_has_processed_the_upload(self, gemini, genai, audio):
        # 假用戶端和 Gemini 一樣：檔案還在處理中就拿來轉錄會回 400
        genai.processing_polls = 3

        assert gemini.transcribe(audio, request()).success

    def test_blocked_response_is_a_failure(self, gemini, genai, audio):
        genai.replies = [Blocked()]

        result = gemini.transcribe(audio, request())

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

        result = gemini.transcribe(audio, request())

        assert transcript(result) == [
            (1.5, None, "おはよう。"), (62.25, None, "こんにちは。"), (65.0, None, "またね。")]
        assert result.text == ""  # 不再附著 LRC 文字

    @pytest.mark.parametrize("first, second", [
        ("Speaker 1:", "Speaker 2:"),
        ("Speaker A:", "Speaker B:"),
        ("Speaker 1：", "Speaker 2："),
    ], ids=["numbers", "letters", "full-width-colon"])
    def test_speaker_labels_become_speaker_ids(self, gemini, genai, audio, first, second):
        # 同一個標記一律同一個說話者編號；沒有標記的行（例如聲響描述）沒有說話者編號
        genai.replies = [Reply(text=(
            f"[00:01.00]{first} おはよう。\n"
            f"[00:02.00]{second} こんにちは。\n"
            f"[00:03.00]{first} またね。\n"
            "[00:04.00][拍手]"))]

        result = gemini.transcribe(audio, request())

        assert transcript(result) == [
            (1.0, "S0", "おはよう。"), (2.0, "S1", "こんにちは。"), (3.0, "S0", "またね。"),
            (4.0, None, "[拍手]")]

    def test_speaker_ids_follow_the_order_labels_first_appear(self, gemini, genai, audio):
        # 不照標記上的數字：先開口的是 S0，和本機一樣；標記從 0 起算或跳號也不會缺號、撞號
        genai.replies = [Reply(text=(
            "[00:01.00]Speaker 2: おはよう。\n"
            "[00:02.00]Speaker 0: はい。\n"
            "[00:03.00]Speaker 2: またね。"))]

        result = gemini.transcribe(audio, request())

        assert transcript(result) == [
            (1.0, "S0", "おはよう。"), (2.0, "S1", "はい。"), (3.0, "S0", "またね。")]

    def test_line_without_text_is_dropped(self, gemini, genai, audio):
        # 只有時間戳或只有說話者標記的行不成為片段，也不佔說話者編號
        genai.replies = [Reply(text=(
            "[00:01.00]Speaker 1: おはよう。\n"
            "[00:02.00]\n"
            "[00:03.00]Speaker 3: \n"
            "[00:04.00]Speaker 2: はい。"))]

        result = gemini.transcribe(audio, request())

        assert transcript(result) == [(1.0, "S0", "おはよう。"), (4.0, "S1", "はい。")]

    def test_segments_have_no_end_time(self, gemini, genai, audio):
        # Gemini 的 LRC 只有開始時間：不拿下一行的開始、也不拿只有時間戳的行來猜。字幕的結束時間
        # 照輸出格式模組對沒有結束時間的片段的規則，猜的值會被當成真實的結束時間
        genai.replies = [Reply(text="[00:01.00]おはよう。\n[00:02.50]\n[00:04.00]はい。")]

        result = gemini.transcribe(audio, request())

        assert [s["end"] for s in result.segments] == [None, None]

    @pytest.mark.parametrize("text", [
        "",
        "這段音檔聽不出任何語音。",
        "[00:05.00]\n[00:06.00]Speaker 1:",
    ], ids=["empty", "no-timestamps", "no-text"])
    def test_response_without_any_line_is_a_failure(self, gemini, genai, audio, text):
        # 當成成功的話，這一段的轉錄會默默不見（分段轉錄時就是掉尾）：和本機一樣回報失敗，
        # 讓外層切段重試，或讓使用者看到原因
        genai.replies = [Reply(text=text, input_tokens=1000, output_tokens=200)]

        result = gemini.transcribe(audio, request())

        assert not result.success
        assert "沒有任何帶時間戳" in result.text
        assert result.total_tokens == 1200  # 用量照樣回報


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
        gemini.transcribe(audio, request())  # 分段轉錄的前一段
        setup(genai)
        with suppress(GeminiPermanentError):
            gemini.transcribe(audio, request())
        assert len(genai.stored) == 2  # 任務還沒結束：兩段的遠端檔都還在

        gemini.release()

        assert genai.stored == {}


class TestFlex:
    def test_retries_retryable_errors_with_growing_waits(self, genai, audio):
        waits = []
        gemini = GeminiProvider(MODEL, client=genai, sleep=waits.append)
        genai.replies = [unavailable(), rate_limited(), Reply()]

        result = gemini.transcribe(audio, request(service_tier="flex"))

        assert result.success
        assert result.service_tier_used == "flex"
        assert len(waits) == 2 and 0 < waits[0] < waits[1]

    def test_falls_back_to_standard_when_flex_stays_unavailable(self, gemini, genai, audio):
        genai.overloaded = {"flex"}

        result = gemini.transcribe(audio, request(service_tier="flex"))

        assert result.success
        assert result.service_tier_used == "standard"

    def test_other_flex_errors_fall_back_without_retrying(self, gemini, genai, audio):
        # 重試 Flex 的話，第二次 Flex 會拿到 Reply，回報的就會是 flex
        genai.replies = [invalid_argument(), Reply()]

        result = gemini.transcribe(audio, request(service_tier="flex"))

        assert result.service_tier_used == "standard"

    def test_transient_when_standard_is_unavailable_too(self, gemini, genai, audio):
        genai.overloaded = {"flex", "standard"}
        with pytest.raises(GeminiTransientError):
            gemini.transcribe(audio, request(service_tier="flex"))

    @pytest.mark.parametrize("reply, tier_header, reported", [
        (Reply(), True, "flex"),
        (Reply(served="standard"), True, "standard"),  # API 端沒有套用 Flex
        (Reply(), False, "flex"),  # 讀不到 header：照請求端判定
    ], ids=["served-flex", "api-downgraded", "no-header"])
    def test_reports_the_processing_mode_actually_used(
            self, gemini, genai, audio, reply, tier_header, reported):
        genai.replies = [reply]
        genai.tier_header = tier_header

        result = gemini.transcribe(audio, request(service_tier="flex"))

        assert result.service_tier_used == reported


class TestErrors:
    @pytest.mark.parametrize("error", [unavailable(), rate_limited()], ids=["503", "429"])
    def test_transient_errors_are_reported_as_transient(self, gemini, genai, audio, error):
        genai.replies = [error]
        with pytest.raises(GeminiTransientError):
            gemini.transcribe(audio, request())

    def test_transient_upload_error_is_reported_as_transient(self, gemini, genai, audio):
        genai.failing["files.upload"] = rate_limited()
        with pytest.raises(GeminiTransientError):
            gemini.transcribe(audio, request())

    def test_other_errors_are_permanent(self, gemini, genai, audio):
        genai.replies = [invalid_argument("API key not valid.")]
        with pytest.raises(GeminiPermanentError, match="API key not valid"):
            gemini.transcribe(audio, request())


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
