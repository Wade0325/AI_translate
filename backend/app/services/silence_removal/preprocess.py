"""去靜音的前處理：先把音檔轉成 wav，再以 RMS 音量閾值找出有聲段（`intervals.extract_speech_intervals`，
不使用 Silero），需要時接成只剩語音的音檔，回傳結構化結果。是否要採用只剩語音的音檔
（例如語音佔比閾值判斷）由呼叫端依情境決定。

單檔任務與批次的去靜音經 :func:`app.services.silence_removal.speech_view` 拿到語音視圖，它也用這裡找
有聲段。還直接呼叫這裡的：去靜音與切點預覽的端點與 tests/ 底下的工具腳本。

Silero VAD 只在分段轉錄找切點時用（:mod:`app.services.vad`，見
:mod:`app.services.chunked_transcription`）：依單次長度分段與失敗後的切段重試用同一套切點。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from app.services.silence_removal.intervals import SpeechIntervalRequest, extract_speech_intervals
from app.utils.audio import convert_to_wav
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class SilenceRemovalResult:
    """去靜音前處理的結果。

    Attributes:
        success: 是否找到有聲段（要寫只剩語音的音檔時，也要寫成）；False 代表呼叫端應回退到原音檔。
        speech_only_path: 只剩語音的 wav 檔路徑；沒有寫或 success=False 時為 None。
        segments: 每個有聲段的 {"start", "end"} 字典列表（原音檔的時間軸）。
        speech_ratio: 語音佔總時長的比例（0.0~1.0）。
        speech_duration: 有聲段的總長（秒）。
        cleanup_files: 流程中產生、呼叫端應負責清理的暫存檔案。
    """

    success: bool
    speech_only_path: Optional[Path] = None
    segments: List[dict] = field(default_factory=list)
    speech_ratio: float = 1.0
    speech_duration: float = 0.0
    cleanup_files: List[Path] = field(default_factory=list)


def remove_silence(
    audio_path: Path,
    temp_dir: Path,
    *,
    write_speech_only: bool = True,
) -> SilenceRemovalResult:
    """執行去靜音的前處理；只看音量，不需要 Silero。

    流程：
      1. 將輸入轉成 wav（若已是 wav 則略過）
      2. 以 RMS 音量閾值找出有聲段（`intervals.extract_speech_intervals`）；``write_speech_only``
         時再接成只剩語音的音檔
      3. 回傳結構化結果與待清理檔案清單

    任何步驟失敗皆回傳 ``success=False``，由呼叫端決定是否回退到原音檔。
    """
    cleanup_files: List[Path] = []

    try:
        wav_path = convert_to_wav(audio_path, temp_dir)
    except Exception as e:
        logger.warning(f"去靜音：轉 wav 失敗 ({audio_path.name}): {e}")
        return SilenceRemovalResult(success=False, cleanup_files=cleanup_files)

    if wav_path is None:
        logger.warning(f"去靜音：無法轉換 {audio_path.name} 為 WAV")
        return SilenceRemovalResult(success=False, cleanup_files=cleanup_files)

    if wav_path != audio_path:
        cleanup_files.append(wav_path)

    try:
        request = SpeechIntervalRequest(
            audio_path=str(wav_path),
            output_dir=str(temp_dir),
            write_speech_only=write_speech_only,
        )
        extraction = extract_speech_intervals(request)
    except Exception as e:
        logger.warning(f"去靜音：找有聲段失敗 ({audio_path.name}): {e}")
        return SilenceRemovalResult(success=False, cleanup_files=cleanup_files)

    speech_path = Path(extraction.speech_only_path) if extraction.speech_only_path else None
    if speech_path is not None:
        cleanup_files.append(speech_path)

    if not extraction.success or (write_speech_only and speech_path is None):
        logger.warning(f"去靜音失敗 ({audio_path.name})")
        return SilenceRemovalResult(success=False, cleanup_files=cleanup_files)

    segments = [
        {"start": seg.start, "end": seg.end}
        for seg in extraction.segments
    ]

    return SilenceRemovalResult(
        success=True,
        speech_only_path=speech_path,
        segments=segments,
        speech_ratio=extraction.speech_ratio,
        speech_duration=extraction.total_speech_duration,
        cleanup_files=cleanup_files,
    )
