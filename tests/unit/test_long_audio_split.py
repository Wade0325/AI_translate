"""分段轉錄（在最接近中點的靜音處切成兩段）的純函式測試。

候選的靜音位置是語音視圖的靜音邊界，從接縫 1 測（tests/integration/test_provider_seam.py 的
TestSpeechView）。
"""

from app.services.transcription.flows import pick_halving_split_point


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
