"""逐字時間的重算：校正過文字的片段，算出一組對得上校正後文字的逐字時間（#357，規格 #25）。

沒改到的字沿用原本的時間；改到的一段在前後兩個沒改到的字之間照字數平均分配，在片段的開頭或結尾時
以片段的起訖為界；整段都改掉時，整個片段的時間照字數平均分配。每個案例都檢查算出來的逐字時間和
校正後的文字對得上、落在片段的起訖之內，而且不倒退（:func:`checked`）。
"""
import random

import pytest

from app.core.word_timings import aligner_words, for_corrected_text, words_match

START, END = 10.0, 20.0


def words(*items):
    return [{"text": text, "start": start, "end": end} for text, start, end in items]


def one_by_one(text: str, start: float = 10.5, step: float = 0.5):
    """``text`` 斷出來的詞一個接一個，每個 ``step`` 秒，沒有空隙。"""
    return [{"text": word, "start": start + step * i, "end": start + step * (i + 1)}
            for i, word in enumerate(aligner_words(text))]


def checked(original_text, original_words, corrected_text, *, start=START, end=END):
    """重算，並檢查每個案例都該成立的事：詞對得上校正後的文字、時間在片段的起訖之內、不倒退。"""
    result = for_corrected_text(original_text, original_words, corrected_text, start=start, end=end)
    assert result is not None
    assert words_match(corrected_text, result)
    bound = end if end is not None else original_words[-1]["end"]
    previous_end = start
    for word in result:
        assert previous_end <= word["start"] <= word["end"] <= bound, (word, result)
        previous_end = word["end"]
    return result


def times(result):
    return [(word["text"], round(word["start"], 6), round(word["end"], 6)) for word in result]


# ─── 驗收的案例 ──────────────────────────────────────────────────────────────

class TestCorrections:
    def test_one_character_changed_takes_the_time_between_its_neighbours(self):
        original = one_by_one("今天先請王小明報告進度。")

        result = checked("今天先請王小明報告進度。", original, "今天先請王曉明報告進度。")

        # 「曉」夾在「王」的結束與「明」的開始之間，就是原本「小」的時間；其他字的時間不變
        assert times(result) == times([{**w, "text": "曉"} if w["text"] == "小" else w for w in original])

    def test_inserted_characters_share_the_gap_between_their_neighbours(self):
        original = words(("我", 10.5, 10.8), ("們", 10.8, 11.1), ("明", 11.1, 11.4), ("天", 11.4, 11.7),
                         ("開", 12.3, 12.6), ("會", 12.6, 12.9))

        result = checked("我們明天開會。", original, "我們明天下午開會。")

        assert times(result) == times(original[:4]) + [("下", 11.7, 12.0), ("午", 12.0, 12.3)] \
            + times(original[4:])

    def test_characters_inserted_between_touching_words_have_no_length(self):
        # 對齊器的詞常常一個接一個；沒改到的字不讓出時間，插進來的字就是零長度
        original = one_by_one("我們開會。")

        result = checked("我們開會。", original, "我們明天開會。")

        assert times(result) == [("我", 10.5, 11.0), ("們", 11.0, 11.5), ("明", 11.5, 11.5),
                                 ("天", 11.5, 11.5), ("開", 11.5, 12.0), ("會", 12.0, 12.5)]

    def test_deleted_characters_take_their_time_with_them(self):
        original = one_by_one("我們明天下午開會。")

        result = checked("我們明天下午開會。", original, "我們明天開會。")

        assert times(result) == times(original[:4] + original[6:])

    def test_only_punctuation_changed_keeps_every_time(self):
        original = one_by_one("今天天氣很好我們出去玩")

        result = checked("今天天氣很好我們出去玩", original, "今天天氣很好，我們出去玩！")

        assert result == original

    def test_punctuation_splitting_a_kana_run_splits_its_time_by_characters(self):
        # 「はゆっくり」是一個詞；讀點把它斷成「は」「ゆっくり」，兩個詞照字數 1:4 分原本的時間
        original = words(("今", 10.5, 10.7), ("日", 10.7, 10.9), ("はゆっくり", 10.9, 11.9),
                         ("休", 11.9, 12.1), ("んで", 12.1, 12.5))

        result = checked("今日はゆっくり休んで", original, "今日は、ゆっくり休んで")

        assert times(result) == times(original[:2]) + [("は", 10.9, 11.1), ("ゆっくり", 11.1, 11.9)] \
            + times(original[3:])

    def test_a_whole_rewrite_spreads_the_whole_segment_by_characters(self):
        original = one_by_one("今天天氣很好")

        result = checked("今天天氣很好", original, "明日は雨")

        assert times(result) == [("明", 10.0, 12.5), ("日", 12.5, 15.0), ("は", 15.0, 17.5),
                                 ("雨", 17.5, 20.0)]

    def test_a_changed_beginning_starts_at_the_segment_start(self):
        original = words(("嗯", 10.4, 10.6), ("今", 11.0, 11.3), ("天", 11.3, 11.6), ("開", 11.6, 11.9),
                         ("會", 11.9, 12.2))

        result = checked("嗯，今天開會", original, "那個，今天開會")

        assert times(result) == [("那", 10.0, 10.5), ("個", 10.5, 11.0)] + times(original[1:])

    def test_a_changed_ending_stops_at_the_segment_end(self):
        original = words(("今", 10.5, 10.8), ("天", 10.8, 11.1), ("開", 11.1, 11.4), ("會", 11.4, 11.7),
                         ("吧", 11.7, 12.0))

        result = checked("今天開會吧。", original, "今天開會囉。", end=12.5)

        assert times(result) == times(original[:4]) + [("囉", 11.7, 12.5)]

    def test_a_segment_without_an_end_stops_at_its_last_word(self):
        original = one_by_one("今天開會吧。")

        result = checked("今天開會吧。", original, "今天開會囉。", end=None)

        assert times(result)[-1] == ("囉", 12.5, 13.0)


