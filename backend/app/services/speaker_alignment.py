"""說話者對齊（#93）：分段轉錄的各段各自分離說話者，合併時用說話者嵌入把同一個人配成同一個說話者編號。

本機的 MOSS 只在單次輸入內編號（模型卡寫明，也沒有說話者註冊），切成好幾段轉錄時，前一段的 ``S0`` 和後一段
的 ``S0`` 可能是不同的人。接續段（#94）也是另外分離的：重疊區配不到的人拿新的編號
（:func:`app.services.continuation.match_speakers`），其實可能是前面的某一位。

這裡只改片段的 ``speaker``，不改時間、文字與片段 key，也不改任何一段送進模型的音檔：錯字率和不對齊時
完全相同。規則（不碰模型，嵌入由 :class:`SpeakerEmbedder` 給）：

1. 單位：每一段的每一個說話者編號是一個單位。同一次分離（一段的第一次轉錄，或它的某一次接續）裡出現的
   兩個編號一定不是同一個人，不能併在一起（cannot-link）；不同段的、或同一段不同次分離的，才可能是同一個人。
   沒有任何兩個單位可以併時（例如只有一段、也沒有接續拿到新編號），不算嵌入，編號照舊。
2. 嵌入：每個單位取它說話的片段，扣掉和別人同時說話的部分，留下至少 :data:`MIN_SPAN_SECONDS` 秒的；
   長的切成不超過 :data:`WINDOW_SECONDS` 秒的窗，從長的取起，最多 :data:`MAX_SECONDS_PER_UNIT` 秒。每一窗一個
   嵌入，依長度加權平均成這個單位的重心。一窗都沒有的單位沒有重心，不和任何人併。
3. 分群：重心兩兩的餘弦相似度，做平均連結的階層式分群，每次併平均相似度最高、又沒有 cannot-link 的兩群，
   最高的不到 :data:`THRESHOLD` 就停。做法照 10/19 的研究；門檻與取窗的上限在 AliMeeting Eval 上調，見研究區
   ``research_notes/93-chunk-speakers/embedding``。
4. 編號：第一段（有說話者的段裡最早的）原本的編號不變；其他群依第一次說話的先後，接在第一段用過的最大
   編號之後編新的。只有一段時，沒併的編號也不變。

嵌入用不了（權重載入失敗、讀不到音檔之類）時，分段轉錄改用 :func:`separate`：後面的段的每個人都拿新的
編號，寧可同一個人多一個編號，也不把不同的人併成同一個（#93 第 1 題）。
"""

from __future__ import annotations

import math
import re
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

_SPEAKER_RE = re.compile(r"S(\d+)")
_PASS_RE = re.compile(r"(c\d+)\.")


class SpeakerEmbedder(Protocol):
    """說話者嵌入：本機是 CAM++（:class:`app.provider.local.campplus.CamPlusPlus`）。"""

    def embed(self, audio: Path, spans: Sequence[Span]) -> Sequence[Optional[np.ndarray]]:
        """``audio`` 裡每一段（起, 迄，秒）的嵌入，長度 1 的向量；取不到的段是 None。"""
        ...


EmbedderFactory = Callable[[], SpeakerEmbedder]


def _campplus() -> SpeakerEmbedder:
    # 延遲 import：會匯入 torch，只有真的要對齊時才載入
    from app.provider.local.campplus import CamPlusPlus
    return CamPlusPlus()


_factory: EmbedderFactory = _campplus


def open_embedder() -> SpeakerEmbedder:
    """建立說話者嵌入（載入模型）；用不了時拋出原本的錯誤。"""
    return _factory()


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


@dataclass
class _Unit:
    piece: int
    label: str
    passes: FrozenSet[str]
    first: float
    """第一次說話的時間（整份轉錄結果的時間軸）。"""
    spans: List[Span] = field(default_factory=list)
    centroid: Optional[np.ndarray] = None


def needs_alignment(pieces: Sequence[Piece]) -> bool:
    """有沒有兩個單位可能是同一個人（見模組說明第 1 點）；沒有時不必嵌入，編號照舊。"""
    units = _units(pieces)
    return any(not _cannot_link(a, b) for i, a in enumerate(units) for b in units[i + 1:])


