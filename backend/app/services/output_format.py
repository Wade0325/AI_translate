"""輸出格式模組：給任務、輸出格式與版本，回傳檔案內容。

資料來源：

* 有片段的任務從片段產生，轉錄結果只有片段這一份。
* 沒有片段的舊任務（片段上線前的任務、批次裡的任務）退回解析存下來的 LRC，內容和以前相同。
* 存下來的 LRC 是凍結的原始轉錄副本（ADR-0007），有片段時下載不讀它。

本機任務從片段產生的 LRC，和本機轉接器寫出的 LRC 逐字相同：同樣的斷行（見
:func:`_segment_lines`）、同樣的時間戳。沒去靜音也沒切段的任務，存下來的副本就是那一份。
去靜音或切段過的任務，副本另外經過分段轉錄對 LRC 文字做的時間處理（#110 拿掉），和這裡會有
三種差異，都是那段處理造成的，這裡的時間比較準：

* 時間戳差 0.01 秒：去靜音的時間還原把秒數捨去到 0.01，切段的後段平移時又四捨五入一次。
  去靜音的任務很常見，約一半的行。
* 一行的第一個詞若在被剪掉的靜音前 0.005 秒內開始，副本先四捨五入才還原時間，時間會跳到
  那段靜音之後。
* 一句中間剪掉的靜音，這裡會算進 12 秒的長度，本機當時沒算；長度在 12 秒上下的句子斷行可能不同。

版本目前只有原始轉錄，校正後版本留給 v0.2。

四種格式由同一串行產生，說話者標記一律「[S0] 文字」：LRC 一行一個時間戳；SRT／VTT 的
結束時間是下一行的開始，最後一行加 5 秒（#96 改用真實結束時間）；TXT 只留文字。SRT／VTT
的時間取 LRC 時間戳讀回來的值，和以前從 LRC 轉換時一樣。斷行的規則見 :func:`_segment_lines`。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, List, Mapping, Optional, Sequence, Tuple

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

    任務沒有轉錄結果（沒有片段，也沒有存下來的 LRC）時回傳 None；舊任務的 LRC 解析不出
    任何一行時，SRT／VTT／TXT 是空字串。版本目前只有原始轉錄一種。
    """
    segments = TranscriptSegmentRepository.segments_for_task(db, task.task_uuid)
    if segments:
        return _render(_lines(segments), fmt)
    stored_lrc = HistoryRepository().resolve_lrc_content(db, task, backfill=True)
    if not stored_lrc:
        return None
    return getattr(convert_from_lrc(stored_lrc), fmt.value)


def for_result(result: TranscriptionTaskResult) -> OutputFiles:
    """一份轉錄結果的四種輸出格式，任務完成時送給畫面；從轉錄結果寫凍結的原始轉錄副本時
    （#110）也從這裡取 LRC。

    有片段時從片段產生，和之後下載的內容相同；沒有片段（Gemini）時轉換轉錄結果的 LRC 文字。
    """
    if not result.segments:
        return convert_from_lrc(result.text)
    lines = _lines(result.segments)
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
    """字幕的一行：開始時間（秒）與文字。"""

    time: float
    text: str


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


def _lines(segments: Sequence[Mapping[str, Any]]) -> List[_Line]:
    """依開始時間排序（和存下來的片段順序相同）後，逐段斷行。本機寫 LRC 時照模型給的順序，
    模型給的片段不照時間時，兩者的行序才會不同。"""
    lines: List[_Line] = []
    for segment in sorted(segments, key=lambda s: s["start"]):
        lines.extend(_segment_lines(segment))
    return lines


def _labelled(speaker: Optional[str], text: str) -> str:
    return f"[{speaker}] {text}" if speaker else text


