"""輸出格式模組：從轉錄結果（片段）產生四種輸出格式。

期望值是本機原本會產生的輸出：LRC 照本機的斷行規則（asr._entry_to_lines，搭配真的
Qwen3-ForcedAligner 斷詞）手算，SRT／VTT／TXT 是舊的 LRC 轉換器從那份 LRC 轉出的結果。
逐字時間的 text 是對齊器的詞：標點被丟掉，漢字一字一詞，連續的假名、英數字是一詞。
「和本機原本產生的 LRC 逐字相同」那一節直接拿本機的斷行當期望值，比對隨機產生的片段。
"""
import random
import re

import pytest

from app.provider.local import asr
from app.services import output_format
from app.services.transcription.models import TranscriptionTaskResult


def formats(*segments):
    return output_format.for_result(
        TranscriptionTaskResult(success=True, segments=list(segments)))


def lrc_lines(*segments) -> list[str]:
    return formats(*segments).lrc.split("\n")


def words(*items):
    return [{"text": text, "start": start, "end": end} for text, start, end in items]


# ─── 沒有逐字時間：一段一行 ──────────────────────────────────────────────────

GREETINGS = [
    {"start": 1.5, "end": 2.8, "speaker": "S0", "text": "おはよう。"},
    {"start": 3.25, "end": 4.0, "speaker": "S1", "text": "こんにちは。"},
    {"start": 3725.5, "end": 3727.0, "speaker": "S0", "text": "またね。"},
]
GREETINGS_LRC = [
    "[00:01.50][S0] おはよう。",
    "[00:03.25][S1] こんにちは。",
    "[62:05.50][S0] またね。",
]


class TestOneLinePerSegment:
    def test_each_segment_is_one_lrc_line_with_its_speaker_label(self):
        assert lrc_lines(*GREETINGS) == GREETINGS_LRC

    def test_segment_without_speaker_has_no_label(self):
        assert lrc_lines({"start": 60.0, "end": 61.0, "speaker": None, "text": "BGMのみ"}) == [
            "[01:00.00]BGMのみ"]

    def test_lines_are_in_time_order_like_the_stored_segments(self):
        # 存片段時依開始時間排序；完成時送給畫面的輸出格式要和之後下載的一樣
        assert lrc_lines(GREETINGS[2], GREETINGS[0], GREETINGS[1]) == GREETINGS_LRC


# ─── 有逐字時間：一句一行 ────────────────────────────────────────────────────

SENTENCES = [
    {"start": 10.0, "end": 13.7, "speaker": "S0",
     "text": "おはようございます。今日は、いい天気ですね！",
     "words": words(("おはようございます", 10.08, 11.2), ("今", 11.6, 11.76),
                    ("日", 11.76, 11.92), ("は", 11.92, 12.08), ("いい", 12.4, 12.64),
                    ("天", 12.64, 12.8), ("気", 12.8, 12.96), ("ですね", 12.96, 13.6))},
    # 長音「ー」和「々」不是漢字，跟著假名算進同一個詞
    {"start": 14.0, "end": 17.0, "speaker": "S1", "text": "ラーメン食べた？人々も来た。",
     "words": words(("ラーメン", 14.08, 14.72), ("食", 14.72, 14.96), ("べた", 14.96, 15.36),
                    ("人", 15.84, 16.0), ("々も", 16.0, 16.32), ("来", 16.32, 16.56),
                    ("た", 16.56, 16.8))},
]


