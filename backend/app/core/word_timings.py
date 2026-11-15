"""逐字時間：對齊器怎麼斷詞、逐字時間對不對得上文字，以及校正過文字的片段怎麼重算逐字時間。

本機的片段帶逐字時間（``words``）：對齊器（Qwen3-ForcedAligner）把片段文字斷成詞，每個詞一個起訖
時間。輸出格式模組（:mod:`app.services.output_format`）靠它斷句與拆字幕，繁體輸出
（:mod:`app.services.traditional_output`）換字時讓它跟著換，校正頁靠它標出正在唸的字；三處都要
照同一套規則斷詞，所以規則只寫在這裡（:func:`aligner_words`）。

校正過文字的片段（#357）：片段存的是原始轉錄，逐字時間對的是原始轉錄的文字（ADR 0011）。讀校正後
版本時，由 :func:`for_corrected_text` 算出一組對得上校正後文字的逐字時間，不寫回片段。
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Dict, List, Mapping, Optional, Sequence

_BREAK_MARK_RE = re.compile(r"([。．！？!?…、，,])")


def aligner_words(text: str) -> List[str]:
    """對齊器（Qwen3-ForcedAligner，不指定語言）把文字斷成的詞，和本機一樣先在斷行標點後補空白。

    照抄 transformers 5.13 ``Qwen3ASRProcessor.split_words_for_alignment`` 的預設規則：
    漢字一字一詞；連續的字母與數字（含假名、「ー」「々」和 '）是一個詞，遇到空白或漢字才斷開；
    標點與符號直接丟掉，也不會讓詞斷開（「ABC-DEF」是一個詞「ABCDEF」）。
    """
    words: List[str] = []
    buffer: List[str] = []

    def flush() -> None:
        if buffer:
            words.append("".join(buffer))
            buffer.clear()

    for char in _BREAK_MARK_RE.sub(r"\1 ", text).strip():
        if _is_cjk_ideograph(char):
            flush()
            words.append(char)
        elif char.isspace():
            flush()
        elif char == "'" or unicodedata.category(char)[0] in "LN":
            buffer.append(char)
    flush()
    return words


def _is_cjk_ideograph(char: str) -> bool:
    code = ord(char)
    return (0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF
            or 0x20000 <= code <= 0x2A6DF or 0x2A700 <= code <= 0x2B73F
            or 0x2B740 <= code <= 0x2B81F or 0x2B820 <= code <= 0x2CEAF
            or 0xF900 <= code <= 0xFAFF or 0x2F800 <= code <= 0x2FA1F)


def words_match(text: str, words: Sequence[Mapping[str, Any]]) -> bool:
    """逐字時間的詞和整段文字斷出來的詞（:func:`aligner_words`）一個一個相同，每個詞也都有
    起訖時間。不同時（例如對齊器的規則改了）就不知道哪個時間屬於哪一句。"""
    return ([w.get("text") for w in words] == aligner_words(text)
            and all(w.get("start") is not None and w.get("end") is not None for w in words))


def for_corrected_text(
    original_text: str,
    words: Optional[Sequence[Mapping[str, Any]]],
    corrected_text: str,
    *,
    start: float,
    end: Optional[float],
) -> Optional[List[Dict[str, Any]]]:
    """校正過文字的片段的逐字時間：和 ``corrected_text`` 斷出來的詞一個一個對得上（#357）。

    ``words`` 是片段存下來、對著原始轉錄 ``original_text`` 的逐字時間，``start``、``end`` 是片段的
    起訖。拿兩段文字斷出來的詞比對（:class:`difflib.SequenceMatcher`，依序對上最長的相同部分）：

    * 沒改到的詞沿用原本的時間（整個詞照原樣複製）。
    * 改到的一段（換掉或插進來的詞），在它前後兩個沒改到的詞之間照字數平均分配：從前一個沒改到的
      詞的結束，到後一個沒改到的詞的開始，每個字分到一樣長的時間，一個詞的時間是它的字數那麼多份。
      改到的是片段的開頭或結尾時，以片段的開始或結束為界；片段沒有結束時間時，以原本最後一個詞的
      結束為界。前後兩個詞之間沒有空隙時（對齊器的詞常常一個接一個），插進來的詞是零長度；插進
      一整句時，那一句的字幕和下一句同時開始，顯示多久照 ADR 0008 的下限。要準確的時間得重新做
      強制對齊，不在這裡做。
    * 整段都改掉時（一個詞都沒對上），整個片段的時間照字數平均分配。
    * 刪掉的詞連同它的時間一起拿掉。

    原本的時間都在片段的起訖之內、而且不倒退時，算出來的也是；原本的時間有重疊或早於片段的開始時，
    算出來的開始時間照樣不倒退。只改標點時詞都沒變，時間和原本相同；標點把連在一起的假名或英數字
    斷成兩個詞時（「はゆっくり」→「は、ゆっくり」），那兩個詞照字數分原本那個詞的時間。

    算不出來時回傳 None，片段就整段一行：原本就沒有逐字時間（Gemini），或逐字時間對不上原始轉錄的
    文字（:func:`words_match`），或校正後的文字斷不出任何詞（刪掉的片段、只剩標點）。
    """
    if not words or not words_match(original_text, words):
        return None
    new_texts = aligner_words(corrected_text)
    if not new_texts:
        return None
    old_texts = [str(word["text"]) for word in words]
    # 新的第 j 個詞沿用原本第 i 個詞的時間；autojunk 會把常出現的詞（例如「的」）當成不能對上
    kept = {block.b + offset: block.a + offset
            for block in SequenceMatcher(None, old_texts, new_texts, autojunk=False).get_matching_blocks()
            for offset in range(block.size)}
    segment_end = end if end is not None else words[-1]["end"]

    retimed: List[Dict[str, Any]] = []
    changed: List[str] = []
    for index, text in enumerate(new_texts):
        if index not in kept:
            changed.append(text)
            continue
        if changed:
            next_start = words[kept[index]]["start"]
            # 不晚於後一個詞的開始：原本的時間有重疊或早於片段開始時，開始時間也不倒退
            retimed += _spread(changed, min(_gap_start(retimed, start), next_start), next_start)
            changed = []
        retimed.append(dict(words[kept[index]]))
    if changed:
        retimed += _spread(changed, _gap_start(retimed, start), segment_end)
    return retimed


def _gap_start(retimed: Sequence[Mapping[str, Any]], segment_start: float) -> float:
    """改到的一段從哪裡開始：前一個詞的結束；前面沒有詞時是片段的開始。"""
    return retimed[-1]["end"] if retimed else segment_start


def _spread(texts: Sequence[str], start: float, end: float) -> List[Dict[str, Any]]:
    """把 ``start`` 到 ``end`` 照字數平均分給這幾個詞；``end`` 早於 ``start`` 時（片段的結束早於
    原本最後一個詞的結束）都是零長度。"""
    end = max(end, start)
    step = (end - start) / sum(len(text) for text in texts)
    spread: List[Dict[str, Any]] = []
    chars = 0
    for position, text in enumerate(texts):
        word_start = start + step * chars
        chars += len(text)
        word_end = end if position == len(texts) - 1 else start + step * chars
        spread.append({"text": text, "start": word_start, "end": word_end})
    return spread
