"""說話者對齊的規則（#93）：哪些編號不能併、取嵌入的窗怎麼挑、門檻、編號怎麼排、不對齊時怎麼編。

一般情況（後一段的編號配回前一段、只在後一段說話的人拿新編號、嵌入用不了時的退路、接續拿到的新編號配回來）
從 API 跑完一個任務來測，見 tests/integration/test_provider_seam.py 的 TestSpeakersAcrossChunks；這裡只測
從那裡不好造出來的邊界情況。

假的嵌入照「這一窗的中點是誰在說話」回答（``voices``），同一個人給同一個向量。

沒寫結束時間的片段（Gemini 的 LRC 多半只寫開始時間，#335）怎麼取窗，見 TestSegmentsWithoutAnEnd。
"""
from pathlib import Path

import numpy as np
import pytest

from app.services import speaker_alignment
from app.services.speaker_alignment import Piece, align, converge, needs_alignment, separate

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


class TestSegmentsWithoutAnEnd:
    """Gemini 的 LRC 多半只寫開始時間（#335）。取嵌入時用同一段裡下一個片段的開始當結束，最多取一窗；最後一個
    片段取到這一段音檔的結尾。只用來挑取嵌入的聲音，片段本身照樣沒有結束時間。"""

    def test_a_segment_ends_where_the_next_one_starts(self):
        segments = [segment(0, None, "S0"), segment(3, None, "S1"), segment(5, None, "S0"),
                    segment(8, 9.5, "S1")]

        assert speaker_alignment._spans(segments, "S0") == [(0.0, 3.0), (5.0, 8.0)]
        assert speaker_alignment._spans(segments, "S1") == [(3.0, 5.0), (8.0, 9.5)]

    def test_only_the_first_window_of_a_long_gap_is_used(self):
        # 下一個片段 25 秒後才開始：中間可能有沒轉出來的別人，只取開頭的一窗
        segments = [segment(0, None, "S0"), segment(25, 27, "S1")]

        assert speaker_alignment._spans(segments, "S0") == [(0.0, speaker_alignment.WINDOW_SECONDS)]

    def test_the_last_segment_ends_with_the_audio(self):
        segments = [segment(0, None, "S0"), segment(3, None, "S1")]

        assert speaker_alignment._spans(segments, "S1", duration=7.0) == [(3.0, 7.0)]
        # 不知道音檔多長時不取
        assert speaker_alignment._spans(segments, "S1") == []

    def test_nothing_past_the_end_of_the_audio_is_used(self):
        # Gemini 寫的時間可能超過送進去的音檔：推算的結束不超過音檔的結尾，整個在結尾之後的片段不取
        segments = [segment(0, None, "S0"), segment(5, None, "S1"), segment(9, None, "S0"),
                    segment(12, None, "S1")]

        assert speaker_alignment._spans(segments, "S1", duration=7.0) == [(5.0, 7.0)]
        assert speaker_alignment._spans(segments, "S0", duration=7.0) == [(0.0, 5.0)]

    def test_a_segment_starting_at_the_same_time_does_not_end_it(self):
        # S1 在同一刻插了一句（0–1 秒）：S0 照樣到下一個比它晚開始的片段（4 秒），扣掉重疊的 0–1 秒
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