class TestLineBreaksFromWordTimings:
    def test_each_sentence_is_a_line_starting_at_its_first_word(self):
        assert lrc_lines(*SENTENCES) == [
            "[00:10.08][S0] おはようございます。",
            "[00:11.60][S0] 今日は、いい天気ですね！",
            "[00:14.08][S1] ラーメン食べた？",
            "[00:15.84][S1] 人々も来た。",
        ]

    def test_sentence_longer_than_12_seconds_breaks_at_reading_marks(self):
        # 整句 20.08–36.4 秒；讀點處斷開，讓每一行從第一個詞到最後一個詞不超過 12 秒
        segment = {
            "start": 20.0, "end": 36.5, "speaker": "S0",
            "text": "今日はね、ずっと待ってたんだよ、本当に、ありがとう。",
            "words": words(("今", 20.08, 20.4), ("日", 20.4, 20.56), ("はね", 20.56, 21.2),
                           ("ずっと", 22.0, 23.0), ("待", 23.0, 23.4),
                           ("ってたんだよ", 23.4, 33.0), ("本", 33.6, 34.0),
                           ("当", 34.0, 34.4), ("に", 34.4, 34.8),
                           ("ありがとう", 35.0, 36.4)),
        }
        assert lrc_lines(segment) == [
            "[00:20.08][S0] 今日はね、",
            "[00:22.00][S0] ずっと待ってたんだよ、",
            "[00:33.60][S0] 本当に、ありがとう。",
        ]

    def test_chinese_breaks_at_full_width_commas_with_one_word_per_character(self):
        segment = {
            "start": 99.8, "end": 114.2, "speaker": "S0", "text": "預算先定，再談時程。",
            "words": words(("預", 100.0, 100.5), ("算", 100.5, 101.0), ("先", 101.0, 101.5),
                           ("定", 101.5, 102.0), ("再", 108.0, 108.5), ("談", 108.5, 109.0),
                           ("時", 109.0, 109.5), ("程", 109.5, 114.0)),
        }
        assert lrc_lines(segment) == ["[01:40.00][S0] 預算先定，", "[01:48.00][S0] 再談時程。"]

    def test_punctuation_without_words_joins_the_next_line_or_the_last(self):
        # 「！？」在兩個句尾標點之間各斷一次：「？」沒有詞，併到下一行行首；結尾的「…」併到最後一行
        segment = {
            "start": 40.0, "end": 42.1, "speaker": "S0", "text": "本当！？そうなの。…",
            "words": words(("本", 40.08, 40.4), ("当", 40.4, 40.72), ("そうなの", 41.2, 42.0)),
        }
        assert lrc_lines(segment) == [
            "[00:40.08][S0] 本当！",
            "[00:41.20][S0] ？そうなの。…",
        ]

    def test_sentence_of_exactly_12_seconds_stays_one_line(self):
        # 本機用對齊器的相對時間判斷：2.40 到 14.40 秒剛好 12 秒，不斷開。
        # 存下來的是加上片段開頭的絕對時間，直接相減會是 12.000000000000002
        segment = {
            "start": 1.7, "end": 16.2, "speaker": "S1", "text": "今日はね、ずっと待ってたんだよ。",
            "words": words(("今", 4.1, 4.4), ("日", 4.4, 4.6), ("はね", 4.6, 5.2),
                           ("ずっと", 9.0, 10.0), ("待", 10.0, 10.4),
                           ("ってたんだよ", 10.4, 16.1)),
        }
        assert lrc_lines(segment) == ["[00:04.10][S1] 今日はね、ずっと待ってたんだよ。"]

    def test_words_are_matched_to_the_text_the_way_the_aligner_splits_it(self):
        # 詞是 transformers 5.13 的對齊器真的斷出來的：符號（-、♡、〜）丟掉但不讓詞斷開，
        # 全形數字和前面的假名、英文連成一詞，全形空白會斷開；〆 不是漢字，被後面的漢字隔開
        segment = {
            "start": 70.0, "end": 75.0, "speaker": "S0",
            "text": "ABC-DEFと２０２４年♡。It's　そうね！〆切は明日〜。",
            "words": words(("ABCDEFと２０２４", 70.08, 71.2), ("年", 71.2, 71.44),
                           ("It's", 72.0, 72.4), ("そうね", 72.56, 73.2),
                           ("〆", 74.0, 74.16), ("切", 74.16, 74.32), ("は", 74.32, 74.48),
                           ("明", 74.48, 74.64), ("日", 74.64, 74.8)),
        }
        assert lrc_lines(segment) == [
            "[01:10.08][S0] ABC-DEFと２０２４年♡。",
            "[01:12.00][S0] It's　そうね！",
            "[01:14.00][S0] 〆切は明日〜。",
        ]

    def test_words_that_do_not_match_the_text_leave_the_segment_one_line(self):
        # 逐字時間的詞和文字斷出來的詞對不上，就不知道哪個時間屬於哪一句：整段一行
        segment = {
            "start": 50.0, "end": 52.0, "speaker": "S0", "text": "おはよう。こんにちは。",
            "words": words(("おはよう", 50.1, 50.6), ("こんばんは", 51.0, 51.8)),
        }
        assert lrc_lines(segment) == ["[00:50.00][S0] おはよう。こんにちは。"]