def _segment_lines(segment: Mapping[str, Any]) -> List[_Line]:
    """一個片段斷成的行，照本機原本產生 LRC 的規則（provider/local/asr.py 的
    ``_entry_to_lines`` 與 ``_split_long_unit``；#110 讓供應商不再產生 LRC 後只剩這一份）：

    * 沒有逐字時間，或逐字時間對不上文字：整段一行，時間是片段的開始。
    * 在句尾標點（。．！？!?…）後斷句，一句一行，時間是這一句第一個詞的開始。
    * 一句從第一個詞的開始到最後一個詞的結束超過 12 秒時，在讀點（、，,）後再斷開，
      讓每一行盡量不超過 12 秒。
    * 沒有詞的部分（例如「！？」中間斷出來的「？」）併到下一行的行首，片段結尾的併到最後一行。

    逐字時間怎麼對到句子：詞是對齊器斷的，標點不算詞、直接丟掉，所以從詞裡看不出句子在哪裡
    結束。本機先在斷行標點後面補空白再斷詞，詞就不會跨過任何斷行處；斷句以後，每一句各自斷詞
    數出有幾個詞，再依序從逐字時間取那麼多個。這裡用同樣的規則斷詞與計數（:func:`_aligner_words`），
    而且先確認整段文字斷出來的詞和存下來的詞一個一個相同；不同（例如對齊器的規則改了）就不知道
    哪個時間屬於哪一句，整段一行。

    一句有多長，用對齊器給的相對時間判斷：存下來的是加上片段開頭、再換回原音檔時間軸的時間，
    減回片段開頭並取到毫秒，就是本機當時用的同一個值，剛好 12 秒時也做一樣的決定（直接拿兩個
    絕對時間相減會多出浮點誤差）。去靜音剪掉的靜音若落在一句中間，量到的長度包含那段靜音，
    本機當時量的是剪掉之後的長度。
    """
    speaker = segment.get("speaker")
    text = segment.get("text") or ""
    whole = [_Line(segment["start"], _labelled(speaker, text))]
    words = segment.get("words")
    if not words:
        return whole
    if ([w.get("text") for w in words] != _aligner_words(text)
            or any(w.get("start") is None or w.get("end") is None for w in words)):
        logger.warning(f"逐字時間對不上片段文字，整段一行（{segment['start']:.2f}s）")
        return whole

    origin = segment["start"]
    starts = [round(w["start"] - origin, 3) for w in words]
    ends = [round(w["end"] - origin, 3) for w in words]

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
        for piece, first in pieces:
            lines.append(_Line(words[first]["start"], _labelled(speaker, piece.strip())))
        offset += count
    if pending and lines:
        lines[-1] = _Line(lines[-1].start, lines[-1].text + pending)
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
    return len(_aligner_words(text))


def _aligner_words(text: str) -> List[str]:
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


# ─── 行 → 檔案內容 ───────────────────────────────────────────────────────────

def _render(lines: Sequence[_Line], fmt: OutputFormat) -> str:
    if fmt == OutputFormat.LRC:
        return "\n".join(_lrc_timestamp(line.start) + line.text for line in lines)
    cues = [Cue(_lrc_seconds(line.start), line.text.strip()) for line in lines]
    renderers = {OutputFormat.SRT: _srt, OutputFormat.VTT: _vtt, OutputFormat.TXT: _txt}
    return renderers[OutputFormat(fmt)](cues)


def _lrc_timestamp(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"[{minutes:02d}:{seconds - minutes * 60:05.2f}]"


def _lrc_seconds(seconds: float) -> float:
    """這個時間寫成 LRC 時間戳再讀回來的秒數（11.6 讀回來是 11.599…，以前就是這樣）。"""
    match = _LRC_LINE_RE.match(_lrc_timestamp(seconds))
    return _stamp_seconds(match) if match else seconds


def _stamp_seconds(match: re.Match) -> float:
    minutes, seconds, fraction = match.group(1, 2, 3)
    return int(minutes) * 60 + int(seconds) + float(f"0.{fraction}")


def _timestamp(seconds: float, separator: str) -> str:
    if seconds < 0:
        seconds = 0
    hours = int(seconds / 3600)
    minutes = int((seconds % 3600) / 60)
    secs = int(seconds % 60)
    milliseconds = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{milliseconds:03d}"


def _end_time(cues: Sequence[Cue], i: int) -> float:
    """沿用現行規則：下一行的開始，最後一行加 5 秒。"""
    return cues[i + 1].time if i + 1 < len(cues) else cues[i].time + 5.0


def _srt(cues: Sequence[Cue]) -> str:
    blocks: List[str] = []
    for i, cue in enumerate(cues):
        blocks += [str(i + 1),
                   f"{_timestamp(cue.time, ',')} --> {_timestamp(_end_time(cues, i), ',')}",
                   cue.text, ""]
    return "\n".join(blocks)


def _vtt(cues: Sequence[Cue]) -> str:
    blocks = ["WEBVTT", ""]
    for i, cue in enumerate(cues):
        blocks += [f"{_timestamp(cue.time, '.')} --> {_timestamp(_end_time(cues, i), '.')}",
                   cue.text, ""]
    return "\n".join(blocks)


def _txt(cues: Sequence[Cue]) -> str:
    return "\n".join(cue.text for cue in cues)
