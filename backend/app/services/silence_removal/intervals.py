"""去靜音找有聲段：以 RMS 音量閾值找出有聲段，需要時接成只剩語音的音檔；不使用 Silero。

呼叫端是 :func:`app.services.silence_removal.preprocess.remove_silence`，它先把音檔轉成 wav。
"""

import soundfile as sf
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional

from pydantic import BaseModel, Field

from app.utils.logger import setup_logger

logger = setup_logger(__name__)


class SpeechInterval(BaseModel):
    """
    一個有聲段（原音檔的時間軸）
    """
    start: float = Field(..., description="有聲段開始時間（秒）")
    end: float = Field(..., description="有聲段結束時間（秒）")

    @property
    def duration(self) -> float:
        """有聲段時長"""
        return self.end - self.start


class SpeechIntervalRequest(BaseModel):
    """
    去靜音的處理請求
    """
    audio_path: str = Field(..., description="音訊檔案路徑")
    output_dir: str = Field(..., description="輸出目錄路徑")
    write_speech_only: bool = Field(
        default=True, description="是否把有聲段接成只剩語音的音檔寫進輸出目錄；只要有聲段時給 False")


class SpeechExtractionResult(BaseModel):
    """
    語音提取結果
    """
    success: bool = Field(..., description="是否成功")
    speech_only_path: Optional[str] = Field(default=None, description="純語音檔案路徑")
    segments: List[SpeechInterval] = Field(
        default_factory=list, description="有聲段列表")
    total_speech_duration: float = Field(default=0.0, description="總語音時長（秒）")
    total_duration: float = Field(default=0.0, description="原始音訊總時長（秒）")

    @property
    def speech_ratio(self) -> float:
        """語音佔比"""
        if self.total_duration > 0:
            return self.total_speech_duration / self.total_duration
        return 0.0


def _to_speech_intervals(segments: List[Dict[str, float]]) -> List[SpeechInterval]:
    """將原始的有聲段轉換為 Pydantic 模型"""
    return [SpeechInterval(start=seg['start'], end=seg['end']) for seg in segments]


def extract_speech_intervals(request: SpeechIntervalRequest) -> SpeechExtractionResult:
    """以 RMS 音量閾值找出有聲段，接成只剩語音的音檔（針對 ASMR 優化，不需 VAD 模型）；
    ``write_speech_only`` 為 False 時只找有聲段、不寫檔。"""
    logger.info(f"開始提取有聲段 (音量閾值模式): {Path(request.audio_path).name}")

    try:
        # 呼叫端保證已轉為 WAV，見 preprocess.remove_silence
        audio_data, original_sr = sf.read(request.audio_path, dtype="float32")

        num_frames = audio_data.shape[0] if audio_data.ndim > 1 else len(audio_data)
        total_duration = num_frames / original_sr

        logger.info("正在分析音量以檢測有聲段...")
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
        rms = np.sqrt(np.mean(frames**2, axis=1) + 1e-10)  # +1e-10 避免 sqrt(0)

        # 相對音量閾值：最大音量的 0.005 倍（約 −46 dB），且不低於絕對下限 0.0005
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
                    # 給每個有聲段增加 0.3 秒的安全邊距
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
                
        # 合併可能因為增加安全邊距而重疊的有聲段
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
            logger.warning("未檢測到任何高於閾值的有聲段")
            return SpeechExtractionResult(
                success=False,
                total_duration=total_duration
            )

        output_file = None
        if request.write_speech_only:
            speech_segments = []
            for ts in speech_timestamps:
                start_sample = max(0, int(ts['start'] * original_sr))
                end_sample = min(num_frames, int(ts['end'] * original_sr))

                segment_data = audio_data[start_sample:end_sample]
                if len(segment_data) > 0:
                    speech_segments.append(segment_data)

            concatenated_audio = np.concatenate(speech_segments)

            output_path = Path(request.output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            input_filename = Path(request.audio_path).stem
            output_file = output_path / f"{input_filename}_speech_only.wav"

            sf.write(str(output_file), concatenated_audio, original_sr)
            logger.info(f"只剩語音的音檔已儲存: {output_file}")

        segments = _to_speech_intervals(speech_timestamps)
        total_speech_duration = sum(seg.duration for seg in segments)

        logger.info("有聲段提取完成:")
        logger.info(f"  - 有聲段數:   {len(segments):>6}")
        logger.info(f"  - 總有聲時長: {total_speech_duration:>6.2f} 秒")
        logger.info(
            f"  - 有聲佔比:   {(total_speech_duration/total_duration)*100:>6.1f}%")

        return SpeechExtractionResult(
            success=True,
            speech_only_path=str(output_file) if output_file else None,
            segments=segments,
            total_speech_duration=total_speech_duration,
            total_duration=total_duration
        )

    except Exception as e:
        logger.error(f"有聲段提取失敗: {e}", exc_info=True)
        return SpeechExtractionResult(success=False)