# ─── 和本機原本產生的 LRC 逐字相同 ───────────────────────────────────────────

# 隨機片段的字元：漢字一字一詞；假名、英數字連在一起是一詞；斷行標點與這幾個符號不算詞，
# 符號也不會讓詞斷開（「そう♡ね」是一詞）
KANJI = "今日本当天気時程預算先定再談人来食待"
LETTERS = ("おはよう", "ございます", "そう", "なの", "ラーメン", "ASMR", "2024", "ー")
BREAK_MARKS = "。．！？!?…、，,"
SYMBOLS = "「」♡～"
# 對齊器的時間 80 毫秒一格；修正過順序的時間不一定在格上（37、113）
GAPS_MS = (0, 0, 80, 160, 400, 1200, 4000, 9600, 37)
LENGTHS_MS = (80, 160, 320, 640, 1600, 6000, 113)


def aligner_words(text: str) -> list[str]:
    """對齊器（不指定語言）在這組字元上斷出的詞；和本機一樣，先在斷行標點後補空白。"""
    kept = "".join(c for c in asr._insert_align_breaks(text) if c not in BREAK_MARKS + SYMBOLS)
    return re.findall(f"[{KANJI}]|[^{KANJI}\\s]+", kept)


def random_entry(rng: random.Random) -> dict:
    """本機轉錄出的一段：MOSS 的時間（兩位小數）與文字，加上對齊器給的段內相對時間。"""
    text = ""
    while not text:
        pools = rng.choices([KANJI, LETTERS, BREAK_MARKS, SYMBOLS, " "],
                            weights=[7, 6, 4, 1, 1], k=rng.randint(1, 30))
        text = "".join(rng.choice(pool) for pool in pools).strip()
    ms, timings = 0, []
    for word in aligner_words(text):
        ms += rng.choice(GAPS_MS)
        start_ms = ms
        ms += rng.choice(LENGTHS_MS)
        timings.append({"text": word, "start_time": round(start_ms / 1000.0, 3),
                        "end_time": round(ms / 1000.0, 3)})
    start = round(rng.uniform(0, 5000), 2)
    return {"start": start, "end": round(start + ms / 1000 + 0.5, 2),
            "speaker": rng.randint(0, 2), "text": text, "text_alt": None,
            # 強制對齊失敗的段沒有逐字時間
            "words": timings if rng.random() > 0.1 else None}


def local_provider_lrc(entries: list[dict]) -> str:
    """本機原本產生的 LRC：每一段照 asr._entry_to_lines 斷行。"""
    def count_words(text: str) -> int:
        return len(aligner_words(text))
    return "\n".join(line for entry in entries for line in asr._entry_to_lines(entry, count_words))


