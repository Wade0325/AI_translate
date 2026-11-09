"""假的說話者嵌入：照收到的音檔回答，讓整合測試不必載入 CAM++（#93）。

和假供應商的 ``Listen`` 一樣聽合成音檔的頻率（tests/support/synthetic_audio.py 的正弦波，取到 100 Hz）：
同一個頻率給同一個向量、不同的頻率互相垂直，所以同一位說話者的相似度是 1，不同的是 0。

它同時是自己的工廠：``speaker_alignment.use_embedder(embedder)`` 之後，每次要對齊時建立的都是同一個實例，
測試可以事後檢查它被怎麼用。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

import numpy as np
import soundfile as sf

DIMENSIONS = 64


class FakeEmbedder:
    def __init__(self) -> None:
        self.opened = 0
        # 建立時拋的錯，例如權重載入失敗
        self.open_error: Optional[Exception] = None
        # 建立時回報給使用者的進度，例如第一次用時下載權重
        self.notice: Optional[str] = None
        # 每次取嵌入收到的（音檔, 窗）
        self.calls: List[Tuple[Path, Tuple[Tuple[float, float], ...]]] = []

    def __call__(self, report: Callable[[str], None]) -> "FakeEmbedder":
        self.opened += 1
        if self.notice is not None:
            report(self.notice)
        if self.open_error is not None:
            raise self.open_error
        return self

    def embed(self, audio: Path, spans: Sequence[Tuple[float, float]]) -> List[Optional[np.ndarray]]:
        self.calls.append((audio, tuple(spans)))
        samples, rate = sf.read(str(audio), dtype="float32", always_2d=True)
        mono = samples.mean(axis=1)
        return [_voice(mono[int(start * rate):int(end * rate)], end - start)
                for start, end in spans]


def _voice(piece: np.ndarray, seconds: float) -> Optional[np.ndarray]:
    """這一窗的頻率（取到 100 Hz）對到的單位向量；沒有聲音時是 None。"""
    if seconds <= 0 or not np.any(np.abs(piece) > 0.01):
        return None
    crossings = int(np.count_nonzero(np.signbit(piece[1:]) != np.signbit(piece[:-1])))
    tone = int(round(crossings / 2 / seconds / 100))
    vector = np.zeros(DIMENSIONS)
    vector[tone % DIMENSIONS] = 1.0
    return vector
