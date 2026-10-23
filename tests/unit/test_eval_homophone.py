"""評測工具（tools/eval）的口音同音判斷：錯誤分類「口音同音」靠它。

台灣國語口音常把捲舌與平舌、後鼻音與前鼻音、n 與 l 混在一起；音位合併後完全相等才算
同音，比用編輯距離設門檻更能擋掉過度判定。案例和 ``python -m tools.eval selftest`` 共用
（``tools/eval/selftest.py``），全是自造的例句，不取自任何真實錄音。
"""
import pytest

from tools.eval import selftest
from tools.eval.phon import homophone


@pytest.mark.parametrize(("heard", "meant"), selftest.HOMOPHONES)
def test_accent_merged_syllables_count_as_homophones(heard, meant):
    assert homophone(heard, meant)


@pytest.mark.parametrize(("a", "b"), selftest.NOT_HOMOPHONES)
def test_near_misses_outside_the_merge_rules_are_not_homophones(a, b):
    assert not homophone(a, b)
