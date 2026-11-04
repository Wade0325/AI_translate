"""掉尾模組：轉錄結果可能少了音檔結尾、或分段轉錄某一段結尾的內容時，找出可能掉尾的起點（#257）。

供應商可能提早停止輸出，卻不回報錯誤：本機的 MOSS 約輸出 16k token 就自己停下（#94），Gemini 也可能
沒轉到結尾。片段照樣回來，只是少了後面。這裡不看供應商說了什麼，只看結果：一段送去轉錄的音檔，最後一個
片段結束之後扣掉去靜音找到的靜音，還有至少 ``TAIL_LOSS_MIN_SECONDS`` 秒的聲音，就算可能掉尾，起點是
最後一個片段的結束（:func:`tail_loss_from`）。

聲音不一定是語音：去靜音只看音量，片尾音樂與 ASMR 的環境音也算，所以門檻留了餘裕，畫面也寫「可能」。

- 單檔任務：分段轉錄對每一段各檢查一次，取最早的起點（:mod:`app.services.chunked_transcription`）。
  分段轉錄時中間的段也可能停在約 16k token，最後一段卻轉到了結尾（#24）。
- 批次：不分段，結果放回原音檔的時間軸之後檢查整個音檔（:mod:`app.tasks.batch_core`）。

任務完成時，起點記在任務紀錄上（``tail_loss_from_seconds``），隨完成的廣播送給畫面；畫面照它寫
「從 mm:ss 起可能沒有轉錄到」。

接續（#94，:mod:`app.services.continuation`）用同一條規則決定要不要接續：分段轉錄的一段在這裡算起來
可能掉尾，模型能力又允許接續時，先從停下的地方附近再轉錄一次並接回；接續放棄時，接回來的片段停在
哪裡，起點就在哪裡，照這條路回報。轉接器回報了擔保轉錄到哪一秒（``covered_until``）時，從那裡算起，
不看最後一個片段。
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from app.core.config import get_settings
from app.services.silence_removal import Span


def tail_loss_from(segments: Sequence[Mapping[str, Any]], *, start: float, end: float,
                   silences: Sequence[Span],
                   covered_until: Optional[float] = None) -> Optional[float]:
    """原音檔的 ``start`` 到 ``end`` 秒送去轉錄、轉出 ``segments``：可能掉尾時回傳起點，不然是 None。

    都在原音檔的時間軸上。起點是停下的地方（:func:`stopped_at`），不早於 ``start``。從起點到 ``end``，
    扣掉 ``silences``（去靜音找到的靜音）之後還有至少 ``TAIL_LOSS_MIN_SECONDS`` 秒，才算可能掉尾。
    """
    stopped = max(stopped_at(segments, covered_until=covered_until, default=start), start)
    if _sounding(stopped, end, silences) < get_settings().tail_loss_min_seconds:
        return None
    return stopped


def stopped_at(segments: Sequence[Mapping[str, Any]], *, covered_until: Optional[float],
               default: float) -> float:
    """轉錄結果停在哪裡：轉接器回報了擔保轉錄到哪一秒（``covered_until``）時就是那裡；沒有時是最後
    一個片段的結束（沒有結束時間的片段，例如 Gemini 沒寫結束的行，看它的開始），一個片段都沒有時是
    ``default``。時間軸和傳進來的相同。"""
    if covered_until is not None:
        return covered_until
    return max((_last_time(segment) for segment in segments), default=default)


def _last_time(segment: Mapping[str, Any]) -> float:
    """片段在原音檔上最後的時間：結束，沒有結束時間時是開始。"""
    end = segment.get("end")
    return end if end is not None else segment.get("start", 0.0)


def _sounding(start: float, end: float, silences: Sequence[Span]) -> float:
    """``start`` 到 ``end`` 秒之間，扣掉 ``silences`` 之後還有幾秒。"""
    silent = sum(max(0.0, min(end, stop) - max(start, begin)) for begin, stop in silences)
    return max(0.0, end - start - silent)
