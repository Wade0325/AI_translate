"""說話者對齊（#93）：分段轉錄的各段各自分離說話者，合併時用說話者嵌入把同一個人配成同一個說話者編號。

本機的 MOSS 只在單次輸入內編號（模型卡寫明，也沒有說話者註冊），切成好幾段轉錄時，前一段的 ``S0`` 和後一段
的 ``S0`` 可能是不同的人。接續段（#94）也是另外分離的：重疊區配不到的人拿新的編號
（:func:`app.services.continuation.match_speakers`），其實可能是前面的某一位。Gemini 也一樣（#335）：每一段是
另一次請求，Gemini 看不到前一段，「Speaker 1」只是那一段裡先說話的人。

這裡只改片段的 ``speaker``，不改時間、文字與片段 key，也不改任何一段送進模型的音檔：錯字率和不對齊時
完全相同。規則（不碰模型，嵌入由 :class:`SpeakerEmbedder` 給）：

1. 單位：每一段的每一個說話者編號是一個單位。同一次分離（一段的第一次轉錄，或它的某一次接續）裡出現的
   兩個編號一定不是同一個人，不能併在一起（cannot-link）；不同段的、或同一段不同次分離的，才可能是同一個人。
   沒有任何兩個單位可以併時（例如只有一段、也沒有接續拿到新編號），不算嵌入，編號照舊。
2. 嵌入：每個單位取它說話的片段，扣掉和別人同時說話的部分，留下至少 :data:`MIN_SPAN_SECONDS` 秒的；
   長的切成不超過 :data:`WINDOW_SECONDS` 秒的窗，從長的取起，最多 :data:`MAX_SECONDS_PER_UNIT` 秒。每一窗一個
   嵌入，依長度加權平均成這個單位的重心。一窗都沒有的單位沒有重心，不和任何人併。
   沒寫結束時間的片段（Gemini 的 LRC 多半只寫開始時間，#335）用同一段裡下一個比它晚開始的片段的開始當結束，
   最多一窗（離開始越遠，越可能已經換人），也不超過這一段音檔的結尾（Gemini 寫的時間可能超過音檔）；後面
   沒有片段時到音檔的結尾。這只用來挑聲音，不寫回片段：字幕會把推算的結束時間當真。本機的片段都有結束
   時間，不受影響。
3. 分群：重心兩兩的餘弦相似度，做平均連結的階層式分群，每次併平均相似度最高、又沒有 cannot-link 的兩群，
   最高的不到 :data:`THRESHOLD` 就停。做法照 10/19 的研究；門檻與取窗的上限在 AliMeeting Eval 上調，見研究區
   ``research_notes/93-chunk-speakers/embedding``。
4. 編號：第一段（有說話者的段裡最早的）原本的編號不變；其他群依第一次說話的先後，接在第一段用過的最大
   編號之後編新的。只有一段時，沒併的編號也不變。

嵌入用不了（權重載入失敗、讀不到音檔之類）時，分段轉錄改用 :func:`separate`：後面的段的每個人都拿新的
編號，寧可同一個人多一個編號，也不把不同的人併成同一個（#93 第 1 題）。

照所選人數收斂（#377，:func:`converge`）：本機的 MOSS 不能指定說話者人數，又常分出比實際多的說話者。使用者選了
2 到 8 人、轉錄結果（分段轉錄已經對齊成同一套）的說話者編號比所選多時，照下面的規則併到所選人數。一樣只改
片段的 ``speaker``，錯字率不變。規則與數字照 #353 的實測（AISHELL-4、AliMeeting 與評測集 ja5 共 12 件）：

1. 每個說話者編號是一位，說話的時間在整份轉錄結果的時間軸上算。說話合計不到 :data:`MIN_TALK_SECONDS` 秒的，
   以及照第 2 點的取窗規則取不到嵌入的，從說最少話的起，一個一個併進說最多話的那位，直到剩下所選人數或沒有
   這種編號：零碎編號的嵌入不準、彼此又相近，照聲音併會自成一群，接著為了湊人數把兩位真人併在一起。
2. 其餘的照第 2、3 點的取窗、重心與平均連結，每次併平均相似度最高的兩群；兩群之間有任兩位同時說話合計到
   :data:`OVERLAP_APART_SECONDS` 秒就不併（同一個人不會和自己同時說話），最高的不到 :data:`CONVERGE_THRESHOLD`
   就停，剩下所選人數也停。不沿用「同一次分離的兩個編號不能併」：單次轉完的檔所有編號都在同一次分離裡，
   照那樣完全不能收斂。窗跨段一起從長的取起，一位最多 :data:`MAX_SECONDS_PER_UNIT` 秒。
3. 併成一群的編號，改成那一群裡最早說話的那個編號。停下時仍比所選多也照樣完成，結果頁照 #351 第 4 點提醒。
"""

