"""說話者對齊的規則（#93）：哪些編號不能併、取嵌入的窗怎麼挑、門檻、編號怎麼排、不對齊時怎麼編。

一般情況（後一段的編號配回前一段、只在後一段說話的人拿新編號、嵌入用不了時的退路、接續拿到的新編號配回來）
從 API 跑完一個任務來測，見 tests/integration/test_provider_seam.py 的 TestSpeakersAcrossChunks；這裡只測
從那裡不好造出來的邊界情況。

假的嵌入照「這一窗的中點是誰在說話」回答（``voices``），同一個人給同一個向量。

沒寫結束時間的片段（Gemini 的 LRC 多半只寫開始時間，#335）怎麼取窗，見 TestLinesWithoutAnEnd。
"""
from pathlib import Path

import numpy as np
import pytest

from app.services import speaker_alignment
from app.services.speaker_alignment import Piece, align, needs_alignment, separate

FIRST, SECOND = Path("first.wav"), Path("second.wav")


def segment(start: float, end: float | None, speaker: str | None, key: str = "") -> dict:
    return {"start": start, "end": end, "speaker": speaker, "text": "x", "seg_key": key or f"{start:g}"}


def voice(*weights: float) -> np.ndarray:
    vector = np.asarray(weights, dtype=np.float64)
    return vector / np.linalg.norm(vector)


A, B, C, D = voice(1, 0, 0, 0), voice(0, 1, 0, 0), voice(0, 0, 1, 0), voice(0, 0, 0, 1)


class Embedder:
    """``voices[音檔]`` 是（起, 迄, 向量）：一窗的中點落在哪一段，就回那一段的向量。"""

    def __init__(self, voices: dict):
        self.voices = voices
        self.spans: list[tuple[Path, tuple]] = []
        self.opened = 0

    def __call__(self, report=None):
        self.opened += 1
        return self

    def embed(self, audio, spans):
        self.spans.append((audio, tuple(spans)))
        return [next((v for lo, hi, v in self.voices.get(audio, ()) if lo <= (s + e) / 2 < hi), None)
                for s, e in spans]


class TestWhoCanBeMerged:
    def test_two_numbers_of_one_pass_stay_apart_even_with_the_same_voice(self):
        # 後一段把同一個人分成 S0、S1（嵌入一樣）：同一次分離裡的兩個編號一定是不同的人，不併。S0 配回
        # 前一段的 S0，S1 拿新的編號
        pieces = [Piece(FIRST, 0.0, [segment(0, 3, "S0")]),
                  Piece(SECOND, 10.0, [segment(0, 3, "S0"), segment(4, 7, "S1")])]
        embedder = Embedder({FIRST: [(0, 3, A)], SECOND: [(0, 7, A)]})

        assert align(pieces, embedder) == [{"S0": "S0"}, {"S0": "S0", "S1": "S1"}]

    def test_continuation_number_seen_with_someone_in_the_same_pass_stays_apart(self):
        # 只有一段：接續 c1 裡的 S1 和 S2 同時出現（同一次分離），S2 不能併進 S1；S2 只出現在接續裡、
        # 第一次轉錄沒有它，可以和第一次轉錄的 S0 併
        pieces = [Piece(FIRST, 0.0, [
            segment(0, 3, "S0", "0000"), segment(4, 7, "S1", "0001"),
            segment(8, 11, "S1", "c1.0001"), segment(12, 15, "S2", "c1.0002")])]
        embedder = Embedder({FIRST: [(0, 3, B), (4, 11, A), (12, 15, B)]})

        assert align(pieces, embedder) == [{"S0": "S0", "S1": "S1", "S2": "S0"}]

    def test_one_piece_without_new_numbers_needs_no_embedding(self):
        pieces = [Piece(FIRST, 0.0, [segment(0, 3, "S1"), segment(4, 7, "S0")]),
                  Piece(SECOND, 10.0, [segment(0, 3, None)])]
        embedder = Embedder({})

        assert not needs_alignment(pieces)
        assert align(pieces, embedder) == [{"S1": "S1", "S0": "S0"}, {}]
        assert embedder.opened == 0

    def test_below_the_threshold_is_someone_else(self):
        # 相似度 0.6：門檻 0.5 時是同一個人，0.7 時不是
        pieces = [Piece(FIRST, 0.0, [segment(0, 3, "S0")]),
                  Piece(SECOND, 10.0, [segment(0, 3, "S0")])]
        embedder = Embedder({FIRST: [(0, 3, voice(1, 0))], SECOND: [(0, 3, voice(0.6, 0.8))]})

        assert align(pieces, embedder, threshold=0.5)[1] == {"S0": "S0"}
        assert align(pieces, embedder, threshold=0.7)[1] == {"S0": "S1"}

    def test_someone_with_only_short_turns_is_not_merged(self):
        # 後一段的 S1 只說了 0.8 秒（短於 MIN_SPAN_SECONDS）：沒有嵌入，不和任何人併，拿新的編號
        pieces = [Piece(FIRST, 0.0, [segment(0, 3, "S0"), segment(4, 7, "S1")]),
                  Piece(SECOND, 10.0, [segment(0, 3, "S0"), segment(4, 4.8, "S1")])]
        embedder = Embedder({FIRST: [(0, 3, A), (4, 7, B)], SECOND: [(0, 3, A), (4, 5, B)]})

        assert align(pieces, embedder)[1] == {"S0": "S0", "S1": "S2"}

    def test_average_linkage_needs_the_whole_group_to_agree(self):
        # 前兩段的 S0 相似度 0.8，先併成同一個人。第三段的 S0 和第一段的像（0.7）、和第二段的不像（0.13）：
        # 平均 0.42，不到門檻，算另一個人（只看最像的一個會把它併進來）
        third = Path("third.wav")
        pieces = [Piece(FIRST, 0.0, [segment(0, 3, "S0")]),
                  Piece(SECOND, 10.0, [segment(0, 3, "S0")]),
                  Piece(third, 20.0, [segment(0, 3, "S0")])]
        embedder = Embedder({FIRST: [(0, 3, voice(1, 0))], SECOND: [(0, 3, voice(0.8, 0.6))],
                             third: [(0, 3, voice(0.7, -(0.51 ** 0.5)))]})

        assert align(pieces, embedder) == [{"S0": "S0"}, {"S0": "S0"}, {"S0": "S1"}]


