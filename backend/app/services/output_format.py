"""輸出格式模組：給任務、輸出格式與版本，回傳檔案內容。

資料來源：

* 有片段的任務從片段產生。
* 沒有片段的任務（片段上線前的任務、#110 之前的 Gemini 任務、#115 之前批次裡的任務）退回解析
  存下來的 LRC：LRC、TXT 和以前相同，SRT／VTT 的結束時間照下面同一套規則。
* 存下來的 LRC 是凍結的原始轉錄副本（ADR-0007）：任務完成時從轉錄結果產生（:func:`for_result`），
  和下載的 LRC 相同；有片段時下載不讀它。#154 之前存的副本差在一點：秒數取到 0.01 是 60 的行
  寫成 [00:60.00] 這種時間戳，下載寫成下一分鐘的 [01:00.00]（見 :func:`_lrc_timestamp`）。

#110 之前的副本是供應商自己寫的 LRC。Gemini 任務的副本就是 Gemini 寫的 LRC（「Speaker 1:」、
三位小數的時間戳、沒有時間戳的行都在）。本機任務的副本和這裡斷行相同（見 :func:`_segment_lines`），
刻意不同的只有片段文字裡的換行收成空白（見 :func:`_one_line`），以及和上面一樣的 [00:60.00]；
沒去靜音也沒切段的任務，除了這兩點，副本和下載逐字相同。去靜音或切段過的任務，副本另外經過
分段轉錄對 LRC 文字做的時間處理，和下載還有這些差異：

* 時間戳差 0.01 秒：去靜音的時間還原把秒數捨去到 0.01，切段的後段平移時又四捨五入一次。
  去靜音的任務約一半的行。
* 在讀點多斷一行：一句中間有讀點、又有被剪掉的靜音時，這裡量的是原音檔時間軸上的長度，
  靜音讓它超過 12 秒就在讀點斷開；本機量的是剪掉之後的長度。和句子實際講多久無關。
* 有聲段交界的整段跳動：行開頭落在交界時，時間可能跳過一整段被剪掉的靜音，往前往後都會。
  副本先四捨五入才還原時間，交界前 0.005 秒內就跳到靜音之後；#111 之前存的片段也可能因為
  浮點誤差落在交界的另一邊。之後存的片段，交界上的開始算後一段、結束算前一段，不會跳動（見
  :mod:`app.services.silence_removal`）。
* 換行後的文字：副本還原時間時只留有時間戳的行，換行後的文字被丟掉；這裡收成空白留著。

除了交界的跳動，這些差異都出在舊的處理，這裡的結果比較準。

版本目前只有原始轉錄，校正後版本留給 v0.2。

四種格式由同一串行產生，說話者標記一律「[S0] 文字」：LRC 一行一個時間戳；TXT 只留文字；
SRT／VTT 另有結束時間，照實際說話的時間顯示（ADR-0008，規則見 :func:`_subtitles`）：不同說話者
的字幕可以重疊，同一位說話者的不疊，每一行至少 0.8 秒，字幕依開始時間排序。有片段的任務和沒有
片段的任務（從存下來的 LRC 轉換）用同一套規則。SRT／VTT 的開始時間取 LRC 時間戳的值（0.01 秒），
和以前從 LRC 轉換時一樣；開始與結束時間都四捨五入到毫秒（見 :func:`_milliseconds`）。斷行的規則見
:func:`_segment_lines`。

SRT／VTT 和其他兩種格式不同的地方只有兩點（#12）：超過兩行的量的行用逐字時間拆成數則字幕
（見 :func:`_subtitle_pieces`），以及依說話者上色（見 :data:`SPEAKER_COLORS`）。LRC、TXT 不能
上色，也不拆。文字只有 VTT 跳脫（#24，見 :func:`_vtt`）；SRT 沒有跳脫的寫法，和 LRC、TXT 一樣
照原樣寫（見 :func:`_srt`）。
"""

from __future__ import annotations

import html
import re
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database.models import TranscriptionLog
from app.repositories.history_repository import HistoryRepository
from app.repositories.transcript_segment_repository import TranscriptSegmentRepository
from app.services.transcription.models import TranscriptionTaskResult
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


