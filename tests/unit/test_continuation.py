"""接續的規則（#94）：重疊區接不回整句時怎麼接、說話者編號沒有證據時怎麼編、接續從哪裡開始。

一般情況（停下之後還有語音就接續、重疊區只留一份、說話者對調時配回來、放棄時保留已轉的部分）從 API 跑完
一個任務來測，見 tests/integration/test_provider_seam.py 的 TestContinuation；這裡只測從那裡不好造出來的
邊界情況。
"""
import pytest

from app.core.config import get_settings
from app.services import continuation


def segment(start: float, end: float, speaker: str | None = "S0", text: str = "x") -> dict:
    return {"start": start, "end": end, "speaker": speaker, "text": text}


@pytest.fixture
def overlap(monkeypatch):
    """重疊 4 秒。"""
    monkeypatch.setattr(get_settings(), "continuation_overlap_seconds", 4.0)


class TestSplice:
    def test_without_a_common_pause_segments_go_to_the_side_of_their_middle(self):
        # 重疊區 6–12 秒一直有人說話：兩邊都沒有換句的地方，接在前段停下的 12 秒。前段 10–12 秒那句的
        # 中點在 12 秒之前，留前段的；接續段跨過 12 秒的 11–14 秒那句中點在 12 秒之後，留接續段的
        earlier = [segment(5.0, 8.0, text="前1"), segment(7.5, 10.5, "S1", "前2"),
                   segment(10.0, 12.0, text="前3")]
        later = [segment(6.0, 9.0, text="後1"), segment(8.5, 11.5, "S1", "後2"),
                 segment(11.0, 14.0, text="後3"), segment(14.5, 16.0, text="後4")]

        spliced = continuation.splice(earlier, later, overlap=(6.0, 12.0))

        assert [s["text"] for s in spliced] == ["前1", "前2", "前3", "後3", "後4"]

    def test_segments_are_kept_whole_at_the_latest_common_pause(self):
        # 兩邊都在 9 秒換句：9 秒之前用前段的，之後用接續段的，片段不切開
        earlier = [segment(6.5, 9.0, text="前1"), segment(9.5, 12.0, text="前2")]
        later = [segment(6.0, 8.9, text="後1"), segment(9.2, 12.3, text="後2")]

        spliced = continuation.splice(earlier, later, overlap=(6.0, 12.0))

        assert [s["text"] for s in spliced] == ["前1", "後2"]


class TestMatchSpeakers:
    def test_speaker_heard_only_after_the_overlap_gets_a_new_number(self):
        # 接續段的 S1 在重疊區沒有說話：沒有證據，不拿前段的 S1（可能是別人），用新的 S2
        earlier = [segment(0.0, 5.0, "S1"), segment(6.0, 9.0, "S0"), segment(9.5, 11.0, "S1")]
        later = [segment(6.0, 9.0, "S0"), segment(9.5, 11.0, "S0"), segment(13.0, 15.0, "S1")]

        assert continuation.match_speakers(earlier, later, overlap=(6.0, 12.0)) == {
            "S0": "S0", "S1": "S2"}

    def test_without_anyone_speaking_in_the_overlap_numbers_are_kept(self):
        # 重疊區只有音樂、兩邊都沒有片段：沒有可以依據的，照接續段原本的編號
        earlier = [segment(0.0, 5.0, "S0")]
        later = [segment(13.0, 15.0, "S0"), segment(15.0, 16.0, "S1")]

        assert continuation.match_speakers(earlier, later, overlap=(6.0, 12.0)) == {
            "S0": "S0", "S1": "S1"}

    def test_segments_without_a_speaker_are_left_alone(self):
        earlier = [segment(6.0, 9.0, None), segment(9.0, 11.0, "S0")]
        later = [segment(6.0, 9.0, None), segment(9.0, 11.0, "S1"), segment(12.0, 13.0, None)]

        assert continuation.match_speakers(earlier, later, overlap=(6.0, 12.0)) == {"S1": "S0"}
        spliced = continuation.splice(earlier, later, overlap=(6.0, 11.0))
        assert [s["speaker"] for s in spliced] == [None, "S0", None]