from __future__ import annotations

import bisect
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import (Any, Callable, Dict, FrozenSet, Iterable, List, Mapping, Optional, Protocol,
                    Sequence, Tuple)

import numpy as np

from app.utils.logger import setup_logger

logger = setup_logger(__name__)

Span = Tuple[float, float]
Segment = Mapping[str, Any]

THRESHOLD = 0.65
"""兩群的平均餘弦相似度到這裡才併成同一個人。AliMeeting Eval 7 場（600 秒切段）上 0.30～0.70 的結果相同，
都是只改編號能做到的最好，0.75 起開始漏併；兩邊都取到 30 秒以上的單位，同一人最低 0.85、不同人最高 0.61。
取 0.65：高於後者，同一次分離的 cannot-link 擋不到時（例如新的人只在後面的段說話）比較不會併錯人。"""
MIN_SPAN_SECONDS = 1.0
"""短於這個長度的發言不取嵌入：太短的嵌入不穩。"""
WINDOW_SECONDS = 10.0
"""長的發言切成不超過這個長度的窗，各取一個嵌入。"""
MAX_SECONDS_PER_UNIT = 60.0
"""一個單位最多取這麼多秒的聲音算重心，從長的發言取起；說很多話的人不必每一句都算。AliMeeting Eval 上 60 秒
和 300 秒的結果相同，取 60 秒，在 CPU 上算嵌入的時間少很多。"""

MIN_TALK_SECONDS = 10.0
"""照所選人數收斂時，說話合計不到這麼久的編號不照聲音併，先併進說最多話的那位（模組說明的收斂第 1 點）。#353：
5 秒不夠，ja5 有 8.2、8.4 秒的零碎編號留下來，整個音檔的 cpMER 26.82%，比不收斂（24.53%）還差；10 秒與 30 秒
在 12 件的結果相同，取小的，比較不會吞掉真的只說幾句話的人。"""
OVERLAP_APART_SECONDS = 1.0
"""照所選人數收斂時，兩群之間有任兩位同時說話合計到這麼久就不併。#353：沒有 10 秒那一步時一定要擋，完全不擋時
L_R003S03C02 的 cpMER 從 14.04% 變 31.46%，放寬到 3 秒也比 1 秒差；有 10 秒那一步時擋不擋結果相同，保留。"""
CONVERGE_THRESHOLD = 0.5
"""照所選人數收斂時，最像的兩群平均相似度不到這裡就停，寧可比所選多一位（結果頁提醒），也不把聲音不像的兩個人
硬併成一位。#353：不設與設 0.5 的結果相同；設 0.65（分段對齊的 :data:`THRESHOLD`）有 1 件停在比正確人數多
一位。讓 cpMER 變好的合併在 0.54～0.97，ja5 不先處理零碎編號時被硬併的兩位真人只有 0.36～0.37。"""

_SPEAKER_RE = re.compile(r"S(\d+)")
_PASS_RE = re.compile(r"(c\d+)\.")


class SpeakerEmbedder(Protocol):
    """說話者嵌入：CAM++（:class:`app.provider.local.campplus.CamPlusPlus`），本機與 Gemini 共用。"""

    def embed(self, audio: Path, spans: Sequence[Span]) -> Sequence[Optional[np.ndarray]]:
        """``audio`` 裡每一段（起, 迄，秒）的嵌入，長度 1 的向量；取不到的段是 None。"""
        ...


Report = Callable[[str], None]
EmbedderFactory = Callable[[Report], SpeakerEmbedder]
"""建立說話者嵌入；參數是給使用者看的進度（例如第一次用時下載權重）。"""


def _campplus(report: Report) -> SpeakerEmbedder:
    # 延遲 import：會匯入 torch，只有真的要對齊時才載入
    from app.provider.local.campplus import CamPlusPlus
    return CamPlusPlus(report)


