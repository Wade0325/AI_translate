"""``python -m tools.eval three-way``：三方對照，起草標準答案（ADR 0009、#15 Q5）。

拿底稿（資料集附的逐字稿、原著、台本）和兩個本機模型的轉錄結果逐句比對：

* ``compare``：三方一致的地方直接採用底稿；不一致的地方列成清單，寫成 JSON 與一個本機的
  試聽頁（HTML）。試聽頁播放每一處的前後幾秒，列出三種寫法讓使用者選，選完下載決定（JSON）。
* ``apply``：把使用者的決定套回底稿，寫成標準答案。還沒決定的地方在底稿原文後面加草稿標記
  ``(?)``，所以只要還有一處沒決定，評測就不會拿它判定（``reference_set``）。

比對用計分的正規化（:func:`.mer.tokenize`），所以標點、繁簡、全半形、語助詞與括號標註的
非語言聲不同，不會被列出來；只列會影響錯字率的差異。底稿的 ``[聽不清]`` 對什麼都算一致。

不一致的地方分三類（同一處三份的 token 合起來比）：

* ``models_agree``：兩個模型一致、底稿不同。底稿可能錯（朗讀者讀錯或跳行、紀錄整理過），
  也可能兩個模型錯在同一處；最需要聽。
* ``all_differ``：三方都不同。
* ``source_with_one``：底稿和其中一個模型一致，另一個模型不同。

時間點：轉錄結果的 LRC 只有每行的開始時間，行內的位置照字數在這一行和下一行的開始時間之間
內插（每字最多算 0.4 秒），只拿來定位播放。

只輸出數字到終端機；底稿與轉錄結果的文字只寫進 ``--out`` 的 JSON 與試聽頁，不寫進標準答案的
資料夾（``data/eval``）。標準答案由使用者確認後，自己從 ``--out`` 複製過去。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import opencc
from rapidfuzz.distance import Levenshtein

from . import lrc, mer, reference_set
from .cli import UsageError, _refuse_writing_references, _tool_version, default_lab_dir
from .reference_set import DOUBT_RE, UNCLEAR, UTT_RE

Category = Literal["models_agree", "all_differ", "source_with_one"]
CATEGORIES: tuple[Category, ...] = ("models_agree", "all_differ", "source_with_one")
CATEGORY_LABELS: dict[Category, str] = {
    "models_agree": "兩個模型一致、底稿不同",
    "all_differ": "三方都不同",
    "source_with_one": "底稿和其中一個模型一致",
}
Choice = Literal["source", "first", "second", "custom", "unclear"]
CHOICES: tuple[Choice, ...] = ("source", "first", "second", "custom", "unclear")

SECONDS_PER_CHAR_CAP = 0.4
"""行內內插時每字最多算幾秒：下一行隔很久才開始時（中間是靜音），不讓時間點被拉到靜音裡。"""

PAGE_TEMPLATE = Path(__file__).with_name("three_way_page.html")

_T2S = opencc.OpenCC("t2s")
"""和 ``mer`` 用同一份繁簡設定（``t2s``，理由見 mer.py 開頭）。"""


# --------------------------------------------------------------- 正規化
@dataclass(frozen=True)
class Token:
    """正規化後的一個 token，連同它在原文哪一行、哪幾個字。"""

    text: str
    line: int
    start: int
    end: int


@dataclass
class _Char:
    """正規化途中的一個字，記著它來自原文的哪幾個字。"""

    ch: str
    start: int
    end: int


def _regex_drop(chars: list[_Char], pattern: re.Pattern[str],
                replacement: str | None = None) -> list[_Char]:
    """在正規化途中的字串上做 ``pattern.sub``，同時保留每個字的出處。"""
    text = "".join(c.ch for c in chars)
    out: list[_Char] = []
    pos = 0
    for m in pattern.finditer(text):
        out.extend(chars[pos:m.start()])
        if replacement is not None and m.end() > m.start():
            out.append(_Char(replacement, chars[m.start()].start, chars[m.end() - 1].end))
        pos = m.end()
    out.extend(chars[pos:])
    return out


def _map_each(chars: list[_Char], convert) -> list[_Char]:
    """逐字轉換；一個字變成好幾個字時，每個都記同一個出處。"""
    out: list[_Char] = []
    for c in chars:
        out.extend(_Char(ch, c.start, c.end) for ch in convert(c.ch))
    return out


def tokenize_with_offsets(text: str, line: int) -> list[Token]:
    """和 :func:`.mer.tokenize` 相同的 token，另外記下每個 token 在原文的起訖位置。

    步驟照 ``mer.tokenize`` 的順序，只是逐字做、保留出處。繁簡轉換整行一起做（字典有詞組），
    長度不變時逐字對回去，變了才逐字轉。合成字（例如分開的濁點）在逐字的 NFKC 不會合起來，
    這種行的 token 可能和計分時不同：:func:`check_tokenization` 用來找出這種行。
    """
    chars = [_Char(ch, i, i + 1) for i, c in enumerate(text)
             for ch in unicodedata.normalize("NFKC", c)]
    chars = _regex_drop(chars, re.compile(re.escape(unicodedata.normalize("NFKC", UNCLEAR))),
                        replacement=mer.UNK)
    chars = _regex_drop(chars, DOUBT_RE)
    chars = _regex_drop(chars, re.compile(re.escape("(?)")))
    chars = _regex_drop(chars, mer.NON_SPEECH_RE)

    joined = "".join(c.ch for c in chars)
    converted = _T2S.convert(joined)
    if len(converted) == len(joined):
        chars = [_Char(ch, c.start, c.end) for ch, c in zip(converted, chars, strict=True)]
    else:
        chars = _map_each(chars, _T2S.convert)
    chars = _map_each(chars, lambda ch: ch.replace("着", "著").lower())

    joined = "".join(c.ch for c in chars)
    tokens = [Token(m.group(), line, chars[m.start()].start, chars[m.end() - 1].end)
              for m in mer.TOKEN_RE.finditer(joined)]
    tokens = [t for t in tokens if t.text not in mer.FILLERS]
    return [Token(mer.DIGIT_ZH.get(t.text, t.text), t.line, t.start, t.end)
            for t in _collapse_spelled_letters(tokens)]


def _collapse_spelled_letters(tokens: Sequence[Token]) -> list[Token]:
    """同 ``mer._collapse_spelled_letters``：逐字母唸出的縮寫（S Q L）併成一個 token。"""
    out: list[Token] = []
    run: list[Token] = []

    def flush() -> None:
        if len(run) >= 2:
            out.append(Token("".join(t.text for t in run), run[0].line, run[0].start, run[-1].end))
        else:
            out.extend(run)
        run.clear()

    for t in tokens:
        if len(t.text) == 1 and t.text.isascii() and t.text.isalpha():
            run.append(t)
        else:
            flush()
            out.append(t)
    flush()
    return out


def check_tokenization(text: str) -> bool:
    """這一行逐字正規化的 token 和計分用的相同。"""
    return [t.text for t in tokenize_with_offsets(text, 0)] == mer.tokenize(text)


# ------------------------------------------------------------------ 讀檔
@dataclass
class SourceLine:
    """底稿的一句：``raw_index`` 是檔案的第幾行（0 起算），``prefix`` 是文字前面的時間戳與代號。"""

    raw_index: int
    prefix: str
    text: str
    speaker: str
    seconds: float | None


@dataclass
class SourceText:
    """底稿，格式同標準答案（``reference_set`` 開頭的說明）。"""

    path: Path
    name: str
    start: float
    end: float
    raw_lines: list[str]
    lines: list[SourceLine]


def _ts_seconds(ts: str | None) -> float | None:
    if not ts:
        return None
    parts = ts.split(":")
    try:
        seconds = 0.0
        for part in parts:
            seconds = seconds * 60 + float(part)
    except ValueError:
        return None
    return seconds


def read_source(path: Path) -> SourceText:
    """讀底稿。格式錯誤時照 ``reference_set.read_reference`` 的訊息拒絕。"""
    excerpt = reference_set.read_reference(path, allow_draft=True)
    raw = path.read_text(encoding="utf-8").splitlines()
    lines: list[SourceLine] = []
    for i, line in enumerate(raw):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = UTT_RE.match(s)
        if m is None:  # read_reference 已經擋下格式錯誤的行
            continue
        text = m.group("text").strip()
        if not text:
            continue
        lead = line[:len(line) - len(line.lstrip())]
        lines.append(SourceLine(raw_index=i, prefix=lead + s[:m.start("text")], text=text,
                                speaker=m.group("spk"), seconds=_ts_seconds(m.group("ts"))))
    if not lines:
        raise UsageError(f"{path.name} 沒有任何一句：底稿至少要有一行「代號: 文字」。")
    return SourceText(path=path, name=excerpt.name, start=excerpt.start, end=excerpt.end,
                      raw_lines=raw, lines=lines)


@dataclass
class Transcript:
    """一份轉錄結果在底稿時間範圍內的行。"""

    path: Path
    label: str
    lines: list[lrc.Line]


def _label(path: Path) -> str:
    """模型名稱：讀 transcribe 寫在旁邊的 manifest，沒有時用資料夾名稱。"""
    manifest = path.with_name(f"{path.stem}.manifest.json")
    if manifest.is_file():
        try:
            model = json.loads(manifest.read_text(encoding="utf-8"))["request"]["model"]
        except (ValueError, KeyError, TypeError):
            model = None
        if isinstance(model, str) and model:
            return model
    return path.parent.name or path.stem


def read_transcript(path: Path, start: float, end: float) -> Transcript:
    if not path.is_file():
        raise UsageError(f"找不到轉錄結果：{path}")
    lines = [line for line in lrc.read(path).lines if start <= line.seconds < end]
    return Transcript(path=path, label=_label(path), lines=lines)


# ------------------------------------------------------------------ 對齊
@dataclass
class _Alignment:
    """一份轉錄結果對底稿的對齊。位置 2g 是第 g 個 token 前面的空隙，2i+1 是第 i 個 token。

    ``ranges[p]`` 是位置 p 對到轉錄結果的哪幾個 token（左閉右開）；``bad[p]`` 是那裡不一致。
    """

    ranges: list[tuple[int, int]]
    bad: list[bool]


def _align(source: Sequence[str], hyp: Sequence[str]) -> _Alignment:
    n = len(source)
    token_range: dict[int, tuple[int, int]] = {}
    token_bad: dict[int, bool] = {}
    inserted: dict[int, tuple[int, int]] = {}
    for op in Levenshtein.opcodes(list(source), list(hyp)):
        i1, i2, j1, j2 = op.src_start, op.src_end, op.dest_start, op.dest_end
        if op.tag == "insert":
            inserted[i1] = (j1, j2)
            continue
        width = i2 - i1
        for k in range(width):
            if op.tag == "delete":
                token_range[i1 + k] = (j1, j1)
            else:  # equal 或 replace；replace 兩邊不等長時照比例分
                token_range[i1 + k] = (j1 + k * (j2 - j1) // width,
                                       j1 + (k + 1) * (j2 - j1) // width)
            token_bad[i1 + k] = op.tag != "equal"

    ranges: list[tuple[int, int]] = []
    bad: list[bool] = []
    cursor = 0
    for g in range(n + 1):
        j1, j2 = inserted.get(g, (cursor, cursor))
        ranges.append((j1, j2))
        bad.append(j2 > j1)
        cursor = j2
        if g < n:
            ranges.append(token_range[g])
            bad.append(token_bad[g])
            cursor = token_range[g][1]
    # 底稿的 [聽不清] 對什麼都算一致，緊鄰的空隙也是
    for i, t in enumerate(source):
        if t == mer.UNK:
            bad[2 * i] = bad[2 * i + 1] = bad[2 * i + 2] = False
    return _Alignment(ranges, bad)


# ------------------------------------------------------------------ 不一致的地方
@dataclass
class Variant:
    """一份文字在不一致處的寫法。``context`` 是它所在的整行，``start``／``end`` 是寫法在
    ``context`` 裡的位置（空的寫法兩者相同，標出插入點）。"""

    text: str
    tokens: list[str]
    context: str
    start: int
    end: int

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "context": self.context, "start": self.start, "end": self.end}


@dataclass
class Spot:
    """一處不一致。``line`` 是底稿的第幾句（0 起算），``source`` 的位置就在那一句的文字裡。"""

    id: int
    line: int
    category: Category
    seconds: float | None
    end_seconds: float | None
    source: Variant
    first: Variant
    second: Variant

    def to_dict(self) -> dict[str, Any]:
        s, a, b = self.source.tokens, self.first.tokens, self.second.tokens
        return {"id": self.id, "line": self.line, "category": self.category,
                "seconds": _round(self.seconds), "end_seconds": _round(self.end_seconds),
                "source": self.source.to_dict(), "first": self.first.to_dict(),
                "second": self.second.to_dict(),
                # 正規化後相同的寫法，試聽頁併成一個選項
                "same": {"first_second": a == b, "source_first": s == a, "source_second": s == b}}


def _round(x: float | None) -> float | None:
    return None if x is None else round(x, 2)


def categorize(source: Sequence[str], first: Sequence[str], second: Sequence[str]) -> Category | None:
    """一處不一致屬於哪一類；三份完全相同（對齊的位置不同而已）時回傳 None。"""
    s, a, b = list(source), list(first), list(second)
    if s == a == b:
        return None
    if s in (a, b):
        return "source_with_one"
    if a == b:
        return "models_agree"
    return "all_differ"


def _joined_text(pieces: Sequence[str]) -> str:
    """跨行的寫法接起來；兩邊都是英數字時中間補空白。"""
    out = ""
    for p in pieces:
        if out and p and out[-1].isascii() and out[-1].isalnum() and p[0].isascii() and p[0].isalnum():
            out += " "
        out += p
    return out


@dataclass
class _Side:
    """一份轉錄結果：每行的文字與時間、正規化後的 token。"""

    transcript: Transcript
    tokens: list[Token] = field(default_factory=list)

    def __post_init__(self) -> None:
        for k, line in enumerate(self.transcript.lines):
            self.tokens.extend(tokenize_with_offsets(line.text, k))

    def variant(self, j1: int, j2: int) -> Variant:
        toks = self.tokens[j1:j2]
        lines = self.transcript.lines
        anchor_char = 0
        if toks:
            first_line, last_line = toks[0].line, toks[-1].line
        else:
            anchor = self._anchor(j1)
            if anchor is None:
                return Variant("", [], "", 0, 0)
            first_line = last_line = anchor[0]
            anchor_char = anchor[1]
        context_parts: list[str] = []
        offsets: dict[int, int] = {}
        for k in range(first_line, last_line + 1):
            offsets[k] = len(" ".join(context_parts)) + (1 if context_parts else 0)
            context_parts.append(lines[k].text)
        context = " ".join(context_parts)
        if not toks:
            pos = offsets[first_line] + anchor_char
            return Variant("", [], context, pos, pos)
        pieces: list[str] = []
        for k in range(first_line, last_line + 1):
            in_line = [t for t in toks if t.line == k]
            if in_line:
                pieces.append(lines[k].text[in_line[0].start:in_line[-1].end])
        return Variant(_joined_text(pieces), [t.text for t in toks], context,
                       offsets[first_line] + toks[0].start, offsets[last_line] + toks[-1].end)

    def _anchor(self, j: int) -> tuple[int, int] | None:
        """空的寫法標在哪：上一個 token 的結尾，前面沒有 token 時是下一個 token 的開頭。"""
        if 0 < j <= len(self.tokens):
            return self.tokens[j - 1].line, self.tokens[j - 1].end
        if self.tokens:
            return self.tokens[0].line, self.tokens[0].start
        return None

    def seconds_at(self, line: int, char: int) -> float:
        """行內的時間：照字數在這一行和下一行的開始時間之間內插。"""
        lines = self.transcript.lines
        here = lines[line]
        length = max(1, len(here.text))
        span = length * SECONDS_PER_CHAR_CAP
        if line + 1 < len(lines) and lines[line + 1].seconds > here.seconds:
            span = min(span, lines[line + 1].seconds - here.seconds)
        return here.seconds + span * min(1.0, char / length)

    def time_span(self, j1: int, j2: int) -> tuple[float, float] | None:
        if j2 > j1:
            a, b = self.tokens[j1], self.tokens[j2 - 1]
            return self.seconds_at(a.line, a.start), self.seconds_at(b.line, b.end)
        anchor = self._anchor(j1)
        if anchor is None:
            return None
        t = self.seconds_at(*anchor)
        return t, t


@dataclass
class Comparison:
    """``compare`` 的結果。"""

    source: SourceText
    first: Transcript
    second: Transcript
    spots: list[Spot]
    source_tokens: int
    unmatched_lines: dict[str, int]

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {"lines": len(self.source.lines), "tokens": self.source_tokens,
                               "spots": len(self.spots)}
        for c in CATEGORIES:
            out[c] = sum(1 for s in self.spots if s.category == c)
        return out


def _gap_line(g: int, src_tokens: Sequence[Token], sides: Sequence[_Side],
              alignments: Sequence[_Alignment]) -> int:
    """第 g 個 token 前面的空隙算底稿的哪一句。

    句子中間的空隙就是那一句。兩句之間的空隙有模型多出來的字時，看那些字在轉錄結果裡和誰同一行：
    和下一句對到的字同一行，就算下一句的開頭；否則算上一句的結尾。
    """
    if not src_tokens:
        return 0
    if g == 0:
        return src_tokens[0].line
    before = src_tokens[g - 1].line
    if g == len(src_tokens) or src_tokens[g].line == before:
        return before
    for side, a in zip(sides, alignments, strict=True):
        j1, j2 = a.ranges[2 * g]
        k1, k2 = a.ranges[2 * g + 1]
        if j2 > j1 and k2 > k1 and side.tokens[j1].line == side.tokens[k1].line:
            return src_tokens[g].line
    return before


def compare(source: SourceText, first: Transcript, second: Transcript) -> Comparison:
    """三方逐句對照，找出不一致的地方。"""
    src_tokens: list[Token] = []
    for k, line in enumerate(source.lines):
        src_tokens.extend(tokenize_with_offsets(line.text, k))
    sides = [_Side(first), _Side(second)]
    unmatched = {
        "source": sum(1 for line in source.lines if not check_tokenization(line.text)),
        "first": sum(1 for line in first.lines if not check_tokenization(line.text)),
        "second": sum(1 for line in second.lines if not check_tokenization(line.text)),
    }
    src_texts = [t.text for t in src_tokens]
    alignments = [_align(src_texts, [t.text for t in side.tokens]) for side in sides]

    n = len(src_tokens)
    gap_line = [_gap_line(g, src_tokens, sides, alignments) for g in range(n + 1)]

    def line_of(p: int) -> int:
        return src_tokens[p // 2].line if p % 2 else gap_line[p // 2]

    # 不一致的位置連成一處：中間只隔著一個沒有插入的空隙（「下週」兩個字都錯）也算連著，
    # 隔著一個一致的 token 就分開；跨到底稿的下一句也分開
    bad = [p for p in range(2 * n + 1) if any(a.bad[p] for a in alignments)]
    runs: list[tuple[int, int]] = []
    for p in bad:
        if runs:
            p0, last = runs[-1]
            joined = p - last == 1 or (p - last == 2 and (last + 1) % 2 == 0)
            if joined and line_of(p) == line_of(p0):
                runs[-1] = (p0, p)
                continue
        runs.append((p, p))

    spots: list[Spot] = []
    for p0, p1 in runs:
        line = line_of(p0)
        token_positions = [p for p in range(p0, p1 + 1) if p % 2]
        src_span = [src_tokens[p // 2] for p in token_positions]
        text = source.lines[line].text
        if src_span:
            s0, s1 = src_span[0].start, src_span[-1].end
        else:  # 底稿沒有的字：插在前一個 token 後面，這一句的開頭則插在第一個 token 前面
            g = p0 // 2
            if n == 0:
                s0 = s1 = 0
            elif g > 0 and src_tokens[g - 1].line == line:
                s0 = s1 = src_tokens[g - 1].end
            else:
                s0 = s1 = src_tokens[g].start
        src_variant = Variant(text[s0:s1], [t.text for t in src_span], text, s0, s1)
        variants: list[Variant] = []
        times: list[tuple[float, float]] = []
        for side, a in zip(sides, alignments, strict=True):
            j1, j2 = a.ranges[p0][0], a.ranges[p1][1]
            variants.append(side.variant(j1, j2))
            span = side.time_span(j1, j2)
            if span is not None:
                times.append(span)
        category = categorize(src_variant.tokens, variants[0].tokens, variants[1].tokens)
        if category is None:
            continue
        if times:
            seconds, end_seconds = min(t[0] for t in times), max(t[1] for t in times)
        else:
            seconds = end_seconds = source.lines[line].seconds
        spots.append(Spot(id=len(spots) + 1, line=line, category=category, seconds=seconds,
                          end_seconds=end_seconds, source=src_variant, first=variants[0],
                          second=variants[1]))
    return Comparison(source=source, first=first, second=second, spots=spots, source_tokens=n,
                      unmatched_lines=unmatched)


# ------------------------------------------------------------------ 輸出
def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def audio_src(audio: Path, page_dir: Path) -> str:
    """試聽頁的 ``<audio src>``：相對於試聽頁的路徑；不同磁碟機時用 file: 網址。"""
    try:
        rel = os.path.relpath(audio.resolve(), page_dir.resolve())
    except ValueError:  # Windows 上不同磁碟機
        return audio.resolve().as_uri()
    return quote(Path(rel).as_posix())


def _digest(spots: list[dict[str, Any]], source_sha: str, system_shas: list[str]) -> str:
    """這份清單的指紋：試聽頁下載的決定帶著它，apply 拿來確認決定是對這份清單做的。

    決定以每一處的編號記錄，重跑 compare（例如換了轉錄結果）編號就會對到別處。"""
    blob = json.dumps({"spots": spots, "source": source_sha, "systems": system_shas},
                      ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def to_payload(result: Comparison, audio: Path | None, out_dir: Path) -> dict[str, Any]:
    spots = [s.to_dict() for s in result.spots]
    source_sha = _sha256(result.source.path)
    systems = [{"label": t.label, "path": str(t.path), "sha256": _sha256(t.path)}
               for t in (result.first, result.second)]
    return {
        "command": "three-way compare",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "tool_version": _tool_version(),
        "name": result.source.name,
        "window": [result.source.start, result.source.end],
        "digest": _digest(spots, source_sha, [s["sha256"] for s in systems]),
        "source": {"path": str(result.source.path), "sha256": source_sha},
        "systems": systems,
        "audio": None if audio is None else {"path": str(audio), "src": audio_src(audio, out_dir)},
        "category_labels": CATEGORY_LABELS,
        "lines": [{"speaker": line.speaker, "text": line.text, "seconds": line.seconds}
                  for line in result.source.lines],
        "spots": spots,
        "counts": result.counts(),
        "unmatched_lines": result.unmatched_lines,
    }


def render_page(payload: dict[str, Any]) -> str:
    """把資料嵌進試聽頁。``</`` 換成 ``<\\/``，文字裡有 ``</script>`` 也不會提早結束。"""
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    template = PAGE_TEMPLATE.read_text(encoding="utf-8")
    title = (payload["name"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    return template.replace("__TITLE__", title).replace("__DATA__", data)


def format_counts(result: Comparison) -> str:
    """終端機只印數字，不印任何文字（底稿與轉錄結果可能是只能留在本機的素材）。"""
    c = result.counts()
    labels = [t.label for t in (result.first, result.second)]
    out = [
        f"三方對照：{result.source.name}（底稿 {c['lines']} 句、{c['tokens']} 個 token；"
        f"模型：{labels[0]}、{labels[1]}）",
        f"不一致 {c['spots']} 處：",
    ]
    out.extend(f"  {CATEGORY_LABELS[k]}：{c[k]}" for k in CATEGORIES)
    bad = {k: v for k, v in result.unmatched_lines.items() if v}
    if bad:
        names = {"source": "底稿", "first": labels[0], "second": labels[1]}
        out.append("⚠ 這些行逐字正規化的 token 和計分時不同（合成字之類），列出的位置可能偏一點："
                   + "、".join(f"{names[k]} {v} 行" for k, v in bad.items()))
    return "\n".join(out)


def cmd_compare(args) -> int:
    lab_references = default_lab_dir() / "data" / "eval"
    out_dir = Path(args.out)
    _refuse_writing_references(out_dir, [lab_references], option="--out")
    source = read_source(Path(args.source))
    first = read_transcript(Path(args.transcript), source.start, source.end)
    second = read_transcript(Path(args.second_hypothesis), source.start, source.end)
    audio = Path(args.audio) if args.audio else None
    if audio is not None and not audio.is_file():
        raise UsageError(f"找不到音檔：{audio}")

    json_path = out_dir / f"{source.name}.three-way.json"
    page_path = out_dir / f"{source.name}.three-way.html"
    existing = [p.name for p in (json_path, page_path) if p.exists()]
    if existing:
        raise UsageError(f"{out_dir} 已經有 {'、'.join(existing)}：不覆寫，換一個 --out 或先移走它們。")

    result = compare(source, first, second)
    payload = to_payload(result, audio, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    page_path.write_text(render_page(payload), encoding="utf-8")
    print(format_counts(result))
    print(f"\n試聽頁：{page_path}\n清單：{json_path}")
    return 0


# ------------------------------------------------------------------ 套用決定
@dataclass
class Applied:
    """``apply`` 的結果：標準答案的全文與各種決定的數量。"""

    text: str
    counts: dict[str, int]


def _decision_text(spot: dict[str, Any], decision: dict[str, Any] | None) -> str | None:
    """這一處要換成的文字；沒有決定時回傳 None。"""
    if not decision:
        return None
    choice = decision.get("choice")
    if choice == "source":
        return spot["source"]["text"]
    if choice in ("first", "second"):
        return spot[choice]["text"]
    if choice == "unclear":
        return UNCLEAR
    if choice == "custom":
        text = decision.get("text")
        if not isinstance(text, str):
            raise UsageError(f"第 {spot['id']} 處選了自己輸入，卻沒有文字。")
        return " ".join(text.split())  # 換行會拆壞「代號: 文字」的一行
    raise UsageError(f"第 {spot['id']} 處的決定看不懂：{choice!r}（可以是 {'、'.join(CHOICES)}）")


def apply_decisions(source: SourceText, payload: dict[str, Any], decisions: dict[str, Any],
                    confirmed_by: str | None = None, on: date | None = None) -> Applied:
    """把決定套回底稿。沒有決定的地方保留底稿的寫法，後面加草稿標記 ``(?)``。"""
    by_id: dict[str, Any] = decisions.get("decisions") or {}
    counts = {c: 0 for c in CHOICES}
    counts["undecided"] = 0
    edits: dict[int, list[tuple[int, int, str]]] = {}
    for spot in payload["spots"]:
        decision = by_id.get(str(spot["id"]))
        replacement = _decision_text(spot, decision)
        s0, s1 = spot["source"]["start"], spot["source"]["end"]
        if decision is None or replacement is None:
            counts["undecided"] += 1
            edits.setdefault(spot["line"], []).append((s1, s1, "(?)"))
        else:
            counts[decision["choice"]] += 1
            edits.setdefault(spot["line"], []).append((s0, s1, replacement))

    if confirmed_by and counts["undecided"]:
        raise UsageError(f"還有 {counts['undecided']} 處沒有決定，不能標成已確認。")

    raw = list(source.raw_lines)
    for k, line_edits in edits.items():
        line = source.lines[k]
        text = line.text
        for s0, s1, replacement in sorted(line_edits, key=lambda e: (e[0], e[1]), reverse=True):
            text = text[:s0] + replacement + text[s1:]
        raw[line.raw_index] = line.prefix + text

    systems = "、".join(f"{s['label']}（SHA-256 {s['sha256'][:12]}）" for s in payload["systems"])
    decided = len(payload["spots"]) - counts["undecided"]
    notes = [
        f"# 三方對照：底稿 {source.path.name}（SHA-256 {payload['source']['sha256'][:12]}）、{systems}；"
        f"不一致 {len(payload['spots'])} 處，已決定 {decided} 處（採用底稿 {counts['source']}、"
        f"採用模型 {counts['first'] + counts['second']}、自己輸入 {counts['custom']}、"
        f"聽不清 {counts['unclear']}）",
    ]
    if confirmed_by:
        notes.append(f"# 確認：{confirmed_by}，{(on or date.today()).isoformat()}")
    first_line = source.lines[0].raw_index
    insert_at = first_line
    while insert_at > 0 and not raw[insert_at - 1].strip():
        insert_at -= 1
    raw[insert_at:insert_at] = notes
    return Applied(text="\n".join(raw) + "\n", counts=counts)


def cmd_apply(args) -> int:
    lab_references = default_lab_dir() / "data" / "eval"
    out_dir = Path(args.out)
    _refuse_writing_references(out_dir, [lab_references], option="--out")
    spots_path, decisions_path = Path(args.spots), Path(args.decisions)
    for p in (spots_path, decisions_path):
        if not p.is_file():
            raise UsageError(f"找不到 {p}")
    payload = json.loads(spots_path.read_text(encoding="utf-8"))
    decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
    source_path = Path(payload["source"]["path"])
    if not source_path.is_file():
        raise UsageError(f"找不到底稿 {source_path}（清單記的路徑）。")
    if _sha256(source_path) != payload["source"]["sha256"]:
        raise UsageError(f"底稿 {source_path.name} 在 compare 之後改過了：清單上的位置對不上，"
                         f"重跑 compare。")
    if decisions.get("digest") != payload["digest"]:
        raise UsageError(f"{decisions_path.name} 不是對這份清單做的決定（digest 不同）：重跑過 compare 時，"
                         f"編號會對到別處。用這份清單的試聽頁重新決定，或改給當時的清單。")

    source = read_source(source_path)
    applied = apply_decisions(source, payload, decisions, confirmed_by=args.confirmed_by)
    target = out_dir / f"{source.name}.txt"
    if target.exists():
        raise UsageError(f"{target} 已經存在：不覆寫，換一個 --out 或先移走它。")
    out_dir.mkdir(parents=True, exist_ok=True)
    # 只用 LF，Windows 上也不換成 CRLF（同 transcribe 寫的 LRC）
    target.write_text(applied.text, encoding="utf-8", newline="")

    c = applied.counts
    print(f"已決定 {len(payload['spots']) - c['undecided']}／{len(payload['spots'])} 處："
          f"採用底稿 {c['source']}、採用 {payload['systems'][0]['label']} {c['first']}、"
          f"採用 {payload['systems'][1]['label']} {c['second']}、自己輸入 {c['custom']}、"
          f"聽不清 {c['unclear']}；沒決定 {c['undecided']}（加了草稿標記）")
    print(f"標準答案：{target}")
    if c["undecided"] == 0 and args.confirmed_by:
        print("沒有草稿標記了；複製到研究區的 data/eval 之後，評測就會拿它判定。")
    return 0
