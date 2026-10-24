import warnings

import soundfile as sf
from pathlib import Path

from app.utils.logger import setup_logger
from .models import (
    AudioSplitResult,
    AudioSplitRequest
)

logger = setup_logger(__name__)

SAMPLING_RATE = 16000


def split_audio_on_silence(request: AudioSplitRequest, vad_service) -> AudioSplitResult:
    """用 Silero VAD 找出最接近中點的靜音間隙，將音訊分割為兩個 wav。"""
    logger.info(f"開始分割音訊: {Path(request.audio_path).name}")

    try:
        model, utils = vad_service.get_model_and_utils()
        get_speech_timestamps, _, read_audio, _, _ = utils

        # 呼叫端保證已轉為 WAV。silero 的 read_audio 內部使用 torchaudio
        # 已棄用的 I/O API（load / sox_effects，依安裝來源而異），僅在此局部抑制棄用警告
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            wav = read_audio(request.audio_path, sampling_rate=SAMPLING_RATE)
        audio_data, original_sr = sf.read(request.audio_path, dtype="float32")
        total_duration = len(audio_data) / original_sr if audio_data.ndim == 1 else audio_data.shape[0] / original_sr

        speech_timestamps = get_speech_timestamps(
            wav, model, sampling_rate=SAMPLING_RATE, return_seconds=True)

        if not speech_timestamps:
            return AudioSplitResult(
                success=False,
                error_message="未檢測到語音片段"
            )

        # 在所有夠長的靜音間隙中，挑最接近音檔中點者作為分割點
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

        split_sample = int(best_split_point * original_sr)
        part1_data = audio_data[:split_sample]
        part2_data = audio_data[split_sample:]

        output_path = Path(request.output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        input_filename = Path(request.audio_path).stem
        part1_file = output_path / f"{input_filename}.part1.wav"
        part2_file = output_path / f"{input_filename}.part2.wav"

        sf.write(str(part1_file), part1_data, original_sr)
        sf.write(str(part2_file), part2_data, original_sr)

        logger.info("音訊分割完成:")
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
