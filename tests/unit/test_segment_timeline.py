"""結構化片段的時間軸轉換。

片段與 LRC 必須走同一套轉換，否則校正介面顯示的時間會與下載的字幕不一致。
"""
import pytest

from app.services.transcription.flows import (
    order_segments,
    remap_lrc_timestamps,
    remap_segments,
    shift_segments,
    speech_time_remapper,
)

# 純語音檔＝原檔的 10-20s 與 50-60s 拼接而成
SPEECH = [{"start": 10.0, "end": 20.0}, {"start": 50.0, "end": 60.0}]


class TestSpeechTimeRemapper:
    def test_maps_into_first_segment(self):
        assert speech_time_remapper(SPEECH)(0.0) == 10.0

    def test_maps_into_second_segment(self):
        # 拼接後 10.5s 已經進入第二段（第一段長 10s）
        assert speech_time_remapper(SPEECH)(10.5) == pytest.approx(50.5)

    def test_beyond_total_clamps_to_last_end(self):
        assert speech_time_remapper(SPEECH)(99.0) == 60.0

    def test_no_segments_returns_none(self):
        assert speech_time_remapper([])(1.0) is None


class TestRemapSegments:
    def test_agrees_with_lrc_remap(self):
        lrc = "[00:10.50][S0] 測試"
        assert remap_lrc_timestamps(lrc, SPEECH).startswith("[00:50.50]")
        out = remap_segments([{"seg_key": "0000", "start": 10.5, "end": 11.0}], SPEECH)
        assert out[0]["start"] == pytest.approx(50.5)
        assert out[0]["end"] == pytest.approx(51.0)

    def test_words_are_remapped(self):
        seg = {"seg_key": "0000", "start": 0.0, "end": 1.0,
               "words": [{"text": "測", "start": 0.0, "end": 0.5}]}
        out = remap_segments([seg], SPEECH)
        assert out[0]["words"][0]["start"] == 10.0
        assert out[0]["words"][0]["end"] == pytest.approx(10.5)

    def test_no_speech_segments_drops_everything(self):
        assert remap_segments([{"seg_key": "0", "start": 1.0}], []) == []


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