_factory: EmbedderFactory = _campplus


def open_embedder(report: Report) -> SpeakerEmbedder:
    """建立說話者嵌入（載入模型，本機沒有權重時先下載）；用不了時拋出原本的錯誤。"""
    return _factory(report)


def use_embedder(factory: EmbedderFactory) -> EmbedderFactory:
    """換掉 :func:`open_embedder` 建立的說話者嵌入，回傳原本的（測試換成假的用）。"""
    global _factory
    previous, _factory = _factory, factory
    return previous


@dataclass(frozen=True)
class Piece:
    """一段轉完的音檔：``segments`` 的時間軸是 ``audio``，``start`` 是它在整份轉錄結果的時間軸上的起點
    （只用來排出誰先說話）。接續轉出的片段，片段 key 以 ``c1.``、``c2.`` 開頭。"""

    audio: Path
    start: float
    segments: Sequence[Segment]
    duration: Optional[float] = None
    """``audio`` 的長度（秒）：沒寫結束時間的最後一個片段取嵌入到這裡（模組說明第 2 點）；None 時不取。"""


@dataclass
class _Unit:
    piece: int
    label: str
    passes: FrozenSet[str]
    first: float
    """第一次說話的時間（整份轉錄結果的時間軸）。"""
    spans: List[Span] = field(default_factory=list)
    centroid: Optional[np.ndarray] = None


@dataclass
class _Speaker:
    """照所選人數收斂時的一位說話者：轉錄結果裡的一個說話者編號（各段已經對齊成同一套）。"""

    label: str
    first: float
    """第一次說話的時間（整份轉錄結果的時間軸）。"""
    talk: List[Span]
    """說話的時間（整份轉錄結果的時間軸），重疊的併起來、依先後。"""
    centroid: Optional[np.ndarray] = None

    @property
    def seconds(self) -> float:
        """說話合計幾秒。"""
        return sum(end - start for start, end in self.talk)


def needs_alignment(pieces: Sequence[Piece]) -> bool:
    """有沒有兩個單位可能是同一個人（見模組說明第 1 點）；沒有時不必嵌入，編號照舊。"""
    units = _units(pieces)
    return any(not _cannot_link(a, b) for i, a in enumerate(units) for b in units[i + 1:])


def align(pieces: Sequence[Piece], open_embedder: EmbedderFactory = open_embedder, *,
          threshold: float = THRESHOLD, check: Callable[[], None] = lambda: None,
          report: Report = lambda text: None) -> List[Dict[str, str]]:
    """對齊各段的說話者編號：回傳每一段的 {原本的編號: 對齊後的編號}，順序和 ``pieces`` 相同。

    ``check`` 在每次取嵌入之前呼叫（例如查使用者取消了沒有，取消就拋例外）；``report`` 交給建立說話者嵌入
    的 ``open_embedder``，回報給使用者看的進度。

    Raises:
        Exception: ``open_embedder`` 或取嵌入失敗時，原本的錯誤；由呼叫端改用 :func:`separate`。
    """
    units = _units(pieces)
    if not any(not _cannot_link(a, b) for i, a in enumerate(units) for b in units[i + 1:]):
        return _identity(units, len(pieces))
    embedder = open_embedder(report)
    for unit in units:
        piece = pieces[unit.piece]
        unit.spans = _spans(piece.segments, unit.label, piece.duration)
        if unit.spans:
            check()
            unit.centroid = _centroid(unit.spans, embedder.embed(piece.audio, unit.spans))
    clusters = _cluster(units, threshold)
    mappings = _numbered(clusters, units, len(pieces))
    _log(units, clusters, mappings)
    return mappings


def separate(pieces: Sequence[Piece]) -> List[Dict[str, str]]:
    """不對齊時的編號：第一段的編號不變，其他段的每一位都拿新的編號（見模組說明的最後一段）。"""
    units = _units(pieces)
    return _numbered([[i] for i in range(len(units))], units, len(pieces))