class OutputFormat(StrEnum):
    SRT = "srt"
    VTT = "vtt"
    LRC = "lrc"
    TXT = "txt"


class Version(StrEnum):
    ORIGINAL = "original"
    """原始轉錄。校正後版本（v0.2）加在這裡。"""


class OutputFiles(BaseModel):
    """一份轉錄結果的四種輸出格式的檔案內容。"""

    lrc: str
    srt: str
    vtt: str
    txt: str


# ─── 介面 ────────────────────────────────────────────────────────────────────

def for_task(
    db: Session,
    task: TranscriptionLog,
    fmt: OutputFormat,
    version: Version = Version.ORIGINAL,
) -> Optional[str]:
    """給定任務、輸出格式與版本，回傳檔案內容。

    任務沒有轉錄結果（沒有片段，也沒有存下來的 LRC）時回傳 None；沒有片段的任務，存下來的
    LRC 解析不出任何一行時，SRT／VTT／TXT 是空字串。版本目前只有原始轉錄一種。
    """
    segments = TranscriptSegmentRepository.segments_for_task(db, task.task_uuid)
    if segments:
        return _render(_lines(segments), fmt)
    stored_lrc = HistoryRepository().resolve_lrc_content(db, task, backfill=True)
    if not stored_lrc:
        return None
    return getattr(convert_from_lrc(stored_lrc), fmt.value)


def for_result(result: TranscriptionTaskResult) -> OutputFiles:
    """一份轉錄結果的四種輸出格式：任務完成時送給畫面，凍結的原始轉錄副本也是這裡的 LRC。

    從片段產生，和之後下載的內容相同；轉錄結果的 text 不讀。沒有任何一行時四種都是空的。
    """
    lines = _lines(result.segments)
    if not lines:
        return OutputFiles(lrc="", srt="", vtt="", txt="")
    return OutputFiles(**{fmt.value: _render(lines, fmt) for fmt in OutputFormat})


def convert_from_lrc(lrc_text: str) -> OutputFiles:
    """沒有片段時的舊轉換：LRC 原樣保留，SRT／VTT／TXT 由解析出來的行產生。"""
    if not lrc_text or not lrc_text.strip():
        logger.warning("LRC 是空的，四種輸出格式都是空的")
        return OutputFiles(lrc="", srt="", vtt="", txt="")
    cues = parse_lrc(lrc_text)
    if not cues:
        logger.warning("LRC 解析不出任何有時間戳的行，只能下載 LRC")
        return OutputFiles(lrc=lrc_text, srt="", vtt="", txt="")
    return OutputFiles(lrc=lrc_text, srt=_srt(cues), vtt=_vtt(cues), txt=_txt(cues))


@dataclass(frozen=True)
class Cue:
    """字幕的一行：開始時間（秒）、文字與真實結束時間（秒，不知道時是 None）。"""

    time: float
    text: str
    end: Optional[float] = None


_LRC_LINE_RE = re.compile(r"\[(\d{2,3}):(\d{2})\.(\d{2,3})\](.*)")
_GEMINI_SPEAKER_RE = re.compile(r"^\s*Speaker\s+[A-Z]:\s*")


def parse_lrc(lrc_text: str) -> List[Cue]:
    """解析 LRC 文字：只留有時間戳的行，並去掉 Gemini 的「Speaker A: 」。"""
    cues: List[Cue] = []
    for line in (lrc_text or "").strip().split("\n"):
        match = _LRC_LINE_RE.match(line)
        if match:
            cues.append(Cue(_stamp_seconds(match),
                            _GEMINI_SPEAKER_RE.sub("", match.group(4).strip())))
    return cues


# ─── 片段 → 行 ───────────────────────────────────────────────────────────────

MAX_LINE_SECONDS = 12.0
_SENTENCE_END_RE = re.compile(r"(?<=[。．！？!?…])")
_CLAUSE_END_RE = re.compile(r"(?<=[、，,])")
_BREAK_MARK_RE = re.compile(r"([。．！？!?…、，,])")


