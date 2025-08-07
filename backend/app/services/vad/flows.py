import soundfile as sf
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional

from app.utils.logger import setup_logger
from .models import (
    SpeechSegment,
    SpeechExtractionResult,
    AudioSplitResult,
    VADProcessRequest,
    AudioSplitRequest
)

logger = setup_logger(__name__)

SAMPLING_RATE = 16000


def _convert_segments_to_pydantic(segments: List[Dict[str, float]]) -> List[SpeechSegment]:
    """將原始片段轉換為 Pydantic 模型"""
    return [SpeechSegment(start=seg['start'], end=seg['end']) for seg in segments]


def extract_speech_segments(request: VADProcessRequest, vad_service) -> SpeechExtractionResult:
    """
    使用 VAD 提取語音片段並建立純語音檔案

    Args:
        request: VAD 處理請求
        vad_service: VADService 實例，用於取得模型
    """
    logger.info(f"開始提取語音片段: {Path(request.audio_path).name}")

    try:
        # 從 service 取得模型和工具
        model, utils = vad_service.get_model_and_utils()
        get_speech_timestamps, _, read_audio, _, _ = utils

        # 讀取並預處理音訊
        logger.info("正在讀取音訊檔案...")
        wav = read_audio(request.audio_path, sampling_rate=SAMPLING_RATE)

        # 檢測語音片段
        logger.info("正在檢測語音片段...")
        speech_timestamps = get_speech_timestamps(
            wav, model, sampling_rate=SAMPLING_RATE, return_seconds=True)

        if not speech_timestamps:
            logger.warning("未檢測到任何語音片段")
            return SpeechExtractionResult(
                success=False,
                total_duration=len(wav) / SAMPLING_RATE
            )

        # 載入原始音訊以保持品質
        audio_data, original_sr = sf.read(request.audio_path)
        total_duration = len(audio_data) / original_sr

        # 收集所有語音片段
        speech_segments = []
        for ts in speech_timestamps:
            start_sample = int((ts['start'] / SAMPLING_RATE) * original_sr)
            end_sample = int((ts['end'] / SAMPLING_RATE) * original_sr)
            segment_data = audio_data[start_sample:end_sample]
            speech_segments.append(segment_data)

        # 拼接所有語音片段
        concatenated_audio = np.concatenate(speech_segments)

        # 儲存純語音檔案
        output_path = Path(request.output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        input_filename = Path(request.audio_path).stem
        output_file = output_path / f"{input_filename}_speech_only.wav"

        sf.write(str(output_file), concatenated_audio, original_sr)
        logger.info(f"純語音檔案已儲存: {output_file}")

        # 計算統計資訊
        segments = _convert_segments_to_pydantic(speech_timestamps)
        total_speech_duration = sum(seg.duration for seg in segments)

        logger.info(f"語音提取完成:")
        logger.info(f"  - 語音片段數: {len(segments):>6}")
        logger.info(f"  - 總語音時長: {total_speech_duration:>6.2f} 秒")
        logger.info(
            f"  - 語音佔比:   {(total_speech_duration/total_duration)*100:>6.1f}%")

        return SpeechExtractionResult(
            success=True,
            speech_only_path=str(output_file),
            segments=segments,
            total_speech_duration=total_speech_duration,
            total_duration=total_duration
        )

    except Exception as e:
        logger.error(f"語音提取失敗: {e}")
        return SpeechExtractionResult(success=False)


def split_audio_on_silence(request: AudioSplitRequest, vad_service) -> AudioSplitResult:
    """
    在靜音處分割音訊檔案

    Args:
        request: 音訊分割請求
        vad_service: VADService 實例，用於取得模型
    """
    logger.info(f"開始分割音訊: {Path(request.audio_path).name}")

    try:
        # 從 service 取得模型和工具
        model, utils = vad_service.get_model_and_utils()
        get_speech_timestamps, _, read_audio, _, _ = utils

        # 讀取音訊
        wav = read_audio(request.audio_path, sampling_rate=SAMPLING_RATE)
        audio_data, original_sr = sf.read(request.audio_path)
        total_duration = len(audio_data) / original_sr

        # 檢測語音片段
        speech_timestamps = get_speech_timestamps(
            wav, model, sampling_rate=SAMPLING_RATE, return_seconds=True)

        if not speech_timestamps:
            return AudioSplitResult(
                success=False,
                error_message="未檢測到語音片段"
            )

        # 尋找最佳分割點（與原邏輯相同）
        best_split_point = None
        max_silence_duration = 0

        for i in range(len(speech_timestamps) - 1):
            current_end = speech_timestamps[i]['end']
            next_start = speech_timestamps[i + 1]['start']
            silence_duration = next_start - current_end

            if silence_duration >= request.min_silence_duration:
                midpoint = total_duration / 2
                distance_from_mid = abs(
                    (current_end + next_start) / 2 - midpoint)

                if best_split_point is None or distance_from_mid < abs(best_split_point - midpoint):
                    best_split_point = (current_end + next_start) / 2
                    max_silence_duration = silence_duration

        if best_split_point is None:
            best_split_point = total_duration / 2
            logger.warning("未找到合適的靜音間隙，在中點分割")
        else:
            logger.info(
                f"找到分割點: {best_split_point:.2f}秒（靜音時長: {max_silence_duration:.2f}秒）")

        # 分割音訊
        split_sample = int(best_split_point * original_sr)
        part1_data = audio_data[:split_sample]
        part2_data = audio_data[split_sample:]

        # 儲存分割後的檔案
        output_path = Path(request.output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        input_filename = Path(request.audio_path).stem
        part1_file = output_path / f"{input_filename}.part1.wav"
        part2_file = output_path / f"{input_filename}.part2.wav"

        sf.write(str(part1_file), part1_data, original_sr)
        sf.write(str(part2_file), part2_data, original_sr)

        logger.info(f"音訊分割完成:")
        logger.info(
            f"  - Part 1: {part1_file.name} ({best_split_point:>6.2f}秒)")
        logger.info(
            f"  - Part 2: {part2_file.name} ({total_duration - best_split_point:>6.2f}秒)")

        return AudioSplitResult(
            success=True,
            part1_path=str(part1_file),
            part2_path=str(part2_file),
            split_point=best_split_point
        )

    except Exception as e:
        logger.error(f"音訊分割失敗: {e}")
        return AudioSplitResult(
            success=False,
            error_message=str(e)
        )
