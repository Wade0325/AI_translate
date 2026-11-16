"""說話者人數（app.core.speaker_count，#351）：任務紀錄存的值，以及和前端選單的對齊。"""

import re
from pathlib import Path

import pytest

from app.core import speaker_count as speakers

FRONTEND_SPEAKER_COUNT = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "utils" / "speakerCount.js"
)


class TestColumn:
    """任務紀錄存成字串：照模型判斷是 "auto"，人數是數字；人數做出來之前的任務是 NULL。"""

    @pytest.mark.parametrize("speaker_count, column", [
        ("auto", "auto"), (1, "1"), (8, "8"), (None, None)])
    def test_round_trip(self, speaker_count, column):
        assert speakers.to_column(speaker_count) == column
        assert speakers.from_column(column) == speaker_count

    @pytest.mark.parametrize("column", ["0", "9", "Auto", "two", ""])
    def test_values_only_a_hand_edited_database_has_count_as_auto(self, column):
        assert speakers.from_column(column) == speakers.AUTO


@pytest.mark.parametrize("speaker_count, count", [("auto", None), (1, None), (2, 2), (8, 8)])
def test_several_count_is_a_count_of_two_to_eight(speaker_count, count):
    """本機選 2 到 8 人時照所選人數收斂（#377）；照模型判斷與 1 人沒有要收斂到的人數。"""
    assert speakers.several_count(speaker_count) == count


def test_frontend_menu_offers_the_same_counts():
    """前端的 Speakers 選單（utils/speakerCount.js）和後端收的值相同：Auto 的值與最多的人數。"""
    source = FRONTEND_SPEAKER_COUNT.read_text(encoding="utf-8")
    auto = re.search(r"""\bAUTO_SPEAKERS\s*=\s*(['"])([^'"]+)\1""", source)
    most = re.search(r"\bMAX_SPEAKERS\s*=\s*(\d+)", source)
    assert auto and most, "speakerCount.js 讀不出 AUTO_SPEAKERS 或 MAX_SPEAKERS"
    assert (auto.group(2), int(most.group(1))) == (speakers.AUTO, speakers.MAX)