class TestSameLrcAsTheLocalProvider:
    """本機現在自己產生 LRC（asr._entry_to_lines），從片段產生的 LRC 必須和它逐字相同，
    所以拿它當期望值的來源；片段也用本機自己的 asr._build_segment_records 產生，和存下來的
    一樣。#110 讓本機不再產生 LRC 時，這組測試跟著刪掉。"""

    def test_random_segments_break_into_the_same_lines_at_the_same_times(self):
        rng = random.Random(109)
        for _ in range(300):
            entries = sorted((random_entry(rng) for _ in range(rng.randint(1, 4))),
                             key=lambda entry: entry["start"])
            segments = asr._build_segment_records(entries, source="moss")
            assert formats(*segments).lrc == local_provider_lrc(entries), entries

    @pytest.mark.parametrize("start, first_ms, line_count", [
        # 段內 151.6 到 163.6 秒相減剛好 12 秒，不斷開；加上片段開頭再相減會是 12.000000000000455
        (3934.3, 151600, 1),
        # 段內 13.6 到 25.6 秒相減是 12.000000000000002，本機在讀點處斷開；加上片段開頭再相減反而剛好 12
        (3365.57, 13600, 2),
    ])
    def test_12_second_limit_is_measured_on_the_aligner_times(self, start, first_ms, line_count):
        # 從第一個詞到最後一個詞 150 格（12 秒），中間有讀點可以斷開
        offsets = [("今", 0, 160), ("日", 160, 320), ("はね", 320, 800),
                   ("ずっと", 5600, 6640), ("待", 6640, 7200), ("ってたんだよ", 7200, 12000)]
        entry = {"start": start, "end": start + 200, "speaker": 1, "text_alt": None,
                 "text": "今日はね、ずっと待ってたんだよ。",
                 "words": [{"text": text, "start_time": round((first_ms + begin) / 1000.0, 3),
                            "end_time": round((first_ms + end) / 1000.0, 3)}
                           for text, begin, end in offsets]}
        lrc = formats(*asr._build_segment_records([entry])).lrc
        assert lrc == local_provider_lrc([entry])
        assert len(lrc.split("\n")) == line_count


# ─── SRT／VTT／TXT ───────────────────────────────────────────────────────────

class TestSubtitleFormats:
    def test_srt_ends_each_line_at_the_next_and_the_last_five_seconds_later(self):
        assert formats(*GREETINGS).srt == (
            "1\n00:00:01,500 --> 00:00:03,250\n[S0] おはよう。\n\n"
            "2\n00:00:03,250 --> 01:02:05,500\n[S1] こんにちは。\n\n"
            "3\n01:02:05,500 --> 01:02:10,500\n[S0] またね。\n")

    def test_vtt_has_a_header_and_dot_milliseconds(self):
        assert formats(*GREETINGS).vtt == (
            "WEBVTT\n\n00:00:01.500 --> 00:00:03.250\n[S0] おはよう。\n\n"
            "00:00:03.250 --> 01:02:05.500\n[S1] こんにちは。\n\n"
            "01:02:05.500 --> 01:02:10.500\n[S0] またね。\n")

    def test_txt_keeps_the_labelled_text_of_each_line(self):
        assert formats(*SENTENCES).txt == (
            "[S0] おはようございます。\n[S0] 今日は、いい天気ですね！\n"
            "[S1] ラーメン食べた？\n[S1] 人々も来た。")

    def test_subtitle_times_are_the_lrc_line_times(self):
        # 和以前從 LRC 轉換時相同：時間取 LRC 時間戳讀回來的值（11.60 讀回來是 11.599…）
        assert formats(*SENTENCES).srt == (
            "1\n00:00:10,080 --> 00:00:11,599\n[S0] おはようございます。\n\n"
            "2\n00:00:11,599 --> 00:00:14,080\n[S0] 今日は、いい天気ですね！\n\n"
            "3\n00:00:14,080 --> 00:00:15,839\n[S1] ラーメン食べた？\n\n"
            "4\n00:00:15,839 --> 00:00:20,839\n[S1] 人々も来た。\n")


# ─── 沒有片段：轉錄結果只有 LRC 文字（Gemini） ────────────────────────────────

class TestResultWithoutSegments:
    def test_its_lrc_is_converted_as_before(self):
        result = output_format.for_result(TranscriptionTaskResult(
            success=True, text="[00:00.50]Speaker A: こんにちは\n[00:02.00]Speaker B: はい"))
        assert result.lrc == "[00:00.50]Speaker A: こんにちは\n[00:02.00]Speaker B: はい"
        assert result.srt == ("1\n00:00:00,500 --> 00:00:02,000\nこんにちは\n\n"
                              "2\n00:00:02,000 --> 00:00:07,000\nはい\n")
        assert result.txt == "こんにちは\nはい"
