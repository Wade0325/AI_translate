"""VAD 前處理共用模組。

`transcription/flows.py`（單檔轉錄）與 `celery/batch_task.py`（批次轉錄）
皆需要先把音檔轉成 wav 再用 Silero VAD 萃取「純語音」檔，這裡集中
該流程，回傳結構化結果。是否要採用純語音檔（例如語音佔比閾值判斷）
由呼叫端依情境決定。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from app.services.vad.flows import extract_speech_segments
from app.services.vad.models import VADProcessRequest
from app.utils.audio import convert_to_wav
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class VadPreprocessResult:
    """VAD 前處理回傳結果。

    Attributes:
        success: 是否成功取得純語音檔（False 代表呼叫端應回退到原始檔）。
        speech_only_path: 純語音 wav 檔路徑（success=False 時為 None）。
        segments: 每個語音片段的 {"start", "end"} 字典列表。
        speech_ratio: 語音佔總時長的比例（0.0~1.0）。
        speech_duration: 純語音總時長（秒）。
        cleanup_files: 流程中產生、呼叫端應負責清理的暫存檔案。
    """

    success: bool
    speech_only_path: Optional[Path] = None
    segments: List[dict] = field(default_factory=list)
    speech_ratio: float = 1.0
    speech_duration: float = 0.0
    cleanup_files: List[Path] = field(default_factory=list)


def run_vad_extraction(
    audio_path: Path,
    temp_dir: Path,
    vad_service,
) -> VadPreprocessResult:
    """執行 VAD 純語音提取流程。

    流程：
      1. 將輸入轉成 wav（若已是 wav 則略過）
      2. 呼叫 Silero VAD 提取語音段
      3. 回傳結構化結果與待清理檔案清單

    任何步驟失敗皆回傳 ``success=False``，由呼叫端決定是否回退到原始檔。
    """
    cleanup_files: List[Path] = []

    if vad_service is None:
        return VadPreprocessResult(success=False, cleanup_files=cleanup_files)

    try:
        wav_path = convert_to_wav(audio_path, temp_dir)
    except Exception as e:
        logger.warning(f"VAD 前處理：轉 wav 失敗 ({audio_path.name}): {e}")
        return VadPreprocessResult(success=False, cleanup_files=cleanup_files)

    if wav_path is None:
        logger.warning(f"VAD 前處理：無法轉換 {audio_path.name} 為 WAV")
        return VadPreprocessResult(success=False, cleanup_files=cleanup_files)

    if wav_path != audio_path:
        cleanup_files.append(wav_path)

    try:
        request = VADProcessRequest(
            audio_path=str(wav_path),
            output_dir=str(temp_dir),
        )
        extraction = extract_speech_segments(request, vad_service)
    except Exception as e:
        logger.warning(f"VAD 前處理：提取語音段失敗 ({audio_path.name}): {e}")
        return VadPreprocessResult(success=False, cleanup_files=cleanup_files)

    if not extraction.success or not extraction.speech_only_path:
        logger.warning(f"VAD 提取失敗 ({audio_path.name})")
        return VadPreprocessResult(success=False, cleanup_files=cleanup_files)

    speech_path = Path(extraction.speech_only_path)
    cleanup_files.append(speech_path)

    segments = [
        {"start": seg.start, "end": seg.end}
        for seg in extraction.segments
    ]

    return VadPreprocessResult(
        success=True,
        speech_only_path=speech_path,
        segments=segments,
        speech_ratio=extraction.speech_ratio,
        speech_duration=extraction.total_speech_duration,
        cleanup_files=cleanup_files,
    )