def converge(pieces: Sequence[Piece], speaker_count: int, open_embedder: EmbedderFactory = open_embedder, *,
             check: Callable[[], None] = lambda: None,
             report: Report = lambda text: None) -> Dict[str, str]:
    """照所選人數收斂（見模組說明的「照所選人數收斂」）：回傳 {原本的編號: 收斂後的編號}，含轉錄結果裡的每一個編號。

    ``pieces`` 的說話者編號已經是同一套（分段轉錄先對齊）；``speaker_count`` 是使用者選的說話者人數。編號不比它多時不取嵌入，
    編號照舊。收斂前後的對應、相似度與停下的原因寫進日誌（不寫文字）。``check`` 與 ``report`` 同 :func:`align`。

    Raises:
        Exception: ``open_embedder`` 或取嵌入失敗時，原本的錯誤；由呼叫端照原本的編號完成任務。
    """
    people = _people(pieces)
    if len(people) <= speaker_count:
        return {person.label: person.label for person in people}
    started = time.monotonic()
    embedder = open_embedder(report)
    for person in people:
        spans: List[Span] = []
        vectors: List[Optional[np.ndarray]] = []
        for index, windows in _windows_across(pieces, person.label).items():
            check()
            spans.extend(windows)
            vectors.extend(embedder.embed(pieces[index].audio, windows))
        person.centroid = _centroid(spans, vectors)
    groups, steps, stopped = _converge_groups(people, speaker_count)
    mapping: Dict[str, str] = {}
    for group in groups:
        # people 依第一次說話的先後排好：索引最小的就是最早說話的
        name = people[min(group)].label
        for i in group:
            mapping[people[i].label] = name
    _log_convergence(people, speaker_count, mapping, steps, stopped, time.monotonic() - started)
    return mapping


# ── 單位與嵌入 ────────────────────────────────────────────────

def _units(pieces: Sequence[Piece]) -> List[_Unit]:
    """每一段的每一個說話者編號一個單位，依段的先後、段裡第一次說話的先後。"""
    units: List[_Unit] = []
    for index, piece in enumerate(pieces):
        passes: Dict[str, set] = {}
        first: Dict[str, float] = {}
        for segment in piece.segments:
            label = segment.get("speaker")
            if label is None:
                continue
            passes.setdefault(label, set()).add(_pass_of(segment))
            first[label] = min(first.get(label, math.inf), piece.start + float(segment["start"]))
        for label in sorted(first, key=lambda name: (first[name], name)):
            units.append(_Unit(index, label, frozenset(passes[label]), first[label]))
    return units


def _pass_of(segment: Segment) -> str:
    """片段是哪一次分離轉出的：一段的第一次轉錄是空字串，接續是 ``c1``、``c2``…（看片段 key 的開頭）。"""
    match = _PASS_RE.match(str(segment.get("seg_key", "")))
    return match.group(1) if match else ""


def _cannot_link(a: _Unit, b: _Unit) -> bool:
    """同一段、同一次分離裡都出現的兩個編號一定是不同的人。"""
    return a.piece == b.piece and bool(a.passes & b.passes)


def _spans(segments: Sequence[Segment], label: str, duration: Optional[float] = None) -> List[Span]:
    """取嵌入的窗（見模組說明第 2 點），依時間先後。``duration`` 是這一段音檔的長度。"""
    windows = _windows(segments, label, duration)
    return sorted(windows[i] for i in _longest([(start, (start, end)) for start, end in windows]))


def _windows_across(pieces: Sequence[Piece], label: str) -> Dict[int, List[Span]]:
    """一位說話者在各段取嵌入的窗：各段的窗一起從長的取起（:func:`_longest`），回傳 {段的索引: 這一段取到的窗}，
    依段的先後、段裡依時間先後。"""
    windows = [(index, span) for index, piece in enumerate(pieces)
               for span in _windows(piece.segments, label, piece.duration)]
    chosen: Dict[int, List[Span]] = {}
    for i in _longest([(pieces[index].start + span[0], span) for index, span in windows]):
        index, span = windows[i]
        chosen.setdefault(index, []).append(span)
    return {index: sorted(chosen[index]) for index in sorted(chosen)}