@dataclass(frozen=True)
class _Line:
    start: float
    """原音檔時間軸上的秒數。"""
    text: str
    """帶說話者標記的文字。"""
    end: Optional[float]
    """真實結束時間（原音檔時間軸上的秒數），不知道時是 None。"""
    speaker: Optional[str] = None
    """說話者編號，例如 S0；沒有時是 None，text 也就沒有說話者標記。"""
    words: Optional[Tuple[Mapping[str, Any], ...]] = None
    """這一行的逐字時間，依序對應 text 斷出來的詞；整段一行（沒有逐字時間）時是 None。"""


def _lines(segments: Sequence[Mapping[str, Any]]) -> List[_Line]:
    """依開始時間排序（和存下來的片段順序相同）後，逐段斷行。本機寫 LRC 時照模型給的順序，
    模型給的片段不照時間時，兩者的行序才會不同。沒有文字的片段不產生行。

    逐字時間對不上文字的片段整段一行（見 :func:`_words_match`），一個任務只記一條警告。
    """
    lines: List[_Line] = []
    unmatched: List[float] = []
    for segment in sorted(segments, key=lambda s: s["start"]):
        text = _one_line(segment.get("text") or "")
        if not text:
            continue
        words = segment.get("words") or None
        if words and not _words_match(text, words):
            unmatched.append(segment["start"])
            words = None
        lines.extend(_segment_lines(segment["start"], segment.get("end"),
                                    segment.get("speaker"), text, words))
    if unmatched:
        logger.warning(f"{len(unmatched)} 個片段的逐字時間對不上文字，這些片段整段一行"
                       f"（第一個從 {unmatched[0]:.2f} 秒開始）")
    return lines


_LINE_BREAK_RE = re.compile(r"\s*[\n\r\v\f\x1c-\x1e\x85  ]\s*")


def _one_line(text: str) -> str:
    """片段文字收成一行：換行（連同空行與前後的空白）換成一個空白。

    換行會讓 LRC 多出沒有時間戳的行，空行會把 SRT／VTT 的 cue 切斷。本機的 LRC 當時把換行
    原樣寫進去，這是和它唯一刻意不同的地方。對齊器斷詞時換行和空白一樣只是把詞隔開，換成空白
    不影響詞的對應。
    """
    return _LINE_BREAK_RE.sub(" ", text).strip()


def _words_match(text: str, words: Sequence[Mapping[str, Any]]) -> bool:
    """逐字時間的詞和整段文字斷出來的詞（:func:`aligner_words`）一個一個相同，每個詞也都有
    起訖時間。不同時（例如對齊器的規則改了）就不知道哪個時間屬於哪一句。"""
    return ([w.get("text") for w in words] == aligner_words(text)
            and all(w.get("start") is not None and w.get("end") is not None for w in words))


def _labelled(speaker: Optional[str], text: str) -> str:
    return f"[{speaker}] {text}" if speaker else text