class TestWindows:
    def test_overlapping_speech_and_short_leftovers_are_left_out(self):
        # S0 說 0–6 秒，S1 在 2–4.5 秒插話：S0 留 0–2、4.5–6（各至少 1 秒）；S1 整段都和 S0 重疊，沒有窗
        segments = [segment(0, 6, "S0"), segment(2, 4.5, "S1"), segment(6.0, 6.5, "S0")]

        assert speaker_alignment._spans(segments, "S0") == [(0.0, 2.0), (4.5, 6.0)]
        assert speaker_alignment._spans(segments, "S1") == []

    def test_long_turns_are_cut_into_windows(self):
        # 25 秒的發言切成三個 8.33 秒的窗（不超過 WINDOW_SECONDS）
        spans = speaker_alignment._spans([segment(0, 25, "S0")], "S0")

        assert spans == pytest.approx([(0, 25 / 3), (25 / 3, 50 / 3), (50 / 3, 25)])

    def test_the_longest_turns_are_used_up_to_the_cap(self, monkeypatch):
        monkeypatch.setattr(speaker_alignment, "MAX_SECONDS_PER_UNIT", 5.0)
        segments = [segment(0, 2, "S0"), segment(3, 7, "S0"), segment(8, 11, "S0")]

        assert speaker_alignment._spans(segments, "S0") == [(3.0, 7.0), (8.0, 11.0)]



