"""分段轉錄合併片段時的時間軸工具：平移與排序。

去靜音之後的時間還原由語音視圖負責，從接縫 1 測（tests/integration/test_provider_seam.py 的
TestSpeechView）。
"""
from app.services.transcription.flows import (
    order_segments,
    shift_segments,
)


class TestShiftSegments:
    def test_shifts_times_and_prefixes_key(self):
        seg = {"seg_key": "0001", "start": 1.0, "end": 2.0,
               "words": [{"text": "a", "start": 1.0, "end": 1.5}]}
        out = shift_segments([seg], 100.0, prefix="b")
        assert (out[0]["start"], out[0]["end"]) == (101.0, 102.0)
        assert out[0]["words"][0]["start"] == 101.0
        assert out[0]["seg_key"] == "b.0001"

    def test_does_not_mutate_input(self):
        seg = {"seg_key": "0", "start": 1.0, "end": 2.0}
        shift_segments([seg], 5.0, prefix="a")
        assert seg == {"seg_key": "0", "start": 1.0, "end": 2.0}

    def test_end_may_be_missing(self):
        out = shift_segments([{"seg_key": "0", "start": 1.0}], 2.0)
        assert out[0]["start"] == 3.0 and out[0].get("end") is None


class TestOrderSegments:
    def test_sorts_by_time_and_renumbers(self):
        segs = [{"seg_key": "b", "start": 5.0}, {"seg_key": "a", "start": 1.0}]
        out = order_segments(segs)
        assert [s["seg_key"] for s in out] == ["a", "b"]
        assert [s["seq"] for s in out] == [0, 1]