def _windows(segments: Sequence[Segment], label: str, duration: Optional[float] = None) -> List[Span]:
    """這一段裡 ``label`` 每一個可以取嵌入的窗（還沒照 :data:`MAX_SECONDS_PER_UNIT` 挑），依片段的先後：扣掉和別人
    同時說話的部分，留下至少 :data:`MIN_SPAN_SECONDS` 秒的，長的切成不超過 :data:`WINDOW_SECONDS` 秒的窗。"""
    ended = _with_ends(segments, duration)
    others = sorted((start, end) for start, end, speaker in ended if speaker not in (None, label))
    windows: List[Span] = []
    for segment_start, segment_end, speaker in ended:
        if speaker != label:
            continue
        for start, end in _minus(segment_start, segment_end, others):
            if end - start >= MIN_SPAN_SECONDS:
                count = math.ceil((end - start) / WINDOW_SECONDS)
                step = (end - start) / count
                windows.extend((start + k * step, start + (k + 1) * step) for k in range(count))
    return windows


def _longest(windows: Sequence[Tuple[float, Span]]) -> List[int]:
    """從長的窗取起，一樣長的先取早的，取到 :data:`MAX_SECONDS_PER_UNIT` 秒為止：回傳取到的窗的索引。``windows`` 是
    （比先後用的開始時間, 窗）。"""
    chosen: List[int] = []
    total = 0.0
    for i in sorted(range(len(windows)), key=lambda i: (-(windows[i][1][1] - windows[i][1][0]), windows[i][0])):
        if total >= MAX_SECONDS_PER_UNIT:
            break
        chosen.append(i)
        total += windows[i][1][1] - windows[i][1][0]
    return chosen


def _with_ends(segments: Sequence[Segment], duration: Optional[float]) -> List[Tuple[float, float, Any]]:
    """每個片段的（起, 迄, 說話者編號），順序和 ``segments`` 相同；沒寫結束時間的推算一個（見模組說明第 2 點）：
    下一個比它晚開始的片段的開始，最多一窗，也不超過音檔的長度 ``duration``；後面沒有片段時到 ``duration``，
    沒給時不取。寫了結束時間的照寫的。"""
    starts = sorted({float(s["start"]) for s in segments})
    ended: List[Tuple[float, float, Any]] = []
    for segment in segments:
        start = float(segment["start"])
        if segment.get("end") is not None:
            ended.append((start, float(segment["end"]), segment.get("speaker")))
            continue
        following = bisect.bisect_right(starts, start)
        next_start = starts[following] if following < len(starts) else None
        if next_start is None and duration is None:
            continue  # 最後一個片段，又不知道音檔多長
        end = min(t for t in (next_start, duration, start + WINDOW_SECONDS) if t is not None)
        ended.append((start, end, segment.get("speaker")))
    return ended


def _minus(start: float, end: float, others: Iterable[Span]) -> List[Span]:
    """``start`` 到 ``end`` 扣掉 ``others``（依開始時間排好）之後剩下的幾段。"""
    left: List[Span] = []
    cursor = start
    for other_start, other_end in others:
        if other_end <= cursor:
            continue
        if other_start >= end:
            break
        if other_start > cursor:
            left.append((cursor, other_start))
        cursor = max(cursor, other_end)
        if cursor >= end:
            break
    if cursor < end:
        left.append((cursor, end))
    return left


def _centroid(spans: Sequence[Span], vectors: Sequence[Optional[np.ndarray]]) -> Optional[np.ndarray]:
    """依窗的長度加權平均、再化成長度 1；一窗都沒有嵌入時是 None。"""
    total: Optional[np.ndarray] = None
    for (start, end), vector in zip(spans, vectors, strict=True):
        if vector is None:
            continue
        weighted = np.asarray(vector, dtype=np.float64) * (end - start)
        total = weighted if total is None else total + weighted
    if total is None:
        return None
    norm = float(np.linalg.norm(total))
    return total / norm if norm > 0 else None


# ── 分群與編號 ────────────────────────────────────────────────

def _cluster(units: Sequence[_Unit], threshold: float) -> List[List[int]]:
    """平均連結的階層式分群（見模組說明第 3 點）：回傳每一群的單位（索引）。沒有重心的單位自成一群。"""
    clusters = [[i] for i in range(len(units))]
    similarity = _similarities([unit.centroid for unit in units])
    while (best := _best_pair(clusters, similarity,
                              lambda i, j: _cannot_link(units[i], units[j]))) is not None:
        if best[0] < threshold:
            break
        _join(clusters, best)
    return clusters


