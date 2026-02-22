import soundfile as sf
import numpy as np
import torchaudio
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


def extract_speech_segments(request: VADProcessRequest, vad_service=None) -> SpeechExtractionResult:
    """
    使用音量閾值提取有聲片段並建立純語音檔案 (針對 ASMR 優化)

    Args:
        request: VAD 處理請求
        vad_service: (現在不需依賴 VAD 模型，但為保持向下相容保留參數)
    """
    logger.info(f"開始提取有聲片段 (音量閾值模式): {Path(request.audio_path).name}")

    try:
        # 讀取音訊
        logger.info("正在讀取音訊檔案...")
        waveform, original_sr = torchaudio.load(request.audio_path)
        audio_data = waveform.numpy().T if waveform.shape[0] > 1 else waveform.squeeze(0).numpy()
        
        # 計算總長度
        num_frames = audio_data.shape[0] if audio_data.ndim > 1 else len(audio_data)
        total_duration = num_frames / original_sr
        
        # 檢測有聲片段 (RMS based) 
        logger.info("正在分析音量以檢測有聲片段...")
        # 轉成單聲道計算能量
        mono_data = audio_data.mean(axis=1) if audio_data.ndim > 1 else audio_data
        
        # 50ms 窗口計算 RMS
        frame_length_s = 0.05
        frame_length = int(frame_length_s * original_sr)
        
        if len(mono_data) < frame_length:
            return SpeechExtractionResult(success=False, total_duration=total_duration)
            
        pad_len = frame_length - (len(mono_data) % frame_length)
        if pad_len != frame_length:
            mono_data = np.pad(mono_data, (0, pad_len))
            
        frames = mono_data.reshape(-1, frame_length)
        rms = np.sqrt(np.mean(frames**2, axis=1) + 1e-10) # 避免計算結果等於 0
        
        # 相對音量閾值：以最大音量為基準 (-45dB 或是絕對最小值)
        max_rms = np.max(rms)
        if max_rms < 1e-4:
            logger.warning("音軌完全無聲")
            return SpeechExtractionResult(success=False, total_duration=total_duration)
            
        threshold = max(max_rms * 0.005, 0.0005) 
        is_speech = rms > threshold
        
        # 平滑處理：填補短靜音，移除極短的有聲段
        # 靜音持續超過 1.0 秒才視為真正的靜音 (ASMR 的空白可能較多)
        min_silence_frames = int(1.0 / frame_length_s)
        # 聲音至少要持續 0.1 秒才不算是雜訊
        min_speech_frames = int(0.1 / frame_length_s)
        
        # 填補短靜音
        current_silence = 0
        for i in range(len(is_speech)):
            if not is_speech[i]:
                current_silence += 1
            else:
                if 0 < current_silence < min_silence_frames:
                    is_speech[i-current_silence:i] = True
                current_silence = 0
        
        # 產生時間戳
        speech_timestamps = []
        is_in_speech = False
        start_frame = 0
        
        for i, speech_flag in enumerate(is_speech):
            if speech_flag and not is_in_speech:
                start_frame = i
                is_in_speech = True
            elif not speech_flag and is_in_speech:
                end_frame = i
                if end_frame - start_frame >= min_speech_frames:
                    # 給每個片段增加 0.3 秒的安全邊距
                    start_time = max(0.0, start_frame * frame_length_s - 0.3)
                    end_time = min(total_duration, end_frame * frame_length_s + 0.3)
                    speech_timestamps.append({'start': float(start_time), 'end': float(end_time)})
                is_in_speech = False
                
        if is_in_speech:
            end_frame = len(is_speech)
            if end_frame - start_frame >= min_speech_frames:
                start_time = max(0.0, start_frame * frame_length_s - 0.3)
                end_time = float(total_duration)
                speech_timestamps.append({'start': start_time, 'end': end_time})
                
        # 合併可能因為增加安全邊距而重疊的片段
        merged_timestamps = []
        for ts in speech_timestamps:
            if not merged_timestamps:
                merged_timestamps.append(ts)
            else:
                last_ts = merged_timestamps[-1]
                if ts['start'] <= last_ts['end']:
                    last_ts['end'] = max(last_ts['end'], ts['end'])
                else:
                    merged_timestamps.append(ts)
                    
        speech_timestamps = merged_timestamps

        if not speech_timestamps:
            logger.warning("未檢測到任何高於閾值的有聲片段")
            return SpeechExtractionResult(
                success=False,
                total_duration=total_duration
            )

        # 收集所有有聲片段
        speech_segments = []
        for ts in speech_timestamps:
            start_sample = max(0, int(ts['start'] * original_sr))
            end_sample = min(num_frames, int(ts['end'] * original_sr))
            
            segment_data = audio_data[start_sample:end_sample]
            if len(segment_data) > 0:
                speech_segments.append(segment_data)

        # 拼接所有語音片段
        concatenated_audio = np.concatenate(speech_segments)

        # 儲存純語音檔案
        output_path = Path(request.output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        input_filename = Path(request.audio_path).stem
        output_file = output_path / f"{input_filename}_speech_only.wav"

        sf.write(str(output_file), concatenated_audio, original_sr)
        logger.info(f"純有聲檔案已儲存: {output_file}")

        # 計算統計資訊
        segments = _convert_segments_to_pydantic(speech_timestamps)
        total_speech_duration = sum(seg.duration for seg in segments)

        logger.info(f"有聲段提取完成:")
        logger.info(f"  - 有聲片段數: {len(segments):>6}")
        logger.info(f"  - 總有聲時長: {total_speech_duration:>6.2f} 秒")
        logger.info(
            f"  - 有聲佔比:   {(total_speech_duration/total_duration)*100:>6.1f}%")

        return SpeechExtractionResult(
            success=True,
            speech_only_path=str(output_file),
            segments=segments,
            total_speech_duration=total_speech_duration,
            total_duration=total_duration
        )

    except Exception as e:
        logger.error(f"有聲段提取失敗: {e}", exc_info=True)
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

        # 讀取音訊（使用 torchaudio 支援 M4A 等格式）
        wav = read_audio(request.audio_path, sampling_rate=SAMPLING_RATE)
        waveform, original_sr = torchaudio.load(request.audio_path)
        audio_data = waveform.numpy().T if waveform.shape[0] > 1 else waveform.squeeze(0).numpy()
        total_duration = len(audio_data) / original_sr if audio_data.ndim == 1 else audio_data.shape[0] / original_sr

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