def _segment_lines(
    segment_start: float,
    segment_end: Optional[float],
    speaker: Optional[str],
    text: str,
    words: Optional[Sequence[Mapping[str, Any]]],
) -> List[_Line]:
    """一個片段斷成的行，照本機原本產生 LRC 的規則（#110 之前本機轉接器自己寫 LRC，
    現在斷行的規則只有這一份）：

    * 沒有逐字時間（或對不上文字，由呼叫端換成 None）：整段一行，時間是片段的開始。
    * 在句尾標點（。．！？!?…）後斷句，一句一行，時間是這一句第一個詞的開始。
    * 一句從第一個詞的開始到最後一個詞的結束超過 12 秒時，在讀點（、，,）後再斷開，
      讓每一行盡量不超過 12 秒。
    * 沒有詞的部分（例如「！？」中間斷出來的「？」）併到下一行的行首，片段結尾的併到最後一行。

    每一行另外帶真實結束時間，給 SRT／VTT 用（見 :func:`_subtitles`）：有逐字時間時是這一行
    最後一個詞的結束，併進來的標點不改變它；整段一行時是片段的結束，片段沒有結束時間時是 None。
    有逐字時間時也帶著這一行的詞，SRT／VTT 拆長字幕時用（見 :func:`_subtitle_pieces`）。

    逐字時間怎麼對到句子：詞是對齊器斷的，標點不算詞、直接丟掉，所以從詞裡看不出句子在哪裡
    結束。本機先在斷行標點後面補空白再斷詞，詞就不會跨過任何斷行處；斷句以後，每一句各自斷詞
    數出有幾個詞，再依序從逐字時間取那麼多個。這裡用同樣的規則斷詞與計數（:func:`aligner_words`），
    呼叫端也先確認過整段文字斷出來的詞和存下來的詞一個一個相同。

    一句有多長，用對齊器給的相對時間判斷：存下來的是加上片段開頭、再換回原音檔時間軸的時間，
    減回片段開頭並取到毫秒，就是本機當時用的同一個值，剛好 12 秒時也做一樣的決定（直接拿兩個
    絕對時間相減會多出浮點誤差）。去靜音剪掉的靜音若落在一句中間，量到的長度包含那段靜音，
    本機當時量的是剪掉之後的長度。
    """
    whole = [_Line(segment_start, _labelled(speaker, text), segment_end, speaker)]
    if not words:
        return whole

    starts = [round(w["start"] - segment_start, 3) for w in words]
    ends = [round(w["end"] - segment_start, 3) for w in words]

    lines: List[_Line] = []
    offset = 0
    pending = ""
    for sentence in _split_keep(text, _SENTENCE_END_RE):
        count = _count_words(sentence)
        if count == 0:
            pending += sentence
            continue
        pieces = [(pending + sentence, offset)]
        pending = ""
        if ends[offset + count - 1] - starts[offset] > MAX_LINE_SECONDS:
            pieces = _split_at_clauses(pieces[0][0], offset, starts, ends)
        # 每一段的最後一個詞在下一段的第一個詞前面；最後一段的是這一句的最後一個詞
        lasts = [first - 1 for _, first in pieces[1:]] + [offset + count - 1]
        for (piece, first), last in zip(pieces, lasts, strict=True):
            lines.append(_Line(words[first]["start"], _labelled(speaker, piece.strip()),
                               words[last]["end"], speaker, tuple(words[first:last + 1])))
        offset += count
    if pending and lines:
        lines[-1] = replace(lines[-1], text=lines[-1].text + pending)
    return lines or whole


def _split_at_clauses(
    sentence: str, offset: int, starts: List[float], ends: List[float],
) -> List[Tuple[str, int]]:
    """過長的句子在讀點後斷開；回傳 [(文字, 第一個詞的序號)]，斷不開時整句一段。"""
    clauses = _split_keep(sentence, _CLAUSE_END_RE)
    if len(clauses) < 2:
        return [(sentence, offset)]
    pieces: List[Tuple[str, int]] = []
    piece, first = "", None
    position = offset
    for clause in clauses:
        count = _count_words(clause)
        if count == 0:
            piece += clause
            continue
        if first is not None and ends[position + count - 1] - starts[first] > MAX_LINE_SECONDS:
            pieces.append((piece, first))
            piece, first = "", None
        if first is None:
            first = position
        piece += clause
        position += count
    if piece:
        pieces.append((piece, first if first is not None else offset))
    return pieces


def _split_keep(text: str, pattern: re.Pattern) -> List[str]:
    """在標點後切開，標點留在前一段；只有空白的段落丟掉。"""
    return [part for part in pattern.split(text) if part.strip()]


def _count_words(text: str) -> int:
    return len(aligner_words(text))


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


# ─── 行 → 字幕：拆開長字幕（SRT／VTT） ───────────────────────────────────────

MAX_SUBTITLE_WIDTH = 32.0
MAX_SUBTITLE_WIDTH_JAPANESE = 26.0
"""一則字幕最多幾個全形字寬（#12）：Netflix Timed Text Style Guide 的每行上限（繁中 16、日文 13）
乘上最多兩行。行裡有假名就算日文，其他語言（含中文）都用 32。換行交給播放器：播放器依畫面寬度
自動換行，字級也跟著畫面縮放（WebVTT 規格 §1.1），手動斷行在窄畫面上會被再斷一次。"""