class TestConvergingToTheSpeakerCount:
    """照所選人數收斂（#377）：使用者選了 2 到 8 人、本機分出的說話者比所選多時，先把說話合計不到 10 秒或取不到
    嵌入的編號併進說最多話的那位，再照聲音相似度（平均連結）併，剩下所選人數就停。規則與數字的依據見 #353。

    這裡的片段都是同一段音檔裡、已經對齊成同一套的說話者編號；分段轉錄怎麼先對齊再收斂，見
    tests/integration/test_provider_seam.py 的 TestSpeakerCountConvergence。"""

    @staticmethod
    def voices(segments, vectors) -> dict:
        """每個片段的時間照它的說話者給向量（``vectors[編號]``）。"""
        return {FIRST: [(s["start"], s["end"], vectors[s["speaker"]]) for s in segments]}

    def test_short_speakers_go_to_whoever_speaks_most_whatever_their_voice(self):
        # S2 只說了 6 秒（不到 10 秒）：聲音和 S1 一樣，照樣併進說最多話的 S0
        segments = [segment(0, 20, "S0"), segment(21, 33, "S1"), segment(34, 40, "S2")]
        embedder = Embedder(self.voices(segments, {"S0": A, "S1": B, "S2": B}))

        assert converge([Piece(FIRST, 0.0, segments)], 2, embedder) == {
            "S0": "S0", "S1": "S1", "S2": "S0"}

    def test_short_speakers_go_from_the_least_talk_until_the_count_is_reached(self):
        # 選 3 人：說最少話的 S3（3 秒）併進 S0 就剩 3 位，S2（5 秒）留著
        segments = [segment(0, 30, "S0"), segment(31, 51, "S1"), segment(52, 57, "S2"),
                    segment(58, 61, "S3")]
        embedder = Embedder(self.voices(segments, {"S0": A, "S1": B, "S2": C, "S3": D}))

        assert converge([Piece(FIRST, 0.0, segments)], 3, embedder) == {
            "S0": "S0", "S1": "S1", "S2": "S2", "S3": "S0"}

    def test_speaker_without_an_embedding_goes_to_whoever_speaks_most(self):
        # S2 說了 12 秒，但都和 S0 同時說話：照取窗的規則一窗都沒有，取不到嵌入
        segments = [segment(0, 30, "S0"), segment(5, 17, "S2"), segment(31, 50, "S1")]
        embedder = Embedder(self.voices(segments, {"S0": A, "S1": B, "S2": C}))

        assert converge([Piece(FIRST, 0.0, segments)], 2, embedder) == {
            "S0": "S0", "S2": "S0", "S1": "S1"}

    @pytest.mark.parametrize("s2_starts, expected", [
        (39.0, "S0"),  # 和 S1 同時說話 1 秒：不併進 S1，改併第二像的 S0（0.55）
        (39.1, "S1"),  # 0.9 秒：照聲音併進最像的 S1
    ])
    def test_two_speaking_at_the_same_time_for_a_second_are_not_merged(self, s2_starts, expected):
        # S2 的聲音和 S1 最像（0.835），和 S0 第二像（0.55）
        segments = [segment(0, 20, "S0"), segment(20, 40, "S1"), segment(s2_starts, 55, "S2")]
        embedder = Embedder({FIRST: [(0, 20, voice(1, 0)), (20, 39, voice(0, 1)),
                                     (39, 55, voice(0.55, 0.835))]})

        assert converge([Piece(FIRST, 0.0, segments)], 2, embedder)["S2"] == expected

    @pytest.mark.parametrize("similarity, expected", [
        (0.45, {"S0": "S0", "S1": "S1", "S2": "S2"}),  # 最像的兩位不到 0.5：停下，比所選的 2 人多
        (0.55, {"S0": "S0", "S1": "S1", "S2": "S0"}),
    ])
    def test_stops_when_no_two_are_alike_enough(self, similarity, expected):
        segments = [segment(0, 15, "S0"), segment(16, 31, "S1"), segment(32, 47, "S2")]
        other = voice(similarity, 0, (1 - similarity ** 2) ** 0.5)
        embedder = Embedder(self.voices(segments, {"S0": voice(1, 0, 0), "S1": voice(0, 1, 0),
                                                   "S2": other}))

        assert converge([Piece(FIRST, 0.0, segments)], 2, embedder) == expected

    @pytest.mark.parametrize("speakers, expected", [
        (2, {"S0": "S0", "S1": "S1", "S2": "S0", "S3": "S1"}),
        # 選 3 人：只併最像的一對（0.9），剩 3 位就停
        (3, {"S0": "S0", "S1": "S1", "S2": "S0", "S3": "S3"}),
    ])
    def test_merges_the_most_alike_until_the_count_is_reached(self, speakers, expected):
        segments = [segment(0, 15, "S0"), segment(16, 31, "S1"), segment(32, 47, "S2"),
                    segment(48, 63, "S3")]
        embedder = Embedder(self.voices(segments, {
            "S0": voice(1, 0, 0, 0), "S1": voice(0, 1, 0, 0),
            "S2": voice(0.9, 0, 0.19 ** 0.5, 0), "S3": voice(0, 0.8, 0, 0.6)}))

        assert converge([Piece(FIRST, 0.0, segments)], speakers, embedder) == expected

    def test_merged_speakers_take_the_number_of_whoever_spoke_first(self):
        # S3 一開始說了 2 秒就併進說最多話的 S1：S1 改成 S3。S2 不動
        segments = [segment(0, 2, "S3"), segment(5, 35, "S1"), segment(36, 56, "S2")]
        embedder = Embedder(self.voices(segments, {"S1": A, "S2": B, "S3": C}))

        assert converge([Piece(FIRST, 0.0, segments)], 2, embedder) == {
            "S3": "S3", "S1": "S3", "S2": "S2"}

    def test_no_more_speakers_than_chosen_needs_no_embedding(self):
        segments = [segment(0, 3, "S0"), segment(4, 7, "S1"), segment(8, 9, None)]
        embedder = Embedder({})

        assert converge([Piece(FIRST, 0.0, segments)], 2, embedder) == {"S0": "S0", "S1": "S1"}
        assert embedder.opened == 0

    def test_failing_embedder_is_left_to_the_caller(self):
        # 嵌入用不了時不收斂：由呼叫端照原本的編號完成任務
        def broken(report):
            raise OSError("讀不到權重")

        segments = [segment(0, 15, "S0"), segment(16, 31, "S1"), segment(32, 47, "S2")]
        with pytest.raises(OSError):
            converge([Piece(FIRST, 0.0, segments)], 2, broken)

    def test_speakers_are_counted_across_pieces(self, monkeypatch):
        # 分段轉錄對齊之後的 S0 在兩段各說 6 秒，合計 12 秒，不算說太少話：照聲音和 S2 併。取嵌入的窗兩段
        # 一起從長的取起，最多 MAX_SECONDS_PER_UNIT 秒
        monkeypatch.setattr(speaker_alignment, "MAX_SECONDS_PER_UNIT", 10.0)
        pieces = [Piece(FIRST, 0.0, [segment(0, 6, "S0"), segment(7, 30, "S1")]),
                  Piece(SECOND, 30.0, [segment(0, 6, "S0"), segment(7, 20, "S1"),
                                       segment(21, 32, "S2")])]
        embedder = Embedder({FIRST: [(0, 6, A), (7, 30, B)],
                             SECOND: [(0, 6, A), (7, 20, B), (21, 32, A)]})

        assert converge(pieces, 2, embedder) == {"S0": "S0", "S1": "S1", "S2": "S0"}
        assert [(audio, spans) for audio, spans in embedder.spans if (0.0, 6.0) in spans] == [
            (FIRST, ((0.0, 6.0),)), (SECOND, ((0.0, 6.0),))]

    def test_fragments_alike_each_other_do_not_force_two_people_together(self):
        # 照 #353 的 ja5（7 人分成 14 位）：7 位真人 S0～S6 彼此的相似度只有 0.365；S3 隔一段時間後換了
        # 編號 S13（0.97）；6 個說不到 10 秒的零碎編號 S7～S12（1.5～8.4 秒）彼此很像（0.9），和真人 0.37。
        # 零碎編號先併進說最多話的 S6，再併 S3 與 S13，剛好剩 7 位。不先處理零碎編號的話，它們會併成一個
        # 「假的人」，停在 8 位（0.5 的下限擋住兩位真人互併；#353 沒有下限的做法 A 就是在這裡把真人硬併）
        basis = np.linalg.qr(np.random.default_rng(353).standard_normal((20, 20)))[0]
        common, fragment = basis[0], basis[1]
        vectors = {f"S{i}": 0.365 ** 0.5 * common + 0.635 ** 0.5 * basis[2 + i] for i in range(7)}
        vectors["S13"] = 0.97 * vectors["S3"] + (1 - 0.97 ** 2) ** 0.5 * basis[9]
        for k in range(6):
            vectors[f"S{7 + k}"] = 0.6125 * common + 0.525 ** 0.5 * fragment + 0.1 ** 0.5 * basis[10 + k]
        talk = {**{f"S{i}": 40.0 + 10 * i for i in range(7)},
                "S7": 1.5, "S8": 2.4, "S9": 3.1, "S10": 5.0, "S11": 8.2, "S12": 8.4, "S13": 30.0}
        segments, clock = [], 0.0
        for label, seconds in talk.items():
            segments.append(segment(clock, clock + seconds, label))
            clock += seconds + 1.0
        embedder = Embedder(self.voices(segments, vectors))

        merged = converge([Piece(FIRST, 0.0, segments)], 7, embedder)

        assert merged == {**{f"S{i}": f"S{i}" for i in range(7)},
                          **{f"S{7 + k}": "S6" for k in range(6)}, "S13": "S3"}
