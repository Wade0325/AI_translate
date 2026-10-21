"""去靜音模組：單檔任務的去靜音只有一個入口 :func:`speech_view`，回傳語音視圖。

語音視圖（:class:`SpeechView`）是實際送進模型的音檔，以及把其中的時間還原回原音檔的對照；
分段轉錄照它決定送什麼、切在哪裡，轉錄完把時間還原回原音檔。剪不剪看兩件事：

- 模型能力的「轉錄前要不要剪掉靜音」：不剪的模型送原音檔，但照樣找出靜音，每段靜音的正中間
  當分段轉錄的切點。
- 語音佔比：低於門檻（``VAD_SPEECH_RATIO_SKIP_THRESHOLD``，預設 90%）才剪。幾乎全是語音的音檔
  剪不到什麼，送原音檔，切點交給分段轉錄另外找（Silero），和以前一樣。

找靜音只看音量（RMS，見 :func:`app.services.vad.preprocess.run_vad_extraction`），用不到 Silero：
沒有 Silero 也照樣去靜音。找不到有聲段（全段靜音、轉檔失敗）時送原音檔。開了
``VAD_KEEP_ARTIFACTS`` 時，只剩語音的音檔與有聲段存進 vad_artifacts/，給本機檢查切得對不對。

批次（tasks/batch_core.py）還自己判斷門檻與存檔，改用語音視圖是 #115；它還原 LRC 時間用的已經是
這裡的 :class:`SpeechTimeline`。VAD 測試端點（services/vad/test.py）不轉錄，只顯示去靜音找到的
有聲段，判斷會不會剪用這裡的 :func:`worth_removing`。
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, replace
from functools import cached_property
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.core.config import get_settings
from app.services.vad.artifacts import persist_speech_extraction
from app.services.vad.preprocess import run_vad_extraction
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

JUNCTION_TOLERANCE = 1e-6
"""有聲段交界的容許誤差（秒）：離交界這麼近的時間都算落在交界上，吸收浮點誤差。"""

Span = Tuple[float, float]
"""一段時間的（起, 迄）秒數。"""


@dataclass(frozen=True)
class SpeechTimeline:
    """語音視圖的時間怎麼對回原音檔：去靜音保留下來的有聲段，依序無縫接成語音視圖。

    ``voiced`` 是有聲段在原音檔時間軸上的（起, 迄）秒數，依時間排列、互不重疊；空的代表沒有
    去靜音，時間原樣對回去。
    """

    voiced: Tuple[Span, ...] = ()

    @cached_property
    def _offsets(self) -> List[float]:
        """有聲段在語音視圖上的位置：第 i 段從 ``_offsets[i]`` 秒到 ``_offsets[i + 1]`` 秒，
        最後一個是語音視圖的長度。"""
        offsets = [0.0]
        for start, end in self.voiced:
            offsets.append(offsets[-1] + (end - start))
        return offsets

    @property
    def junctions(self) -> Tuple[float, ...]:
        """有聲段在語音視圖上的交界（秒）：原本是靜音的地方，切在這裡不會切斷句子。"""
        return tuple(self._offsets[1:-1])

    def to_original(self, seconds: float, *, end: bool = False) -> float:
        """語音視圖上的一個時間還原回原音檔的時間軸；沒有去靜音時原樣傳回。

        ``end`` 是這個時間是不是一段（片段或詞）的結束，只在剛好落在有聲段的交界（前後
        :data:`JUNCTION_TOLERANCE` 秒內）時有差別：開始算後一段，結束算前一段。在交界開始的是
        從後一段才開始說，在交界結束的在前一段就說完了，都不包含中間剪掉的靜音；浮點誤差讓時間
        落在交界的哪一邊，結果都一樣。超出語音視圖的時間（模型給的時間超出音檔，或浮點誤差）
        夾到最後一段的結尾，負的時間夾到第一段的開頭。
        """
        if not self.voiced:
            return seconds
        offsets = self._offsets
        # 落在第幾段：數它前面有幾個交界（交界是 offsets[1] 到 offsets[-2]）
        last = len(self.voiced)
        if end:
            index = bisect_left(offsets, seconds - JUNCTION_TOLERANCE, 1, last) - 1
        else:
            index = bisect_right(offsets, seconds + JUNCTION_TOLERANCE, 1, last) - 1
        start, stop = self.voiced[index]
        if seconds >= offsets[index + 1]:
            # 結束剛好在交界之後一點點，或超出語音視圖：這一段的結尾
            return stop
        if seconds < offsets[index]:
            # 開始剛好在交界之前一點點：這一段的開頭
            return start
        return start + (seconds - offsets[index])

    def restore(self, segments: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        """片段（連同逐字時間）的時間還原回原音檔，回傳新的片段；沒有去靜音時時間不變。

        開始照開始、結束照結束還原（見 :meth:`to_original`）。零長度的一段（片段或詞）剛好落在
        交界時，開始算後一段、結束算前一段會顛倒，這時結束跟著開始。沒有時間的欄位（例如 Gemini
        沒寫結束的片段）維持沒有。
        """
        restored: List[Dict[str, Any]] = []
        for segment in segments:
            new = dict(segment)
            start, end = self._restored_interval(segment.get("start", 0.0), segment.get("end"))
            new["start"] = start
            if segment.get("end") is not None:
                new["end"] = end
            if segment.get("words"):
                new["words"] = [self._restored_word(word) for word in segment["words"]]
            restored.append(new)
        return restored

    def _restored_word(self, word: Mapping[str, Any]) -> Dict[str, Any]:
        start, end = self._restored_interval(word.get("start"), word.get("end"))
        return {**word, "start": start, "end": end}

    def _restored_interval(self, start: Optional[float],
                           end: Optional[float]) -> Tuple[Optional[float], Optional[float]]:
        if start is None or end is None:
            return (None if start is None else self.to_original(start),
                    None if end is None else self.to_original(end, end=True))
        restored_start = self.to_original(start)
        restored_end = self.to_original(end, end=True)
        if start <= end and restored_end < restored_start:
            restored_end = restored_start
        return restored_start, restored_end


@dataclass(frozen=True)
class SpeechView:
    """語音視圖：實際送進模型的音檔，以及把其中的時間還原回原音檔的對照。

    由 :func:`speech_view` 產生。去靜音之後是只剩語音的音檔；沒有去靜音時就是原音檔本身，
    時間還原是恆等。
    """

    audio: Path
    """要送進模型的音檔。"""
    duration: float
    """:attr:`audio` 的長度（秒）。"""
    timeline: SpeechTimeline = SpeechTimeline()
    """:attr:`audio` 的時間怎麼對回原音檔。"""
    silence_boundaries: Tuple[float, ...] = ()
    """:attr:`audio` 裡的靜音位置（秒），分段轉錄優先切在這裡：去靜音之後是有聲段的交界，不剪
    靜音的模型是原音檔裡每段靜音的正中間；跳過去靜音時沒有，切點交給分段轉錄另外找。"""
    temp_files: Tuple[Path, ...] = ()
    """這裡產生的暫存檔（轉成的 wav、只剩語音的音檔），呼叫端用完要清掉；輸入音檔不在裡面。"""

    @property
    def removed_silence(self) -> bool:
        """送進模型的是剪掉靜音之後的音檔。"""
        return bool(self.timeline.voiced)

    def restore(self, segments: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        """轉錄結果的片段還原回原音檔的時間軸，見 :meth:`SpeechTimeline.restore`。"""
        return self.timeline.restore(segments)


def worth_removing(speech_ratio: float) -> bool:
    """語音佔比低於門檻（``VAD_SPEECH_RATIO_SKIP_THRESHOLD``，預設 90%）才值得剪掉靜音：幾乎全是
    語音的音檔剪不到什麼。"""
    return speech_ratio < get_settings().vad_speech_ratio_skip_threshold


def speech_view(
    audio: Path,
    duration: float,
    *,
    remove_silence: bool,
    temp_dir: Path,
    task_id: str,
    original_filename: str,
) -> SpeechView:
    """單檔任務的去靜音只有這個入口：這段音檔的語音視圖。剪不剪見模組說明。

    ``duration`` 是 ``audio`` 的長度（秒），沒剪靜音時就是語音視圖的長度；``remove_silence``
    是模型能力的「轉錄前要不要剪掉靜音」。產生的暫存檔放在 ``temp_dir``，列在語音視圖的
    ``temp_files``，剪不剪都由呼叫端清掉。``task_id`` 與 ``original_filename`` 只用來替
    vad_artifacts/ 底下的資料夾命名（見 :func:`persist_speech_extraction`）。

    轉檔、讀檔或找有聲段失敗時，送原音檔。
    """
    found = run_vad_extraction(audio, temp_dir, write_speech_only=remove_silence)
    unchanged = SpeechView(audio=audio, duration=duration, temp_files=tuple(found.cleanup_files))
    if not found.success:
        return unchanged
    voiced = tuple((segment["start"], segment["end"]) for segment in found.segments)

    if not remove_silence:
        # 不剪靜音的模型：送原音檔，兩個有聲段中間那段靜音的正中間當切點
        midpoints = tuple((end + start) / 2
                          for (_, end), (start, _) in zip(voiced, voiced[1:], strict=False))
        logger.info(f"不剪靜音的模型：送原音檔，{len(midpoints)} 段靜音的正中間當切點")
        return replace(unchanged, silence_boundaries=midpoints)

    use_speech_only = worth_removing(found.speech_ratio)
    if found.speech_only_path is not None:
        persist_speech_extraction(
            task_id=task_id,
            original_filename=original_filename,
            speech_only_path=found.speech_only_path,
            segments=found.segments,
            speech_ratio=found.speech_ratio,
            speech_duration=found.speech_duration,
            total_duration=duration,
            used_for_transcription=use_speech_only,
        )
    if not use_speech_only or found.speech_only_path is None:
        logger.info(f"去靜音：語音佔比 {found.speech_ratio:.1%}，不低於門檻，送原音檔")
        return unchanged

    timeline = SpeechTimeline(voiced)
    logger.info(f"去靜音：語音佔比 {found.speech_ratio:.1%}，送只剩語音的音檔"
                f"（{found.speech_duration:.1f} 秒／{duration:.1f} 秒）")
    return replace(unchanged, audio=found.speech_only_path, duration=found.speech_duration,
                   timeline=timeline, silence_boundaries=timeline.junctions)