class TestLinesWithoutAnEnd:
    """Gemini 的 LRC 多半只寫開始時間（#335）。取嵌入時用同一段裡下一句的開始當結束，最多取一窗；最後一句
    取到這一段音檔的結尾。只用來挑取嵌入的聲音，片段本身照樣沒有結束時間。"""

    def test_a_line_ends_where_the_next_one_starts(self):
        segments = [segment(0, None, "S0"), segment(3, None, "S1"), segment(5, None, "S0"),
                    segment(8, 9.5, "S1")]

        assert speaker_alignment._spans(segments, "S0") == [(0.0, 3.0), (5.0, 8.0)]
        assert speaker_alignment._spans(segments, "S1") == [(3.0, 5.0), (8.0, 9.5)]

    def test_only_the_first_window_of_a_long_gap_is_used(self):
        # 下一句 25 秒後才開始：中間可能有沒轉出來的別人，只取開頭的一窗
        segments = [segment(0, None, "S0"), segment(25, 27, "S1")]

        assert speaker_alignment._spans(segments, "S0") == [(0.0, speaker_alignment.WINDOW_SECONDS)]

    def test_the_last_line_ends_with_the_audio(self):
        segments = [segment(0, None, "S0"), segment(3, None, "S1")]

        assert speaker_alignment._spans(segments, "S1", duration=7.0) == [(3.0, 7.0)]
        # 不知道音檔多長時不取
        assert speaker_alignment._spans(segments, "S1") == []

    def test_a_line_starting_at_the_same_time_does_not_end_it(self):
        # S1 在同一刻插了一句（0–1 秒）：S0 照樣到下一個比它晚開始的 4 秒，扣掉重疊的 0–1 秒
        segments = [segment(0, None, "S0"), segment(0, 1, "S1"), segment(4, 6, "S0")]

        assert speaker_alignment._spans(segments, "S0") == [(1.0, 4.0), (4.0, 6.0)]

    def test_numbers_are_matched_by_voice(self):
        # 兩段各自先聽到誰就把誰編成 S0（像 Gemini 的「Speaker 1」）：後一段先說話的是 B，配回前一段的 S1
        pieces = [Piece(FIRST, 0.0, [segment(0, None, "S0"), segment(3, None, "S1")], duration=6.0),
                  Piece(SECOND, 10.0, [segment(0, None, "S0"), segment(3, None, "S1")], duration=6.0)]
        embedder = Embedder({FIRST: [(0, 3, A), (3, 6, B)], SECOND: [(0, 3, B), (3, 6, A)]})

        assert align(pieces, embedder) == [{"S0": "S0", "S1": "S1"}, {"S0": "S1", "S1": "S0"}]
        assert embedder.spans == [(FIRST, ((0.0, 3.0),)), (FIRST, ((3.0, 6.0),)),
                                  (SECOND, ((0.0, 3.0),)), (SECOND, ((3.0, 6.0),))]


class TestNumbering:
    def test_first_piece_keeps_its_numbers_and_the_rest_follow_in_order_of_speaking(self):
        # 第一段的 S1、S0 不變（就算 S1 先說話）；後一段的兩位新人依先說話的順序拿 S2、S3
        pieces = [Piece(FIRST, 0.0, [segment(0, 3, "S1"), segment(4, 7, "S0")]),
                  Piece(SECOND, 10.0, [segment(0, 3, "S1"), segment(4, 7, "S0")])]
        embedder = Embedder({FIRST: [(0, 3, A), (4, 7, B)], SECOND: [(0, 3, C), (4, 7, D)]})

        assert align(pieces, embedder) == [{"S1": "S1", "S0": "S0"}, {"S1": "S2", "S0": "S3"}]

    def test_without_the_embedder_later_pieces_get_new_numbers(self):
        pieces = [Piece(FIRST, 0.0, [segment(0, 3, "S0"), segment(4, 7, "S1")]),
                  Piece(SECOND, 10.0, []),
                  Piece(Path("third.wav"), 20.0, [segment(0, 3, "S1"), segment(4, 7, "S0")])]

        assert separate(pieces) == [{"S0": "S0", "S1": "S1"}, {}, {"S1": "S2", "S0": "S3"}]

    def test_pieces_before_anyone_speaks_do_not_count_as_the_first(self):
        # 第一段沒有說話者（例如空段）：第二段才是第一段，它的編號不變
        pieces = [Piece(FIRST, 0.0, [segment(0, 3, None)]),
                  Piece(SECOND, 10.0, [segment(0, 3, "S1")]),
                  Piece(Path("third.wav"), 20.0, [segment(0, 3, "S0")])]

        assert separate(pieces) == [{}, {"S1": "S1"}, {"S0": "S2"}]

    def test_failing_embedder_is_left_to_the_caller(self):
        def broken(report):
            raise OSError("讀不到權重")

        pieces = [Piece(FIRST, 0.0, [segment(0, 3, "S0")]),
                  Piece(SECOND, 10.0, [segment(0, 3, "S0")])]
        with pytest.raises(OSError):
            align(pieces, broken)

    def test_the_embedder_tells_the_user_what_it_is_doing(self):
        # 例如第一次用時下載權重：建立說話者嵌入時拿到的 report 就是 align 的 report
        reports: list[str] = []
        embedder = Embedder({FIRST: [(0, 3, A)], SECOND: [(0, 3, A)]})

        def downloading(report):
            report("下載權重...")
            return embedder(report)

        pieces = [Piece(FIRST, 0.0, [segment(0, 3, "S0")]),
                  Piece(SECOND, 10.0, [segment(0, 3, "S0")])]
        assert align(pieces, downloading, report=reports.append) == [{"S0": "S0"}, {"S0": "S0"}]
        assert reports == ["下載權重..."]
