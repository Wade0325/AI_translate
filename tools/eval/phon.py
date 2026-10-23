"""台灣國語口音感知的拼音正規化：錯誤分類「口音同音」用它判斷兩段文字是否同音。

把實際會混淆的音位合併，合併後要求 **完全相等** 才視為同音。比起用編輯距離設門檻，
這能擋掉絕大多數過度判定。聲調不計。
"""

from __future__ import annotations

from pypinyin import Style, lazy_pinyin

# 台灣國語最常見的音位合併（依序套用，長的先換）
MERGE_RULES = [
    ("zh", "z"), ("ch", "c"), ("sh", "s"),   # 捲舌 → 平舌
    ("eng", "en"), ("ing", "in"),            # 後鼻音 → 前鼻音
    ("uen", "un"), ("iou", "iu"), ("uei", "ui"),
]



def norm_syllable(s: str) -> str:
    s = s.lower()
    for a, b in MERGE_RULES:
        s = s.replace(a, b)
    if s.startswith("n"):  # n- / l- 不分
        s = "l" + s[1:]
    return s


def norm_pinyin(text: str) -> tuple[str, ...]:
    """回傳正規化後的音節 tuple；非漢字轉小寫原樣。"""
    return tuple(
        norm_syllable(p)
        for p in lazy_pinyin(text, style=Style.NORMAL, errors=lambda x: x.lower())
    )


def homophone(a: str, b: str) -> bool:
    return norm_pinyin(a) == norm_pinyin(b)
