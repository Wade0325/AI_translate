"""繁體輸出：中文的轉錄結果一律以台灣的繁體字形與用詞呈現（ADR-0002；規則由 #14 決定）。

任務完成時（:mod:`app.tasks.lifecycle`）對轉錄結果的片段做這一步，單檔任務與批次的檔案都一樣。
四種輸出格式、凍結的原始轉錄副本與存下的片段都從轉換後的片段產生，所以原始轉錄就是使用者看到、
會去校正的繁體版本（ADR-0007）。規則：

1. 台灣字形與台灣用詞：照 OpenCC 的 s2twp（软件→軟體、信息→資訊、视频→影片）。逐字稿因此寫
   台灣用詞，不一定是講者原本說的詞；s2twp 不看語意，也會改錯（支持→支援、菜单→選單），這是定案
   時接受的代價。評測量的是轉換前的結果（#242），這一步由單元測試把關。
2. 已經是台灣用詞的不再換：台灣講者說的「演算法」，本機的模型照寫，s2twp 卻會把裡面的「算法」
   再換一次，寫成「演演算法」（運算子→運運算元、真實模式→真真實模式也是）。所以 TWPhrases 的詞
   落在字典裡的某個台灣用詞裡面時不換（:func:`_phrase_matches`）。只有這裡和 s2twp 不同；本身
   也是台灣用詞的「程序」「文件」因此照講者說的寫，不換成「程式」「檔案」。
3. 看輸出的語言：有翻譯時是目標語言，不然是音檔的語言。中文（``zh`` 開頭，含舊的 ``zh-CN``）、
   ``auto`` 與沒指定的才可能轉；日文與其他語言一律不轉。
4. 假名安全網：整份的假名占漢字加假名的 :data:`KANA_SHARE` 以上，看得出是日文，整份不轉；其餘
   片段裡含假名的（例如引用日文）也不轉。日文漢字不能被轉（会社→會社）。轉錄頁的預設語言是中文，
   使用者忘了改就轉日文檔時，靠的是這一條。
5. 簡轉繁只轉簡體的部分：簡繁通用的字（里、余、干、范、面）在已經是繁體的句子裡再轉一次會被改壞
   （里長→裡長、余先生→餘先生）。所以整份的簡體專用字比繁體專用字多時（本機的模型寫簡體），每個
   片段整段轉；不然（Gemini 照提示詞寫了繁體），簡體專用字比繁體專用字多的片段整段轉，其餘片段
   只換簡體專用字。台灣用詞與台灣異體字（裏→裡）則每個片段都換，同一段音檔不論用本機還是 Gemini，
   用詞都一致。
6. 簡轉繁把簡體的「台」一律寫成「臺」，這裡寫回「台」：台灣日常寫「台」。颱風、吧檯照 OpenCC，
   台式机照 TWPhrases 整個詞換成桌上型電腦。

s2twp 是三步：簡轉繁（s2t：STPhrases 與 STCharacters，一個字換一個字）、台灣用詞（TWPhrases，
詞的長度可能改變：博客→部落格）、台灣異體字（TWVariants，一個字換一個字）。這裡自己一步一步做，
才能在第一步留下繁體裡的原字、最後寫回「台」，也才知道原文每一塊換成了什麼（:data:`_Piece`），
讓逐字時間的詞跟著換：一個字換一個字或用詞的長度不變（信息→資訊）時，詞照位置換字、時間不變；
用詞的長度變了時，換成新詞斷出來的詞，平分原本那幾個詞的時間。換完的詞仍和片段文字對得上，
下載時照樣用逐字時間斷行。

簡體專用字是 OpenCC 字典裡一定要換成別的字的簡體字（们→們），繁體專用字反過來（們→们）；簡繁
通用的字兩邊都不算。

OpenCC 用評測工具同一個套件 ``opencc-python-reimplemented``（見 requirements-dev.txt 的註解）。
台灣用詞照它選詞的方式找（:func:`_phrase_matches`），測試檢查沒有台灣用詞的文字，三步的結果和
它的 s2twp 相同。
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

import opencc

from app.services import output_format
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

KANA_SHARE = 0.1
"""整份轉錄結果的假名占漢字加假名到這個比例，就當成日文、整份不轉。"""

# 平假名、片假名的字母（不含中文也會用的「・」與「ー」）、片假名音標擴充與半形片假名
_KANA_RE = re.compile(r"[ぁ-ゖァ-ヺㇰ-ㇿｦ-ﾝ]")
# CJK 統一表意文字、擴充 A 與相容表意文字；只用來算假名的比例
_HAN_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")

_Piece = Tuple[int, int, str]
"""原文的 ``text[start:end]`` 換成的文字：沒換成用詞的字一個字一塊，換成用詞的整個詞一塊。"""


def convert(
    segments: Sequence[Dict[str, Any]],
    *,
    source_lang: str,
    target_lang: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """把轉錄結果的片段轉成繁體輸出（規則見檔頭），回傳新的片段，不改傳進來的。

    片段的 ``text`` 與 ``text_alt``（第二假設）都轉，逐字時間的詞跟著 ``text``。不必轉的片段原樣
    放進回傳的清單。
    """
    if not _may_be_chinese(source_lang, target_lang):
        return list(segments)
    whole = "".join(segment.get("text") or "" for segment in segments)
    if _looks_japanese(whole):
        logger.info("繁體輸出：轉錄結果看得出是日文，不轉")
        return list(segments)
    whole_is_simplified = _is_simplified(whole)
    converted = [_converted_segment(segment, whole_is_simplified) for segment in segments]
    changed = sum(new is not old for new, old in zip(converted, segments, strict=True))
    logger.info(f"繁體輸出：整份以{'簡體' if whole_is_simplified else '繁體'}為主，"
                f"轉了 {changed}/{len(segments)} 個片段")
    return converted


def _may_be_chinese(source_lang: str, target_lang: Optional[str]) -> bool:
    """輸出的語言是中文、auto 或沒指定；有翻譯時看目標語言（判斷翻譯的條件和提示詞相同）。"""
    language = target_lang if target_lang and target_lang != source_lang else source_lang
    language = (language or "").strip().lower()
    return language in ("", "auto") or language.startswith("zh")


def _looks_japanese(text: str) -> bool:
    kana = len(_KANA_RE.findall(text))
    han = len(_HAN_RE.findall(text))
    return kana > 0 and kana >= KANA_SHARE * (kana + han)


def _is_simplified(text: str) -> bool:
    """簡體專用字比繁體專用字多。"""
    simplified, traditional = _simplified_only(), _traditional_only()
    return sum(c in simplified for c in text) > sum(c in traditional for c in text)


def _converted_segment(segment: Dict[str, Any], whole_is_simplified: bool) -> Dict[str, Any]:
    """轉換一個片段；沒有要換的字時回傳原本的片段。"""
    text = segment.get("text") or ""
    pieces = _pieces(text, whole_is_simplified)
    new_text = _joined(pieces)
    alt = segment.get("text_alt")
    new_alt = _joined(_pieces(alt, whole_is_simplified)) if alt else alt
    if new_text == text and new_alt == alt:
        return segment
    updated = {**segment, "text": new_text}
    if "text_alt" in segment:
        updated["text_alt"] = new_alt
    if segment.get("words") and new_text != text:
        updated["words"] = _converted_words(segment["words"], text, pieces)
    return updated


def _joined(pieces: Sequence[_Piece]) -> str:
    return "".join(new for _, _, new in pieces)


def _pieces(text: str, whole_is_simplified: bool) -> List[_Piece]:
    """轉換一段文字，回傳原文每一塊換成的文字；含假名的不轉。"""
    if not text or _KANA_RE.search(text):
        return [(0, len(text), text)]
    glyphs = _glyphs(text, whole_is_simplified or _is_simplified(text))
    if len(glyphs) != len(text):
        # s2t 的字典一個字換一個字（測試檢查過），不會走到這裡；萬一換了字典，整段當成一塊
        return [(0, len(text), _joined(_taiwan_pieces(glyphs, glyphs)))]
    return _taiwan_pieces(text, glyphs)


def _glyphs(text: str, simplified: bool) -> str:
    """簡轉繁：簡體的文字整段轉；繁體的文字只換簡體專用字，簡繁通用的字留原字。"""
    if not simplified and not any(c in _simplified_only() for c in text):
        return text
    out = _s2t().convert(text)
    if simplified or len(out) != len(text):
        return out
    return "".join(new if original in _simplified_only() else original
                   for original, new in zip(text, out, strict=True))


def _taiwan_pieces(text: str, glyphs: str) -> List[_Piece]:
    """台灣用詞與台灣異體字。``glyphs`` 是簡轉繁後的 ``text``，一個字對一個字。

    TWPhrases 的詞整個換掉，其餘一個字一塊；簡轉繁寫成「臺」的「台」寫回「台」。用詞裡的
    「臺」（臺式機）要等用詞換完才寫回，不然就找不到這個詞。
    """
    matches = {start: (end, phrase) for start, end, phrase in _phrase_matches(glyphs)}
    variants = _tw_variants()
    pieces: List[_Piece] = []
    position = 0
    while position < len(glyphs):
        if position in matches:
            end, phrase = matches[position]
            pieces.append((position, end, phrase.translate(variants)))
            position = end
            continue
        char = glyphs[position].translate(variants)
        if text[position] == "台" and char == "臺":
            char = "台"
        pieces.append((position, position + 1, char))
        position += 1
    return pieces


def _phrase_matches(text: str) -> List[_Piece]:
    """TWPhrases 的詞在文字裡的位置與要換成的詞。

    照 ``opencc-python-reimplemented`` 選詞的方式：最長的詞先選，一樣長時先選左邊的，和已經選了
    的詞重疊的不選。它先在標點與空白處斷開再找，字典裡的詞沒有這些字（測試檢查過），結果一樣。
    和它不同的只有一點：落在台灣用詞裡面的詞不選（檔頭規則 2）。
    """
    phrases, longest = _tw_phrases()
    reach = _taiwan_word_reach(text)
    found = [(start, start + length)
             for length in range(longest, 0, -1)
             for start in range(len(text) - length + 1)
             if text[start:start + length] in phrases and reach[start] < start + length]
    taken = [False] * len(text)
    matches: List[_Piece] = []
    for start, end in found:
        if not any(taken[start:end]):
            taken[start:end] = [True] * (end - start)
            matches.append((start, end, phrases[text[start:end]]))
    return sorted(matches)


def _taiwan_word_reach(text: str) -> List[int]:
    """每個位置之前（含）開始的台灣用詞最遠到哪裡：``text[start:end]`` 落在某個台灣用詞裡面，
    就是 ``reach[start] >= end``。"""
    words, longest = _taiwan_words()
    reach: List[int] = []
    farthest = 0
    for start in range(len(text)):
        for length in range(1, min(longest, len(text) - start) + 1):
            if text[start:start + length] in words:
                farthest = max(farthest, start + length)
        reach.append(farthest)
    return reach


def _converted_words(words: Sequence[Mapping[str, Any]], text: str,
                     pieces: Sequence[_Piece]) -> List[Dict[str, Any]]:
    """逐字時間的詞照它在片段文字裡的位置跟著換（規則見檔頭）。

    詞是對齊器從片段文字依序取出的字（標點丟掉）。換不了時原樣留著，下載時就整段一行：詞對不上
    片段文字（例如對齊器的規則改了，輸出格式本來就不用它斷行），或一個詞只有一部分換成了長度
    不同的用詞（MySQL注入→MySQL隱碼攻擊，「MySQL」是一個詞）。
    """
    unchanged = [dict(word) for word in words]
    # 原文每個字在哪一塊、換成哪個字；換成長度不同的用詞的字沒有對應的字（空字串）
    piece_at = [index for index, (start, end, _) in enumerate(pieces) for _ in range(start, end)]
    char_at = [new[offset] if len(new) == end - start else ""
               for start, end, new in pieces for offset in range(end - start)]
    # 依序放：照位置換好字的詞，或落在同一個長度不同的用詞裡、要一起換的詞（記著是哪一塊）
    runs: List[Tuple[Optional[int], List[Mapping[str, Any]]]] = []
    position = 0
    for word in words:
        word_text = word.get("text")
        if word_text is None:
            runs.append((None, [dict(word)]))
            continue
        places: List[int] = []
        for char in word_text:
            position = text.find(char, position)
            if position < 0:
                return unchanged
            places.append(position)
            position += 1
        if all(char_at[place] for place in places):
            runs.append((None, [{**word, "text": "".join(char_at[place] for place in places)}]))
            continue
        index = piece_at[places[0]]
        if char_at[places[0]] or any(piece_at[place] != index for place in places):
            return unchanged
        if runs and runs[-1][0] == index:
            runs[-1][1].append(word)
        elif any(other == index for other, _ in runs):
            return unchanged
        else:
            runs.append((index, [word]))

    converted: List[Dict[str, Any]] = []
    for index, run in runs:
        if index is None:
            converted.extend(dict(word) for word in run)
            continue
        spread = _spread(run, pieces[index][2])
        if spread is None:
            return unchanged
        converted.extend(spread)
    # 原本對得上片段文字的詞，換完也要對得上，不然寧可原樣留著
    if ([word.get("text") for word in words] == output_format.aligner_words(text)
            and [word["text"] for word in converted]
            != output_format.aligner_words(_joined(pieces))):
        return unchanged
    return converted


def _spread(words: Sequence[Mapping[str, Any]], phrase: str) -> Optional[List[Dict[str, Any]]]:
    """換成長度不同的用詞：換成它斷出來的詞，平分原本那幾個詞從頭到尾的時間。"""
    if any(word.get("start") is None or word.get("end") is None for word in words):
        return None
    start, end = min(word["start"] for word in words), max(word["end"] for word in words)
    texts = output_format.aligner_words(phrase)
    step = (end - start) / len(texts) if texts else 0.0
    return [{**words[0], "text": word_text, "start": start + step * i,
             "end": end if i == len(texts) - 1 else start + step * (i + 1)}
            for i, word_text in enumerate(texts)]


@cache
def _s2t() -> opencc.OpenCC:
    return opencc.OpenCC("s2t")


@cache
def _tw_phrases() -> Tuple[Dict[str, str], int]:
    """TWPhrases 的詞換成第一個候選（和 OpenCC 一樣），加上最長的詞有幾個字。"""
    phrases = {key: candidates[0] for key, candidates in _dictionary("TWPhrases.txt").items()}
    return phrases, max(map(len, phrases))


@cache
def _taiwan_words() -> Tuple[FrozenSet[str], int]:
    """TWPhrases 換上的台灣用詞（換成自己的不算），加上最長的有幾個字。"""
    words = frozenset(word for key, word in _tw_phrases()[0].items() if word != key)
    return words, max(map(len, words))


@cache
def _tw_variants() -> Dict[int, str]:
    """TWVariants 的字換成第一個候選，給 :meth:`str.translate` 用；字典一個字換一個字（測試檢查過）。"""
    return {ord(key): candidates[0]
            for key, candidates in _dictionary("TWVariants.txt").items() if len(key) == 1}


def _simplified_only() -> FrozenSet[str]:
    return _changing_chars("STCharacters.txt")


def _traditional_only() -> FrozenSet[str]:
    return _changing_chars("TSCharacters.txt")


@cache
def _changing_chars(dictionary: str) -> FrozenSet[str]:
    """OpenCC 字典裡一定要換成別的字的單字：候選裡沒有它自己（们→們）；里→里 裡 這種不算。"""
    return frozenset(key for key, candidates in _dictionary(dictionary).items()
                     if len(key) == 1 and key not in candidates)


def _dictionary(name: str) -> Dict[str, List[str]]:
    """讀 OpenCC 的字典：每一行是詞、tab、空白隔開的候選。"""
    path = Path(opencc.__file__).parent / "dictionary" / name
    entries: Dict[str, List[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, _, candidates = line.strip().partition("\t")
        if key:
            entries[key] = candidates.split(" ")
    return entries