def align(pieces: Sequence[Piece], open_embedder: EmbedderFactory = open_embedder, *,
          threshold: float = THRESHOLD, check: Callable[[], None] = lambda: None
          ) -> List[Dict[str, str]]:
    """對齊各段的說話者編號：回傳每一段的 {原本的編號: 對齊後的編號}，順序和 ``pieces`` 相同。

    ``check`` 在每次取嵌入之前呼叫（例如查使用者取消了沒有，取消就拋例外）。

    Raises:
        Exception: ``open_embedder`` 或取嵌入失敗時，原本的錯誤；由呼叫端改用 :func:`separate`。
    """
    units = _units(pieces)
    if not any(not _cannot_link(a, b) for i, a in enumerate(units) for b in units[i + 1:]):
        return _identity(units, len(pieces))
    embedder = open_embedder()
    for unit in units:
        unit.spans = _spans(pieces[unit.piece].segments, unit.label)
        if unit.spans:
            check()
            unit.centroid = _centroid(unit.spans, embedder.embed(pieces[unit.piece].audio, unit.spans))
    clusters = _cluster(units, threshold)
    mappings = _numbered(clusters, units, len(pieces))
    _log(units, clusters, mappings)
    return mappings


def separate(pieces: Sequence[Piece]) -> List[Dict[str, str]]:
    """不對齊時的編號：第一段的編號不變，其他段的每一位都拿新的編號（見模組說明的最後一段）。"""
    units = _units(pieces)
    return _numbered([[i] for i in range(len(units))], units, len(pieces))


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


def _spans(segments: Sequence[Segment], label: str) -> List[Span]:
    """取嵌入的窗（見模組說明第 2 點），依時間先後。"""
    others = sorted((float(s["start"]), float(s["end"])) for s in segments
                    if s.get("speaker") not in (None, label) and s.get("end") is not None)
    pieces: List[Span] = []
    for segment in segments:
        if segment.get("speaker") != label or segment.get("end") is None:
            continue
        for start, end in _minus(float(segment["start"]), float(segment["end"]), others):
            if end - start >= MIN_SPAN_SECONDS:
                count = math.ceil((end - start) / WINDOW_SECONDS)
                step = (end - start) / count
                pieces.extend((start + k * step, start + (k + 1) * step) for k in range(count))
    chosen: List[Span] = []
    total = 0.0
    for span in sorted(pieces, key=lambda s: (-(s[1] - s[0]), s[0])):
        if total >= MAX_SECONDS_PER_UNIT:
            break
        chosen.append(span)
        total += span[1] - span[0]
    return sorted(chosen)


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
    similarity = _similarities(units)

    def linkage(a: List[int], b: List[int]) -> Optional[float]:
        pairs = [similarity.get((min(i, j), max(i, j))) for i in a for j in b]
        if any(p is None for p in pairs) or any(_cannot_link(units[i], units[j]) for i in a for j in b):
            return None
        return sum(p for p in pairs if p is not None) / len(pairs)

    while True:
        best: Optional[Tuple[float, int, int]] = None
        for x in range(len(clusters)):
            for y in range(x + 1, len(clusters)):
                score = linkage(clusters[x], clusters[y])
                if score is not None and score >= threshold and (best is None or score > best[0]):
                    best = (score, x, y)
        if best is None:
            return clusters
        _, x, y = best
        clusters[x] = sorted(clusters[x] + clusters[y])
        del clusters[y]


def _similarities(units: Sequence[_Unit]) -> Dict[Tuple[int, int], float]:
    """兩兩都有重心的單位（索引 i < j）的餘弦相似度。"""
    centroids = [unit.centroid for unit in units]
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
    similarity = _similarities(units)
    parts = []
    for cluster in clusters:
        members = "、".join(f"第 {units[i].piece + 1} 段的 {units[i].label}" for i in cluster)
        name = mappings[units[cluster[0]].piece][units[cluster[0]].label]
        sims = [similarity[(i, j)] for i in cluster for j in cluster if i < j]
        evidence = (f"最低相似度 {min(sims):.2f}" if sims
                    else "沒有足夠長的發言取嵌入" if units[cluster[0]].centroid is None else "沒有配到別人")
        parts.append(f"{name}：{members}（{evidence}）")
    logger.info("跨段的說話者對齊：" + "；".join(parts))