class TestMixedScripts:
    def test_an_english_word_among_chinese_characters(self):
        original = words(("我", 10.5, 10.7), ("們", 10.7, 10.9), ("用", 10.9, 11.1),
                         ("Python", 11.3, 11.9), ("寫", 12.1, 12.3))

        result = checked("我們用 Python 寫", original, "我們用 Rust 寫")

        # 「Rust」夾在「用」的結束與「寫」的開始之間
        assert times(result) == times(original[:3]) + [("Rust", 11.1, 12.1)] + times(original[4:])

    def test_words_share_the_time_by_their_number_of_characters(self):
        # 插進來的「React」五個字、「跟」一個字：React 分到六分之五
        original = words(("我", 10.5, 10.7), ("們", 10.7, 10.9), ("用", 10.9, 11.1),
                         ("Vue", 11.7, 12.0))

        result = checked("我們用Vue", original, "我們用React跟Vue")

        assert times(result) == times(original[:3]) + [("React", 11.1, 11.6), ("跟", 11.6, 11.7)] \
            + times(original[3:])

    def test_japanese_with_an_english_word(self):
        original = words(("これは", 10.5, 11.0), ("test", 11.2, 11.6), ("です", 11.8, 12.2))

        result = checked("これは test です", original, "これは demo です")

        assert times(result) == [("これは", 10.5, 11.0), ("demo", 11.0, 11.8), ("です", 11.8, 12.2)]


class TestCannotRetime:
    def test_a_segment_without_word_timings(self):
        # Gemini 的片段沒有逐字時間，本來就是一個片段一行
        assert for_corrected_text("今日は。", None, "今日も。", start=START, end=END) is None
        assert for_corrected_text("今日は。", [], "今日も。", start=START, end=END) is None

    def test_word_timings_not_matching_the_original_text(self):
        original = words(("今", 10.5, 10.7), ("天", 10.7, 10.9))

        assert for_corrected_text("今日", original, "今天", start=START, end=END) is None

    def test_a_word_without_an_end(self):
        original = [{"text": "今", "start": 10.5, "end": None}, {"text": "天", "start": 10.7, "end": 10.9}]

        assert for_corrected_text("今天", original, "明天", start=START, end=END) is None

    @pytest.mark.parametrize("corrected", ["", "……", "！？"])
    def test_corrected_text_without_any_word(self, corrected):
        assert for_corrected_text("今天", one_by_one("今天"), corrected, start=START, end=END) is None