def _best_pair(clusters: Sequence[Sequence[int]], similarity: Mapping[Tuple[int, int], float],
               apart: Callable[[int, int], bool]) -> Optional[Tuple[float, int, int]]:
    """平均相似度最高的兩群：（平均相似度, x, y），x < y 是 ``clusters`` 的索引，一樣高的取前面的。兩群裡有任一位
    沒有重心（``similarity`` 裡沒有那一對），或有任兩位 ``apart`` 時不能併；沒有可以併的兩群時是 None。"""

    def linkage(a: Sequence[int], b: Sequence[int]) -> Optional[float]:
        pairs = [similarity.get((min(i, j), max(i, j))) for i in a for j in b]
        if any(p is None for p in pairs) or any(apart(i, j) for i in a for j in b):
            return None
        return sum(p for p in pairs if p is not None) / len(pairs)

    best: Optional[Tuple[float, int, int]] = None
    for x in range(len(clusters)):
        for y in range(x + 1, len(clusters)):
            score = linkage(clusters[x], clusters[y])
            if score is not None and (best is None or score > best[0]):
                best = (score, x, y)
    return best


def _join(clusters: List[List[int]], pair: Tuple[float, int, int]) -> None:
    """把 :func:`_best_pair` 選出的兩群併成一群，放在前面那群的位置。"""
    _, x, y = pair
    clusters[x] = sorted(clusters[x] + clusters[y])
    del clusters[y]


def _similarities(centroids: Sequence[Optional[np.ndarray]]) -> Dict[Tuple[int, int], float]:
    """兩兩都有重心的（索引 i < j）的餘弦相似度。"""
    return {(i, j): float(a @ b)
            for i, a in enumerate(centroids) if a is not None
            for j, b in enumerate(centroids) if j > i and b is not None}


def _numbered(clusters: Sequence[Sequence[int]], units: Sequence[_Unit],
              count: int) -> List[Dict[str, str]]:
    """每一群的編號（見模組說明第 4 點），展開成每一段的 {原本的編號: 對齊後的編號}。"""
    first_piece = min((u.piece for u in units), default=0)
    kept = [u.label for u in units if u.piece == first_piece]
    next_number = 1 + max((int(m[1]) for label in kept if (m := _SPEAKER_RE.fullmatch(label))),
                          default=-1)
    mappings: List[Dict[str, str]] = [{} for _ in range(count)]
    for cluster in sorted(clusters, key=lambda c: min(units[i].first for i in c)):
        own = sorted((units[i] for i in cluster if units[i].piece == first_piece),
                     key=lambda u: u.first)
        if own:
            name = own[0].label
        else:
            name = f"S{next_number}"
            next_number += 1
        for i in cluster:
            mappings[units[i].piece][units[i].label] = name
    return mappings


def _identity(units: Sequence[_Unit], count: int) -> List[Dict[str, str]]:
    mappings: List[Dict[str, str]] = [{} for _ in range(count)]
    for unit in units:
        mappings[unit.piece][unit.label] = unit.label
    return mappings


def _log(units: Sequence[_Unit], clusters: Sequence[Sequence[int]],
         mappings: Sequence[Mapping[str, str]]) -> None:
    """對齊的依據（每一群的成員與群裡最低的相似度、沒有嵌入的單位）寫進日誌，不寫文字。"""
    similarity = _similarities([unit.centroid for unit in units])
    parts = []
    for cluster in clusters:
        members = "、".join(f"第 {units[i].piece + 1} 段的 {units[i].label}" for i in cluster)
        name = mappings[units[cluster[0]].piece][units[cluster[0]].label]
        sims = [similarity[(i, j)] for i in cluster for j in cluster if i < j]
        evidence = (f"最低相似度 {min(sims):.2f}" if sims
                    else "沒有足夠長的發言取嵌入" if units[cluster[0]].centroid is None else "沒有配到別人")
        parts.append(f"{name}：{members}（{evidence}）")
    logger.info("跨段的說話者對齊：" + "；".join(parts))


# ── 照所選人數收斂 ────────────────────────────────────────────