_READING_MARKS = "、，,"


def _subtitle_pieces(line: _Line) -> List[_Line]:
    """一行在 SRT／VTT 裡拆成的字幕（#12）：字寬（見 :func:`_width`，連同行首的說話者標記）超過
    上限時，用逐字時間拆成數則，每則都帶說話者標記，時間是它第一個詞的開始到最後一個詞的結束；
    之後的結束時間照 :func:`_subtitles` 的規則。切點見 :func:`_cut`，拆完還超過上限的段再拆，
    直到不超過或沒有切點。

    沒有逐字時間的行（Gemini、整段一行、沒有片段的任務）不拆：拆了只能猜時間。
    """
    limit = MAX_SUBTITLE_WIDTH_JAPANESE if _has_kana(line.text) else MAX_SUBTITLE_WIDTH
    if line.words is None or _width(line.text) <= limit:
        return [line]
    label = _labelled(line.speaker, "") if line.speaker else ""
    pieces = _split_to_width(line.text[len(label):], limit - _width(label))
    counts = [_count_words(piece) for piece in pieces]
    if len(pieces) == 1 or sum(counts) != len(line.words):
        return [line]
    subtitles: List[_Line] = []
    first = 0
    for piece, count in zip(pieces, counts, strict=True):
        words = line.words[first:first + count]
        subtitles.append(_Line(words[0]["start"], label + piece, words[-1]["end"],
                               line.speaker, words))
        first += count
    return subtitles


def _split_to_width(text: str, limit: float) -> List[str]:
    if _width(text) <= limit:
        return [text]
    cut = _cut(text)
    if cut is None:
        return [text]
    return _split_to_width(text[:cut].strip(), limit) + _split_to_width(text[cut:].strip(), limit)


def _cut(text: str) -> Optional[int]:
    """在哪裡拆開一則字幕。切點只在詞與詞之間（切開後兩邊斷出來的詞數加起來不變），標點跟著
    前面的字（下一則不以「，」「」」開頭），開頭的括號跟著後面的字。依序找

    1. 讀點（、，,）之後，或開頭的括號之前（「…」「…」從兩個引號中間切），
    2. 空白處，
    3. 平假名之後接著漢字、片假名或英數字的地方（「ゆっくり|休んで」；對齊器的詞在漢字與後面
       的假名之間也斷開，切在那裡會變成「休|んで」），

    每一類只考慮切完兩邊都有全長三分之一以上的切點，取最接近中間的（一樣近時取前面的）；三類
    都沒有時，取所有切點中最接近中間的。沒有切點（整則只有一個詞）時是 None。
    """
    total_words = _count_words(text)
    cuts = [cut for cut in range(1, len(text))
            if _may_start(text[cut]) and not _is_opening(text[cut - 1])
            and _count_words(text[:cut]) and _count_words(text[cut:])
            and _count_words(text[:cut]) + _count_words(text[cut:]) == total_words]
    if not cuts:
        return None
    total = _width(text)

    def off_middle(cut: int) -> float:
        return abs(_width(text[:cut]) - total / 2)

    def balanced(cut: int) -> bool:
        return min(_width(text[:cut]), total - _width(text[:cut])) >= total / 3

    preferences = (
        lambda cut: text[cut - 1] in _READING_MARKS or _is_opening(text[cut]),
        lambda cut: text[cut - 1].isspace() or text[cut].isspace(),
        lambda cut: _is_hiragana(text[cut - 1]) and not _is_hiragana(text[cut])
        and _count_words(text[cut]) == 1,
    )
    for preferred in preferences:
        candidates = [cut for cut in cuts if preferred(cut) and balanced(cut)]
        if candidates:
            return min(candidates, key=off_middle)
    return min(cuts, key=off_middle)