class TestOnePersonSplitInTwo:
    """#322：接續段的說話者分離把同一個人分成兩位（例如語氣在重疊區裡變了）時，兩位都配回前段的同一個
    編號；重疊區裡真的是兩個人時不併。

    重疊區 10–40 秒。前段：S0 只在重疊區之前說話，重疊區裡一直是 S1，一句一句說到 40 秒停下。"""

    EARLIER = [segment(0.0, 8.0, "S0"), segment(10.0, 16.0, "S1"), segment(17.0, 24.0, "S1"),
               segment(25.0, 31.0, "S1"), segment(32.0, 36.0, "S1"), segment(37.0, 40.0, "S1")]
    OVERLAP = (10.0, 40.0)

    def test_both_halves_keep_the_earlier_number(self):
        # ja3-jvnv：接續段把 S1 在 37 秒換語氣之前與之後分成 S0、S1。兩位都只和前段的 S1 同時說話，
        # S0 說得久、先配；S1 同時說話 3 秒、全部和前段的 S1 重疊，也沒和 S0 同時說話，是同一個人
        later = [segment(10.0, 16.0, "S0", "後1"), segment(17.0, 24.0, "S0", "後2"),
                 segment(25.0, 31.0, "S0", "後3"), segment(32.0, 36.0, "S0", "後4"),
                 segment(37.0, 40.0, "S1", "後5"), segment(41.0, 46.0, "S1", "後6")]

        assert continuation.match_speakers(self.EARLIER, later, overlap=self.OVERLAP) == {
            "S0": "S1", "S1": "S1"}
        spliced = continuation.splice(self.EARLIER, later, overlap=self.OVERLAP)
        assert [s["speaker"] for s in spliced] == ["S0", "S1", "S1", "S1", "S1", "S1", "S1"]

    @pytest.mark.parametrize("earlier, later", [
        # 新來的人在前段停下前 1 秒開口，前段的 S1 那句和他重疊 1 秒（例如時間戳對不準）：太短，不是證據
        (EARLIER, [segment(10.0, 31.0, "S0"), segment(32.0, 36.0, "S0"), segment(39.0, 42.0, "S1")]),
        # 新來的人在重疊區說了 10 秒，前段只有 3 秒認成 S1，其他時候前段沒有片段：大部分沒有證據
        (EARLIER[:3] + [segment(25.0, 29.0, "S1")],
         [segment(10.0, 16.0, "S0"), segment(17.0, 24.0, "S0"), segment(26.0, 36.0, "S1")]),
        # 兩個人搶話，前段只認出 S1：新來的人整句都和前段的 S1 重疊，但他和接續段的 S0 同時在說話，
        # 一個人不會和自己搶話
        (EARLIER, [segment(10.0, 36.0, "S0"), segment(17.0, 24.0, "S1"), segment(37.0, 40.0, "S0")]),
    ], ids=["brief", "mostly_unheard", "talking_over"])
    def test_two_different_people_are_not_merged(self, earlier, later):
        assert continuation.match_speakers(earlier, later, overlap=self.OVERLAP) == {
            "S0": "S1", "S1": "S2"}

    def test_without_enough_evidence_the_next_pair_is_matched_one_to_one(self):
        # 兩個人搶話，前段把那段大多認成 S1、只有 1 秒認成另一位 S2：新來的人不併進 S1，照一對一配 S2
        earlier = [*self.EARLIER[:2], segment(17.0, 24.0, "S1"), segment(20.0, 21.0, "S2"),
                   *self.EARLIER[3:]]
        later = [segment(10.0, 36.0, "S0"), segment(17.0, 24.0, "S1"), segment(37.0, 40.0, "S0")]

        assert continuation.match_speakers(earlier, later, overlap=self.OVERLAP) == {
            "S0": "S1", "S1": "S2"}

    def test_the_log_says_why_without_what_was_said(self, app_log):
        later = [segment(10.0, 36.0, "S0", "後1"), segment(37.0, 40.0, "S1", "後2"),
                 segment(41.0, 46.0, "S2", "後3")]

        continuation.match_speakers(self.EARLIER, later, overlap=self.OVERLAP)

        assert app_log[-1].endswith(
            "接續的說話者配對（接續段→前段）：S0→S1（同時說話 23.0 秒）；"
            "S1→S1（同時說話 3.0 秒，佔重疊區的 100%，和 S0 是同一個人）；S2→S2（新編號）")
        assert not any("後" in entry for entry in app_log)


class TestResumePoint:
    def test_overlaps_back_to_the_latest_pause_before_it(self, overlap):
        # 停在 20 秒：往前 4 秒是 16 秒，之前 2 秒內最晚的靜音是 15.5 秒
        assert continuation.resume_point(20.0, (13.0, 15.5, 16.5, 19.0)) == 15.5

    def test_without_a_pause_nearby_overlaps_by_the_setting(self, overlap):
        assert continuation.resume_point(20.0, (10.0,)) == 16.0
        assert continuation.resume_point(20.0, None) == 16.0

    def test_stopping_near_the_start_overlaps_at_most_half_of_it(self, overlap):
        # 停在 6 秒：重疊 4 秒會從 2 秒開始，最多重疊到一半，從 3 秒開始；之前的靜音不用
        assert continuation.resume_point(6.0, (2.5,)) == 3.0

    def test_is_rounded_to_milliseconds_like_the_cut(self, overlap):
        assert continuation.resume_point(20.00049, None) == 16.0
