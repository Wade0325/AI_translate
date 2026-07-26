"""長檔切半（VAD 之後在中點靜音處對半切）的純函式測試。"""
import pytest

from app.services.transcription.flows import (
    pick_halving_split_point,
    speech_segment_boundaries,
)


class TestSpeechSegmentBoundaries:
    def test_boundaries_are_cumulative_durations(self):
        # 三個片段（拼接後長度 10s、20s、5s）→ 交界在 10s 與 30s
        segments = [
            {"start": 0.0, "end": 10.0},
            {"start": 15.0, "end": 35.0},
            {"start": 40.0, "end": 45.0},
        ]
        assert speech_segment_boundaries(segments) == [10.0, 30.0]

    def test_single_segment_has_no_boundary(self):
        assert speech_segment_boundaries([{"start": 0.0, "end": 60.0}]) == []

    def test_empty_segments(self):
        assert speech_segment_boundaries([]) == []


class TestPickHalvingSplitPoint:
    def test_picks_boundary_nearest_midpoint(self):
        # 中點 500s，候選 300/480/700 → 480 最接近
        assert pick_halving_split_point([300.0, 480.0, 700.0], 1000.0) == 480.0

    def test_excludes_degenerate_edges(self):
        # 距頭尾 1 秒內的切點視為退化，不採用
        assert pick_halving_split_point([0.5, 999.5], 1000.0) is None

    def test_no_candidates_returns_none(self):
        assert pick_halving_split_point([], 1000.0) is None

    def test_far_from_middle_still_selected(self):
        # 唯一可用的靜音點就算偏離中點也採用（遞迴會處理過長的另一半）
        assert pick_halving_split_point([100.0], 1000.0) == 100.0