def _width(text: str) -> float:
    """字寬：全形字（East Asian Width 是 F 或 W）算 1，其他（半形字、空白）算 0.5，
    照 Netflix 日文規範的算法。"""
    return sum(1.0 if unicodedata.east_asian_width(char) in "FW" else 0.5 for char in text)


def _may_start(char: str) -> bool:
    """一則字幕可以用這個字開頭：詞的字、空白或開頭的括號，不是「，」「。」「」」這類標點。"""
    return _count_words(char) == 1 or char.isspace() or _is_opening(char)


def _is_opening(char: str) -> bool:
    return unicodedata.category(char) in ("Ps", "Pi")


def _has_kana(text: str) -> bool:
    return any(_is_hiragana(char) or "゠" <= char <= "ヿ" or "ｦ" <= char <= "ﾟ"
               for char in text)


def _is_hiragana(char: str) -> bool:
    return "ぁ" <= char <= "ゟ"


# ─── 行 → 檔案內容 ───────────────────────────────────────────────────────────

def _render(lines: Sequence[_Line], fmt: OutputFormat) -> str:
    if fmt == OutputFormat.LRC:
        return "\n".join(_lrc_timestamp(line.start) + line.text for line in lines)
    if fmt == OutputFormat.TXT:
        return _txt(_cues(lines))
    subtitles = _cues([piece for line in lines for piece in _subtitle_pieces(line)])
    return _srt(subtitles) if fmt == OutputFormat.SRT else _vtt(subtitles)


def _cues(lines: Sequence[_Line]) -> List[Cue]:
    return [Cue(_lrc_seconds(line.start), line.text.strip(), line.end) for line in lines]


def _lrc_timestamp(seconds: float) -> str:
    """先把秒數取到 0.01，再拆成分鐘與秒：59.996 秒寫成 [01:00.00]。

    照浮點數實際的值取最接近的 0.01，剛好一半時取偶數，和以前的 ``f"{秒:.2f}"`` 相同。以前先拆
    分鐘才取，秒數進位到 60 時會寫成 [00:60.00]（#154）。
    """
    hundredths = int(Decimal(seconds).quantize(Decimal("0.01"), ROUND_HALF_EVEN) * 100)
    minutes, rest = divmod(hundredths, 6_000)
    whole_seconds, fraction = divmod(rest, 100)
    return f"[{minutes:02d}:{whole_seconds:02d}.{fraction:02d}]"


def _lrc_seconds(seconds: float) -> float:
    """這個時間寫成 LRC 時間戳再讀回來的秒數。讀回來的是浮點數，不一定剛好（11.60 讀回來是
    11.599…），寫進 SRT／VTT 前由 :func:`_milliseconds` 四捨五入。"""
    match = _LRC_LINE_RE.match(_lrc_timestamp(seconds))
    return _stamp_seconds(match) if match else seconds


def _stamp_seconds(match: re.Match) -> float:
    minutes, seconds, fraction = match.group(1, 2, 3)
    return int(minutes) * 60 + int(seconds) + float(f"0.{fraction}")


def _milliseconds(seconds: float) -> int:
    """寫進 SRT／VTT 的毫秒數：四捨五入到毫秒，負的當成 0。開始與結束時間都用它。

    #24 之前開始時間是捨去：LRC 的 11.60 讀回來是浮點數 11.599…，寫成 11,599，約一半的開始
    因此少 1 毫秒；Gemini 三位小數的 1.001 也寫成 1,000。"""
    return round(max(seconds, 0.0) * 1000)


