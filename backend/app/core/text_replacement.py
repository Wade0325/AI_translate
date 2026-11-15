"""校正頁的尋找與全部取代怎麼比對文字（#356）。

比對的規則（#345 第 8 節）：

* 一般文字比對，不支援正規表示式：``.``、``*``、``(`` 都是普通的字。
* 英文不分大小寫：A–Z 和 a–z 當成同一個字，全形的 Ａ–Ｚ 和 ａ–ｚ 也是。全形與半形當成不同的字（``Ａ`` 和
  ``A`` 不同），其他文字照原樣比對。只換英文字母，換過之後字數不變，找到的位置就是原本文字裡的位置。
* 從左到右找，找到的不重疊：在「啊啊啊」裡找「啊啊」只有一處。

前端照同一套規則算符合的片段數與全部取代會改到幾處（``frontend/src/utils/segmentSearch.js``，函式名稱相同），
兩邊用同一份案例測試（``tests/fixtures/replace_all/cases.json``），確認前端算的和伺服器實際改到的一致。
"""

from __future__ import annotations

from typing import List, Tuple

_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_UPPER_TO_LOWER = str.maketrans(
    _LETTERS + "".join(chr(ord(c) + 0xFEE0) for c in _LETTERS),
    _LETTERS.lower() + "".join(chr(ord(c) + 0xFEE0) for c in _LETTERS.lower()),
)
"""半形的 A–Z 換成 a–z，全形的 Ａ–Ｚ 換成 ａ–ｚ（全形字母是半形加 0xFEE0）。"""


def _folded(text: str) -> str:
    """英文字母換成小寫（半形換成半形、全形換成全形），其他字不動（字數不變）。"""
    return text.translate(_UPPER_TO_LOWER)


def find_occurrences(text: str, query: str) -> List[Tuple[int, int]]:
    """``query`` 在 ``text`` 裡出現的每一處，(開始, 結束) 的位置，從左到右、不重疊。``query`` 是空的時沒有。"""
    if not query:
        return []
    haystack, needle = _folded(text), _folded(query)
    found: List[Tuple[int, int]] = []
    at = haystack.find(needle)
    while at >= 0:
        found.append((at, at + len(needle)))
        at = haystack.find(needle, at + len(needle))
    return found


def replace_occurrences(text: str, query: str, replacement: str) -> Tuple[str, int]:
    """把 ``text`` 裡每一處 ``query`` 換成 ``replacement``（照打的字放進去，不跟著原本的大小寫），
    回傳換好的文字與換了幾處。取代的文字裡又含有 ``query`` 時不會再換一次。"""
    found = find_occurrences(text, query)
    if not found:
        return text, 0
    pieces: List[str] = []
    pos = 0
    for start, end in found:
        pieces.append(text[pos:start])
        pieces.append(replacement)
        pos = end
    pieces.append(text[pos:])
    return "".join(pieces), len(found)