class TestOriginalTimesOutOfOrder:
    """原本的時間不在片段的起訖之內、或互相重疊時（本機不該產生這種時間），算出來的開始時間照樣不倒退。"""

    @staticmethod
    def starts(result):
        return [word["start"] for word in result]

    def test_first_word_before_the_segment_start(self):
        original = words(("今", 9.9, 10.2), ("天", 10.2, 10.5))

        result = for_corrected_text("今天", original, "嗯今天", start=START, end=END)

        assert times(result) == [("嗯", 9.9, 9.9), ("今", 9.9, 10.2), ("天", 10.2, 10.5)]

    def test_overlapping_words(self):
        original = words(("今", 10.5, 11.0), ("天", 10.8, 11.2))

        result = for_corrected_text("今天", original, "今明天", start=START, end=END)

        assert self.starts(result) == sorted(self.starts(result))

    def test_segment_end_before_the_last_word_end(self):
        original = words(("今", 10.5, 10.8), ("天", 10.8, 11.1))

        result = for_corrected_text("今天", original, "今天好", start=START, end=11.0)

        assert times(result)[-1] == ("好", 11.1, 11.1)


class TestUnchangedWords:
    def test_unchanged_text_gives_the_same_words(self):
        original = one_by_one("今天先請王小明報告進度。")

        assert checked("今天先請王小明報告進度。", original, "今天先請王小明報告進度。") == original

    def test_other_keys_of_kept_words_are_kept(self):
        original = [{"text": "今", "start": 10.5, "end": 10.7, "score": 0.9},
                    {"text": "天", "start": 10.7, "end": 10.9, "score": 0.8}]

        result = checked("今天", original, "今天好")

        assert result[:2] == original

    def test_a_common_character_is_not_treated_as_noise(self):
        # difflib 預設把出現很多次的元素當成雜訊、不拿來對齊；「的」在中文裡很常見，也要沿用原本的時間
        text = "的" * 120 + "我"
        original = one_by_one(text, step=0.05)

        result = checked(text, original, text + "們")

        assert result[:-1] == original


# ─── 隨機的校正 ──────────────────────────────────────────────────────────────

POOLS = ("今天先請王小明報告進度預算的部分", "おはようございますそうなのラーメン", "ASMR2024abcXYZ'",
         "。．！？!?…、，,「」♡～", "  ")


def random_text(rng: random.Random, length: int) -> str:
    return "".join(rng.choice(rng.choice(POOLS)) for _ in range(length))


def random_words(rng: random.Random, text: str, start: float):
    """``text`` 斷出來的詞，時間依序往後，詞與詞之間的空隙可能是零。"""
    result, time = [], start
    for word in aligner_words(text):
        time += rng.choice((0.0, 0.0, 0.08, 0.4))
        length = rng.choice((0.0, 0.08, 0.16, 0.64))
        result.append({"text": word, "start": time, "end": time + length})
        time += length
    return result


def random_edit(rng: random.Random, text: str) -> str:
    """換掉、插入或刪掉一到三處。"""
    for _ in range(rng.randint(1, 3)):
        at = rng.randint(0, len(text))
        cut = rng.randint(0, min(5, len(text) - at))
        text = text[:at] + random_text(rng, rng.randint(0, 5)) + text[at + cut:]
    return text


def test_random_corrections_stay_inside_the_segment_and_never_go_back():
    rng = random.Random(357)
    checked_cases = 0
    for _ in range(500):
        text = random_text(rng, rng.randint(1, 40))
        if not aligner_words(text):
            continue
        start = round(rng.random() * 100, 2)
        original = random_words(rng, text, start + rng.choice((0.0, 0.3)))
        end = original[-1]["end"] + rng.choice((0.0, 0.5))
        corrected = random_edit(rng, text)
        if not aligner_words(corrected):
            assert for_corrected_text(text, original, corrected, start=start, end=end) is None
            continue
        result = checked(text, original, corrected, start=start, end=end)
        if aligner_words(corrected) == aligner_words(text):
            assert result == original
        checked_cases += 1
    assert checked_cases > 400