def _people(pieces: Sequence[Piece]) -> List[_Speaker]:
    """轉錄結果裡的每一位說話者，依第一次說話的先後（整份轉錄結果的時間軸）。"""
    first: Dict[str, float] = {}
    talk: Dict[str, List[Span]] = {}
    for piece in pieces:
        for segment in piece.segments:
            label = segment.get("speaker")
            if label is not None:
                first[label] = min(first.get(label, math.inf), piece.start + float(segment["start"]))
                talk.setdefault(label, [])
        for start, end, label in _with_ends(piece.segments, piece.duration):
            if label is not None and end > start:
                talk[label].append((piece.start + start, piece.start + end))
    return [_Speaker(label, first[label], _union(talk[label]))
            for label in sorted(first, key=lambda name: (first[name], name))]


def _union(spans: Iterable[Span]) -> List[Span]:
    """重疊或相接的時間併起來，依先後。"""
    merged: List[Span] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _overlap(a: Sequence[Span], b: Sequence[Span]) -> float:
    """兩串依先後、互不重疊的時間（:func:`_union` 的結果）重疊的秒數。"""
    total, i, j = 0.0, 0, 0
    while i < len(a) and j < len(b):
        total += max(0.0, min(a[i][1], b[j][1]) - max(a[i][0], b[j][0]))
        if a[i][1] <= b[j][1]:
            i += 1
        else:
            j += 1
    return total


def _converge_groups(people: Sequence[_Speaker],
                     speaker_count: int) -> Tuple[List[List[int]], List[str], Optional[str]]:
    """收斂的兩步（模組說明的收斂第 1、2 點）：回傳（每一群的說話者（``people`` 的索引）, 每一步做了什麼, 停下時仍比
    所選多的原因；到了所選人數時是 None）。"""
    biggest = max(range(len(people)), key=lambda i: people[i].seconds)
    steps: List[str] = []
    absorbed: List[int] = []
    minor = sorted((i for i in range(len(people))
                    if i != biggest and (people[i].seconds < MIN_TALK_SECONDS or people[i].centroid is None)),
                   key=lambda i: (people[i].seconds, i))
    for i in minor:
        if len(people) - len(absorbed) <= speaker_count:
            break
        absorbed.append(i)
        why = ("取不到嵌入" if people[i].centroid is None
               else f"說話合計 {people[i].seconds:.1f} 秒")
        steps.append(f"{people[i].label}（{why}）併進說最多話的 {people[biggest].label}")

    similarity = _similarities([person.centroid for person in people])
    overlaps = {(i, j): _overlap(people[i].talk, people[j].talk)
                for i in range(len(people)) for j in range(i + 1, len(people))}
    clusters = [[i] for i in range(len(people)) if i not in absorbed]
    stopped: Optional[str] = None
    while len(clusters) > speaker_count:
        best = _best_pair(clusters, similarity,
                          lambda i, j: overlaps[(min(i, j), max(i, j))] >= OVERLAP_APART_SECONDS)
        if best is None:
            stopped = "其餘的任兩群之間都有人同時說話，或有一群取不到嵌入"
            break
        if best[0] < CONVERGE_THRESHOLD:
            stopped = f"最像的兩群平均相似度 {best[0]:.2f}，不到 {CONVERGE_THRESHOLD}"
            break
        _, x, y = best
        steps.append(f"{_names(people, clusters[y])} 併進 {_names(people, clusters[x])}"
                     f"（平均相似度 {best[0]:.2f}）")
        _join(clusters, best)
    for cluster in clusters:
        if biggest in cluster:
            cluster[:] = sorted(cluster + absorbed)
    return clusters, steps, stopped


def _names(people: Sequence[_Speaker], cluster: Sequence[int]) -> str:
    return "、".join(people[i].label for i in cluster)


def _log_convergence(people: Sequence[_Speaker], speaker_count: int, mapping: Mapping[str, str],
                     steps: Sequence[str], stopped: Optional[str], seconds: float) -> None:
    """收斂前後的對應、每一步的依據與停下的原因寫進日誌，不寫文字。"""
    left = len(set(mapping.values()))
    renamed = "、".join(f"{label}→{name}" for label, name in mapping.items() if label != name)
    parts = [f"照所選人數收斂說話者：模型分出 {len(people)} 位，所選 {speaker_count} 位，收斂後 {left} 位"
             f"（取嵌入與分群 {seconds:.1f} 秒）", "；".join(steps),
             f"停下：{stopped}，結果比所選多" if stopped else "", f"對應：{renamed}" if renamed else ""]
    logger.info("。".join(part for part in parts if part))