def _timestamp(milliseconds: int, separator: str) -> str:
    hours, rest = divmod(milliseconds, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{millis:03d}"


MIN_CUE_SECONDS = 0.8
"""字幕至少顯示的秒數（ADR-0008）。對齊器給的詞常常只有零點幾秒，甚至是零長度；一兩個字的插話
（例如「对」）照實際長度顯示會一閃而過。0.8 秒是使用者看過對照影片後選的。"""

_LAST_LINE_SECONDS = 5.0
"""沒有真實結束時間時，最後一行顯示的秒數（以前的規則）。"""


def _subtitles(cues: Sequence[Cue]) -> List[Tuple[str, int, int]]:
    """SRT／VTT 的每一行：(文字, 開始, 結束)，時間是毫秒，依開始時間排序（ADR-0008）。

    WebVTT 規定字幕依開始時間排列，SRT 照做。行依片段的開始排序，一個片段斷成的幾行可能和別人
    的片段交錯，所以這裡重新排序，同時開始的行照原本的順序；LRC、TXT 照片段的順序，不排序。
    下面的「下一行」指之後第一個比這一行晚開始的行，同時開始的不算。

    結束時間依序這樣算，全部在毫秒上：

    1. 有真實結束時間（有逐字時間時是這一行最後一個詞的結束，整段一行時是片段的結束，見
       :func:`_segment_lines`）就用它，四捨五入到毫秒，不截到別人下一行的開始：不同說話者的
       字幕可以重疊，靠說話者標記分辨。沒有真實結束時間（沒有片段的任務、片段沒有結束時間）時
       照以前，顯示到下一行（任何人的）開始，最後一行加 :data:`_LAST_LINE_SECONDS`。
    2. 至少顯示 :data:`MIN_CUE_SECONDS`；真實結束時間是零長度或顛倒時，就顯示這麼久。
    3. 同一位說話者的字幕不疊：不晚於他自己下一行的開始（說話者見 :func:`_speaker`）。同一位
       說話者緊接著說下一句時，這一行因此可能不到 0.8 秒。

    沒有說話者標記的行都算同一位說話者，所以沒有說話者標記、也沒有真實結束時間的輸出和以前逐字
    相同；只有開始時間倒退或重複的行不同，以前會輸出開始晚於結束、或零長度的字幕。

    #111 之前存的去靜音任務，結束剛好落在有聲段交界的片段，還原時可能跳到被剪掉的靜音之後：
    這一行多顯示到那段靜音結束，或截到同一位說話者的下一行。之後存的片段，結束在交界的算前一段
    （見 :mod:`app.services.silence_removal`）。
    """
    ordered = sorted(cues, key=lambda cue: cue.time)
    starts = [_milliseconds(cue.time) for cue in ordered]
    speakers = [_speaker(cue) for cue in ordered]
    starts_by_speaker: Dict[Optional[str], List[int]] = {}
    for speaker, start in zip(speakers, starts, strict=True):
        starts_by_speaker.setdefault(speaker, []).append(start)

    subtitles: List[Tuple[str, int, int]] = []
    for cue, start, speaker in zip(ordered, starts, speakers, strict=True):
        next_start = _first_after(starts, start)
        if cue.end is not None:
            end = _milliseconds(cue.end)
        elif next_start is not None:
            end = next_start
        else:
            end = _milliseconds(cue.time + _LAST_LINE_SECONDS)
        end = max(end, start + round(MIN_CUE_SECONDS * 1000))
        own_next_start = _first_after(starts_by_speaker[speaker], start)
        if own_next_start is not None:
            end = min(end, own_next_start)
        subtitles.append((cue.text, start, end))
    return subtitles


def _first_after(sorted_starts: Sequence[int], start: int) -> Optional[int]:
    """排好序的開始時間裡，第一個比 start 晚的；沒有時是 None。"""
    later = bisect_right(sorted_starts, start)
    return sorted_starts[later] if later < len(sorted_starts) else None


_SPEAKER_LABEL_RE = re.compile(r"\[S\d+\]|Speaker\s*(?:[0-9]+|[A-Z])\s*[:：]")


def _speaker(cue: Cue) -> Optional[str]:
    """這一行的說話者，看行首的說話者標記：[S0]，或存下來的 Gemini LRC 裡的「Speaker 1:」
    （空白與全形冒號不計）。同一個標記就是同一位說話者；沒有標記時是 None，這些行都算同一位。"""
    match = _SPEAKER_LABEL_RE.match(cue.text)
    return re.sub(r"[\s:：]", "", match.group(0)) if match else None


SPEAKER_COLORS: Tuple[Optional[str], ...] = (None, "#FFDD55", "#66CCFF", "#7FE0A0")
"""SRT／VTT 的說話者顏色（#12），依說話者編號輪流：S0、S4… 白色（播放器的預設，不加標籤），
S1、S5… 黃，S2、S6… 青，S3、S7… 綠。照 BBC Subtitle Guidelines §8.3 的順序（白、黃、青、綠）
把純色調柔：對黑色的對比 11.6:1 以上，兩色之間的色差（CIEDE2000）一般視覺 25 以上、紅綠色弱
13 以上，純色在紅色弱的眼裡黃和綠只差 4。顏色只看行首的 [Sn]：Gemini 舊 LRC 的「Speaker 1:」
與沒有標記的行都不上色。"""

_APP_LABEL_RE = re.compile(r"\[S(\d+)\]")


def _color_index(text: str) -> int:
    """這一行在 :data:`SPEAKER_COLORS` 裡的位置；0 是白色，不上色。"""
    match = _APP_LABEL_RE.match(text)
    return int(match.group(1)) % len(SPEAKER_COLORS) if match else 0


def _srt(cues: Sequence[Cue]) -> str:
    """SRT 用 ``<font color>`` 上色：VLC 與 ffmpeg（mpv 用它解碼）都認得。

    文字照原樣寫，不跳脫（#24）。SRT 沒有規格，也沒有跳脫的寫法：VLC 3.0 與 ffmpeg 都不解
    ``&amp;`` 這類字元參照，跳脫了反而照字面顯示「&amp;」。兩者都把沒有結尾標籤的 ``<笑>``、
    ``&``、``-->`` 照原樣顯示（ffmpeg 6.1 實測；VLC 照 3.0.x 的 modules/codec/subsdec.c）。
    寫不出來的只有字面上的格式標籤：文字裡的 ``<i>…</i>`` 這類標籤，播放器一律當成格式。
    """
    blocks: List[str] = []
    for number, (text, start, end) in enumerate(_subtitles(cues), start=1):
        color = SPEAKER_COLORS[_color_index(text)]
        colored = f'<font color="{color}">{text}</font>' if color else text
        blocks += [str(number), f"{_timestamp(start, ',')} --> {_timestamp(end, ',')}", colored, ""]
    return "\n".join(blocks)


def _vtt(cues: Sequence[Cue]) -> str:
    """VTT 用檔頭的 STYLE 區塊定義顏色，字幕用 ``<c.colorN>`` 包起來。

    文字依 WebVTT 規格跳脫（#24）：字幕文字裡的 & 與 < 要寫成字元參照（§4.2.2），字幕內容
    不能有「-->」（§4.1），所以 &、<、> 寫成 &amp;、&lt;、&gt;。沒跳脫時，Chromium 與 ffmpeg
    都把 ``<笑>`` 當成標籤吃掉；Chromium 遇到「-->」整則字幕的文字都不見。說話者與顏色看的是
    跳脫前的文字。

    ffmpeg 7.0 之前的版本遇到 STYLE 區塊，整個檔案都讀不出來（7.0 起跳過它），所以只在有要上色
    的行時才寫，只有白色或沒有標記的 VTT 不帶 STYLE 區塊。類別名稱不用 WebVTT 的預設顏色名
    （yellow、cyan、lime）：不讀 CSS 的 VLC 會照那些名字套上純色。
    """
    subtitles = _subtitles(cues)
    indexes = [_color_index(text) for text, _, _ in subtitles]
    blocks = ["WEBVTT", ""]
    used = sorted(set(indexes) - {0})
    if used:
        blocks += ["STYLE",
                   *(f"::cue(.color{index}) {{ color: {SPEAKER_COLORS[index]}; }}" for index in used),
                   ""]
    for (text, start, end), index in zip(subtitles, indexes, strict=True):
        escaped = html.escape(text, quote=False)
        colored = f"<c.color{index}>{escaped}</c>" if index else escaped
        blocks += [f"{_timestamp(start, '.')} --> {_timestamp(end, '.')}", colored, ""]
    return "\n".join(blocks)


def _txt(cues: Sequence[Cue]) -> str:
    return "\n".join(cue.text for cue in cues)
